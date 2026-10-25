"""Бизнес-логика: совместимость, подбор доноров, запасы, резервирование, прогноз, перераспределение."""
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import asin, ceil, cos, radians, sin, sqrt

from .db import now

# компонент: (срок хранения, дней; интервал между донациями, дней)
COMPONENTS = {"red_cells": (42, 56), "platelets": (5, 14), "plasma": (365, 14), "whole_blood": (35, 56)}
ABO_TO = {"O": {"O", "A", "B", "AB"}, "A": {"A", "AB"}, "B": {"B", "AB"}, "AB": {"AB"}}  # кому можно эритроциты
EXPIRING_HOURS = 72
THRESHOLD = 3  # порог дефицита по региону, единиц


# запись на визит: часы приёма станций (местное время), вместимость слота, горизонт записи
LOCAL_TZ = timezone(timedelta(hours=int(os.getenv("BPSC_TZ_OFFSET", "5"))))  # Астана, UTC+5
SLOT_HOURS = range(9, 17)  # 09:00 … 16:00, шаг 1 час
SLOT_CAPACITY = 2
BOOKING_DAYS = 30


def local_today() -> date:
    return datetime.now(LOCAL_TZ).date()


def slot_utc(d: date, hour: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def day_slots(d: date) -> list[datetime]:
    """Слоты дня в UTC; воскресенье — выходной."""
    return [] if d.weekday() == 6 else [slot_utc(d, h) for h in SLOT_HOURS]


def valid_slot(dt: datetime) -> bool:
    loc = dt.astimezone(LOCAL_TZ)
    if loc.minute or loc.second or loc.hour not in SLOT_HOURS or loc.weekday() == 6:
        return False
    return dt > datetime.now(timezone.utc) and loc.date() <= local_today() + timedelta(days=BOOKING_DAYS)


def next_eligible(last_donation: str | None, component: str) -> date:
    """Ближайшая дата, когда донор снова может сдавать данный компонент."""
    today = local_today()
    if not last_donation:
        return today
    return max(today, date.fromisoformat(last_donation) + timedelta(days=COMPONENTS[component][1]))


def compatible(component, dg, dr, rg, rr) -> bool:
    """Подходит ли кровь/компонент донора (dg, dr) реципиенту (rg, rr)."""
    if component in ("red_cells", "whole_blood"):
        return rg in ABO_TO[dg] and (dr == "-" or rr == "+")
    if component == "plasma":
        return dg in ABO_TO[rg]
    return dg == rg  # тромбоциты: одноимённая группа


def haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    a = sin((p2 - p1) / 2) ** 2 + cos(p1) * cos(p2) * sin(radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def hours_left(expires_at: str) -> float:
    return (datetime.fromisoformat(expires_at) - datetime.now(timezone.utc)).total_seconds() / 3600


def trace_event(conn, unit_id, event_type, actor_id, frm=None, to=None, note=None):
    conn.execute(
        "INSERT INTO trace(unit_id,event_type,from_institution,to_institution,actor_id,note,timestamp) "
        "VALUES(?,?,?,?,?,?,?)", (unit_id, event_type, frm, to, actor_id, note, now()))


def audit(conn, actor_id, action, target=None):
    conn.execute("INSERT INTO audit(actor_id,action,target,timestamp) VALUES(?,?,?,?)",
                 (actor_id, action, target, now()))


def find_donors(conn, req) -> list[dict]:
    """Подходящие доноры: совместимость, радиус, интервал между донациями, согласие, активная запись."""
    h = conn.execute("SELECT lat,lon FROM institutions WHERE id=?", (req["hospital_id"],)).fetchone()
    interval = COMPONENTS[req["component"]][1]
    today = datetime.now(timezone.utc).date()
    rows = conn.execute("SELECT d.* FROM donors d JOIN users u ON u.id=d.user_id "
                        "WHERE d.consent=1 AND u.active=1").fetchall()
    out = []
    for d in rows:
        if not compatible(req["component"], d["blood_group"], d["rh"], req["blood_group"], req["rh"]):
            continue
        dist = haversine(h["lat"], h["lon"], d["lat"], d["lon"])
        if dist > d["notify_radius_km"]:
            continue
        days = (today - date.fromisoformat(d["last_donation_date"])).days if d["last_donation_date"] else None
        if days is not None and days < interval:
            continue
        out.append({"donor_id": d["id"], "blood_group": d["blood_group"], "rh": d["rh"],
                    "distance_km": round(dist, 1), "days_since_last_donation": days})
    out.sort(key=lambda x: x["distance_km"])
    return out


def notify(conn, req) -> int:
    """Адресные уведомления только подходящим донорам; повторно одному донору не отправляются."""
    created = 0
    for m in find_donors(conn, req):
        cur = conn.execute("INSERT OR IGNORE INTO notifications(request_id,donor_id,sent_at) VALUES(?,?,?)",
                           (req["id"], m["donor_id"], now()))
        created += cur.rowcount
    return created


def available_units(conn, req) -> list:
    """Подходящие неистёкшие единицы региона; сначала одноимённая группа, затем с ближайшим сроком."""
    region = conn.execute("SELECT region FROM institutions WHERE id=?", (req["hospital_id"],)).fetchone()[0]
    rows = conn.execute(
        "SELECT u.* FROM units u JOIN institutions i ON i.id=u.institution_id "
        "WHERE i.region=? AND u.status='stored' AND u.expires_at>? AND u.component=?",
        (region, now(), req["component"])).fetchall()
    rows = [r for r in rows if compatible(req["component"], r["blood_group"], r["rh"], req["blood_group"], req["rh"])]
    rows.sort(key=lambda r: ((r["blood_group"], r["rh"]) != (req["blood_group"], req["rh"]), r["expires_at"]))
    return rows


def reserve(conn, req, actor_id) -> int:
    need = req["units_needed"] - req["reserved_units"]
    taken = 0
    for u in available_units(conn, req)[:max(need, 0)]:
        conn.execute("UPDATE units SET status='reserved', request_id=? WHERE id=?", (req["id"], u["id"]))
        trace_event(conn, u["id"], "reserved", actor_id, u["institution_id"], req["hospital_id"], f"заявка #{req['id']}")
        taken += 1
    total = req["reserved_units"] + taken
    status = "reserved" if total >= req["units_needed"] else ("partial" if total else req["status"])
    conn.execute("UPDATE requests SET reserved_units=?, status=? WHERE id=?", (total, status, req["id"]))
    return taken


def inventory(conn, user) -> dict:
    inst = None if user["role"] == "admin" else user["institution_id"]
    q = "SELECT * FROM units WHERE status IN ('testing','tested','stored','reserved')"
    mine = conn.execute(q + (" AND institution_id=?" if inst else ""), (inst,) if inst else ()).fetchall()
    units = []
    for u in mine:
        h = hours_left(u["expires_at"])
        units.append({**dict(u), "hours_left": round(h, 1), "expired": h <= 0, "expiring": 0 < h <= EXPIRING_HOURS})
    units.sort(key=lambda x: x["expires_at"])
    region = conn.execute("SELECT region FROM institutions WHERE id=?", (user["institution_id"],)).fetchone()
    reg = region[0] if region else None
    rows = conn.execute(
        "SELECT i.name, u.component, u.blood_group, u.rh, COUNT(*) c FROM units u JOIN institutions i "
        "ON i.id=u.institution_id WHERE u.status='stored' AND u.expires_at>? AND (? IS NULL OR i.region=?) "
        "GROUP BY 1,2,3,4", (now(), reg, reg)).fetchall()
    totals = defaultdict(int)
    for r in rows:
        totals[(r["component"], r["blood_group"], r["rh"])] += r["c"]
    deficits = [{"component": c, "blood_group": g, "rh": rh, "count": totals.get((c, g, rh), 0)}
                for c in ("red_cells", "platelets", "plasma") for g in ABO_TO for rh in "+-"
                if totals.get((c, g, rh), 0) < THRESHOLD]
    return {"units": units, "region_stock": [dict(r) for r in rows], "deficits": deficits, "threshold": THRESHOLD}


def forecast_need(conn, hospital_id=None) -> dict:
    """Скользящее среднее: сумма единиц по заявкам за 28 дней / 4 = ожидаемая потребность на 7 дней."""
    since = (datetime.now(timezone.utc) - timedelta(days=28)).isoformat(timespec="seconds")
    q = ("SELECT hospital_id,component,blood_group,rh,SUM(units_needed) s FROM requests "
         "WHERE created_at>=? AND status!='cancelled'" + (" AND hospital_id=?" if hospital_id else "") +
         " GROUP BY 1,2,3,4")
    rows = conn.execute(q, (since, hospital_id) if hospital_id else (since,)).fetchall()
    return {(r[0], r[1], r[2], r[3]): ceil(r[4] / 4) for r in rows}


def rebalance(conn) -> list[dict]:
    """Рекомендации: из учреждений с избытком (сначала единицы с ближайшим сроком) туда, где прогноз выше запаса."""
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM institutions")}
    need = forecast_need(conn)
    stock = defaultdict(list)
    for u in conn.execute("SELECT * FROM units WHERE status='stored' AND expires_at>? ORDER BY expires_at", (now(),)):
        stock[(u["institution_id"], u["component"], u["blood_group"], u["rh"])].append(u)
    surplus = {k: len(v) - need.get(k, 0) for k, v in stock.items()}
    used, recs = defaultdict(int), []
    for (hid, c, g, r), n in sorted(need.items()):
        deficit = n - len(stock.get((hid, c, g, r), []))
        if deficit <= 0:
            continue
        sources = sorted(((k, v) for k, v in stock.items() if k[1:] == (c, g, r) and k[0] != hid and surplus[k] > 0),
                         key=lambda kv: kv[1][0]["expires_at"])
        for k, v in sources:
            take = min(deficit, surplus[k])
            units = v[used[k]:used[k] + take]
            used[k] += take
            surplus[k] -= take
            deficit -= take
            urgent = hours_left(units[0]["expires_at"]) <= EXPIRING_HOURS
            recs.append({"from_institution_id": k[0], "from": names[k[0]], "to_institution_id": hid, "to": names[hid],
                         "component": c, "blood_group": g, "rh": r, "units": take, "unit_ids": [u["id"] for u in units],
                         "reason": f"прогноз {n} ед./нед., на складе {len(stock.get((hid, c, g, r), []))}"
                                   + ("; срок годности истекает" if urgent else "")})
            if deficit <= 0:
                break
    return recs
