"Авторизация"
import os
import re
import sqlite3
import time
import asyncio
import logging
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator

from . import security as sec
from . import services as svc
from .db import get_db, init_db, now

Group = Literal["A", "B", "AB", "O"]
Rh = Literal["+", "-"]
Comp = Literal["red_cells", "platelets", "plasma", "whole_blood"]
EMAIL_RE = re.compile(r"^[^@\s'\";<>]+@[^@\s'\";<>]+\.[^@\s'\";<>]+$")
STATIC = Path(__file__).resolve().parent.parent / "static"
logger = logging.getLogger(__name__)


def expire_units(conn, actor_id=None, institution_id=None):
    q = "SELECT * FROM units WHERE status IN ('testing','tested','stored','reserved') AND expires_at<=?"
    args = [now()]
    if institution_id is not None:
        q, args = q + " AND institution_id=?", args + [institution_id]
    rows = conn.execute(q, args).fetchall()
    for row in rows:
        if row["status"] == "reserved" and row["request_id"]:
            req = conn.execute("SELECT reserved_units,status FROM requests WHERE id=?", (row["request_id"],)).fetchone()
            if req and req["status"] not in ("fulfilled", "cancelled"):
                reserved = max(req["reserved_units"] - 1, 0)
                status = "partial" if reserved else "open"
                conn.execute("UPDATE requests SET reserved_units=?,status=? WHERE id=?",
                             (reserved, status, row["request_id"]))
        conn.execute("UPDATE units SET status='discarded' WHERE id=?", (row["id"],))
        svc.trace_event(conn, row["id"], "discarded", actor_id, row["institution_id"], None, "истёк срок годности")
    return len(rows)


async def expiration_loop():
    while True:
        try:
            def run_sweep():
                from .db import connect
                conn = connect()
                try:
                    discarded = expire_units(conn)
                    conn.commit()
                    return discarded
                finally:
                    conn.close()

            count = await asyncio.to_thread(run_sweep)
            if count:
                logger.info("Автоматически списано просроченных единиц: %s", count)
        except Exception:
            logger.exception("Не удалось автоматически списать просроченные единицы")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_):
    init_db()
    if os.getenv("BPSC_AUTOSEED") == "1":
        from . import seed
        from .db import connect
        conn = connect()
        if not conn.execute("SELECT 1 FROM institutions").fetchone():
            seed.seed(conn)
        conn.close()
    expiry_task = asyncio.create_task(expiration_loop())
    try:
        yield
    finally:
        expiry_task.cancel()
        try:
            await expiry_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Blood & Plasma Supply Chain", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("BPSC_CORS", "").split(",") if o],
                   allow_methods=["*"], allow_headers=["*"])
_hits: dict = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    q = _hits[request.client.host if request.client else "?"]
    t = time.time()
    while q and q[0] < t - 60:
        q.popleft()
    if len(q) >= int(os.getenv("BPSC_RATE_LIMIT", "300")):
        return JSONResponse({"detail": "Слишком много запросов, повторите позже"}, status_code=429)
    q.append(t)
    return await call_next(request)


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error(_, __):
    return JSONResponse({"detail": "Операция нарушает ограничения данных"}, status_code=409)


@app.exception_handler(Exception)
async def unhandled(_, __):
    return JSONResponse({"detail": "Внутренняя ошибка сервера"}, status_code=500)



class Credentials(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v):
        if not EMAIL_RE.match(v):
            raise ValueError("Некорректный email")
        return v.lower()


class RegisterDonor(Credentials):
    full_name: str = Field(min_length=2, max_length=100)
    phone: str = Field(min_length=5, max_length=30)
    blood_group: Group
    rh: Rh
    last_donation_date: Optional[date] = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    notify_radius_km: int = Field(10, ge=1, le=200)
    consent: bool = True

    @field_validator("password")
    @classmethod
    def _pwd(cls, v):
        if len(v) < 8 or not re.search(r"[A-Za-zА-Яа-я]", v) or not re.search(r"\d", v):
            raise ValueError("Пароль: минимум 8 символов, буквы и цифры")
        return v

    @field_validator("last_donation_date")
    @classmethod
    def _past(cls, v):
        if v and v > date.today():
            raise ValueError("Дата в будущем")
        return v


class DonorUpdate(BaseModel):
    notify_radius_km: Optional[int] = Field(None, ge=1, le=200)
    consent: Optional[bool] = None
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)


class DonationIn(BaseModel):
    donor_id: int
    component: Comp
    volume_ml: int = Field(450, ge=50, le=1000)
    collected_at: Optional[datetime] = None


class RequestIn(BaseModel):
    component: Comp
    blood_group: Group
    rh: Rh
    units_needed: int = Field(ge=1, le=50)
    urgency: Literal["routine", "urgent", "critical"] = "urgent"


class EventIn(BaseModel):
    event_type: Literal["transferred", "transfused", "discarded"]
    to_institution_id: Optional[int] = None
    note: Optional[str] = Field(None, max_length=200)


class CloseIn(BaseModel):
    status: Literal["fulfilled", "cancelled"]


class RespondIn(BaseModel):
    accept: bool


class StaffIn(Credentials):
    role: Literal["station", "hospital", "admin"]
    institution_id: Optional[int] = None


class UserPatch(BaseModel):
    active: bool


class AppointmentIn(BaseModel):
    station_id: int
    slot_at: datetime
    component: Comp
    request_id: Optional[int] = None


class VisitDone(BaseModel):
    volume_ml: int = Field(450, ge=50, le=1000)

class TestResult(BaseModel):
    passed: bool



bearer = HTTPBearer(auto_error=False)


def current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer), conn=Depends(get_db)):
    if not creds:
        raise HTTPException(401, "Требуется вход")
    try:
        uid = int(sec.decode_token(creds.credentials)["sub"])
    except Exception:
        raise HTTPException(401, "Недействительный токен")
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or not u["active"]:
        raise HTTPException(401, "Учётная запись недоступна")
    return u


def roles(*allowed):
    def dep(u=Depends(current_user)):
        if u["role"] not in allowed:
            raise HTTPException(403, "Недостаточно прав")
        return u
    return dep


def get_request_for(conn, rid: int, user, owner_only=False):
    """ABAC: больница видит только свои заявки; станция — заявки своего региона."""
    r = conn.execute("SELECT r.*, i.region FROM requests r JOIN institutions i ON i.id=r.hospital_id WHERE r.id=?",
                     (rid,)).fetchone()
    if not r:
        raise HTTPException(404, "Заявка не найдена")
    if user["role"] == "hospital" and r["hospital_id"] != user["institution_id"]:
        raise HTTPException(403, "Чужая заявка")
    if user["role"] == "station":
        if owner_only:
            raise HTTPException(403, "Недостаточно прав")
        reg = conn.execute("SELECT region FROM institutions WHERE id=?", (user["institution_id"],)).fetchone()[0]
        if reg != r["region"]:
            raise HTTPException(403, "Заявка из другого региона")
    return r


def get_unit_for(conn, uid: int, user, strict=False):
    unit = conn.execute("SELECT * FROM units WHERE id=?", (uid,)).fetchone()
    if not unit:
        raise HTTPException(404, "Единица не найдена")
    if user["role"] == "admin" and not strict:
        return unit
    inst = user["institution_id"]
    mine = unit["institution_id"] == inst
    touched = conn.execute("SELECT 1 FROM trace WHERE unit_id=? AND (from_institution=? OR to_institution=?)",
                           (uid, inst, inst)).fetchone()
    if not (mine or (touched and not strict)):
        raise HTTPException(403, "Нет доступа к этой единице")
    return unit



@app.post("/api/auth/register", status_code=201)
def register(p: RegisterDonor, conn=Depends(get_db)):
    if conn.execute("SELECT 1 FROM users WHERE email=?", (p.email,)).fetchone():
        raise HTTPException(409, "Email уже зарегистрирован")
    cur = conn.execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,'donor')",
                       (p.email, sec.hash_password(p.password)))
    cur2 = conn.execute(
        "INSERT INTO donors(user_id,full_name_enc,contacts_enc,blood_group,rh,last_donation_date,lat,lon,"
        "notify_radius_km,consent) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (cur.lastrowid, sec.encrypt(p.full_name), sec.encrypt(p.phone), p.blood_group, p.rh,
         p.last_donation_date.isoformat() if p.last_donation_date else None, p.lat, p.lon,
         p.notify_radius_km, int(p.consent)))
    conn.commit()
    return {"user_id": cur.lastrowid, "donor_id": cur2.lastrowid, "token": sec.make_token(cur.lastrowid, "donor")}


@app.post("/api/auth/login")
def login(p: Credentials, conn=Depends(get_db)):
    u = conn.execute("SELECT * FROM users WHERE email=?", (p.email,)).fetchone()
    if u and u["failed_attempts"] >= 5:
        raise HTTPException(423, "Учётная запись заблокирована после 5 неудачных попыток")
    if not u or not u["active"] or not sec.verify_password(p.password, u["password_hash"]):
        if u:
            conn.execute("UPDATE users SET failed_attempts=failed_attempts+1 WHERE id=?", (u["id"],))
            conn.commit()
        raise HTTPException(401, "Неверный email или пароль")
    conn.execute("UPDATE users SET failed_attempts=0 WHERE id=?", (u["id"],))
    conn.commit()
    return {"token": sec.make_token(u["id"], u["role"]), "role": u["role"], "email": u["email"],
            "institution_id": u["institution_id"]}


@app.get("/api/me")
def me(u=Depends(current_user), conn=Depends(get_db)):
    inst = conn.execute("SELECT id,name,region,type FROM institutions WHERE id=?", (u["institution_id"],)).fetchone()
    return {"id": u["id"], "email": u["email"], "role": u["role"], "institution": dict(inst) if inst else None}


@app.get("/api/institutions")
def institutions(u=Depends(roles("station", "hospital", "admin")), conn=Depends(get_db)):
    return [dict(r) for r in conn.execute("SELECT id,type,name,region FROM institutions ORDER BY id")]




def donor_view(d, with_pii):
    out = {"id": d["id"], "blood_group": d["blood_group"], "rh": d["rh"], "last_donation_date": d["last_donation_date"],
           "lat": d["lat"], "lon": d["lon"], "notify_radius_km": d["notify_radius_km"], "consent": bool(d["consent"])}
    if with_pii:
        out["full_name"], out["phone"] = sec.decrypt(d["full_name_enc"]), sec.decrypt(d["contacts_enc"])
    return out


@app.get("/api/donors/me")
def donor_me(u=Depends(roles("donor")), conn=Depends(get_db)):
    return donor_view(conn.execute("SELECT * FROM donors WHERE user_id=?", (u["id"],)).fetchone(), True)


@app.put("/api/donors/me")
def donor_update(p: DonorUpdate, u=Depends(roles("donor")), conn=Depends(get_db)):
    for k, v in p.model_dump(exclude_none=True).items():
        conn.execute(f"UPDATE donors SET {k}=? WHERE user_id=?", (int(v) if k == "consent" else v, u["id"]))
    conn.commit()
    return donor_me(u, conn)


@app.get("/api/donors")
def donors_list(u=Depends(roles("station")), conn=Depends(get_db)):
    rows = conn.execute("SELECT * FROM donors WHERE consent=1 ORDER BY id LIMIT 300").fetchall()
    svc.audit(conn, u["id"], "view_donor_pii", f"list:{len(rows)}")
    conn.commit()
    return [donor_view(d, True) for d in rows]


@app.get("/api/donors/{donor_id}")
def donor_get(donor_id: int, u=Depends(roles("station")), conn=Depends(get_db)):
    d = conn.execute("SELECT * FROM donors WHERE id=? AND consent=1", (donor_id,)).fetchone()
    if not d:
        raise HTTPException(404, "Донор не найден или не дал согласие")
    svc.audit(conn, u["id"], "view_donor_pii", f"donor:{donor_id}")
    conn.commit()
    return donor_view(d, True)




def register_donation(conn, user, d, component, volume_ml, at):
    """Общая логика донации: проверка интервала, новая единица, события журнала, аудит."""
    shelf, interval = svc.COMPONENTS[component]
    if d["last_donation_date"] and (at.date() - date.fromisoformat(d["last_donation_date"])).days < interval:
        raise HTTPException(409, f"Не соблюдён интервал между донациями ({interval} дн.)")
    exp = (at + timedelta(days=shelf)).isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO units(component,blood_group,rh,volume_ml,collected_at,expires_at,status,institution_id,donor_id) "
        "VALUES(?,?,?,?,?,?,'testing',?,?)", (component, d["blood_group"], d["rh"], volume_ml,
                                            at.isoformat(timespec="seconds"), exp, user["institution_id"], d["id"]))
    uid = cur.lastrowid
    svc.trace_event(conn, uid, "collected", user["id"], None, user["institution_id"], f"донор #{d['id']}")
    conn.execute("UPDATE donors SET last_donation_date=? WHERE id=?", (at.date().isoformat(), d["id"]))
    svc.audit(conn, user["id"], "register_donation", f"unit:{uid};donor:{d['id']}")
    return uid, exp


@app.post("/api/donations", status_code=201)
def donation(p: DonationIn, u=Depends(roles("station")), conn=Depends(get_db)):
    d = conn.execute("SELECT * FROM donors WHERE id=? AND consent=1", (p.donor_id,)).fetchone()
    if not d:
        raise HTTPException(404, "Донор не найден или не дал согласие")
    at = p.collected_at or datetime.now(timezone.utc)
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    if at > datetime.now(timezone.utc) + timedelta(minutes=1):
        raise HTTPException(422, "Дата донации в будущем")
    uid, exp = register_donation(conn, u, d, p.component, p.volume_ml, at)
    conn.commit()
    return {"unit_id": uid, "expires_at": exp}


@app.get("/api/inventory")
def inventory(u=Depends(roles("station", "hospital", "admin")), conn=Depends(get_db)):
    return svc.inventory(conn, u)


@app.post("/api/maintenance/expire")
def expire(u=Depends(roles("station", "hospital", "admin")), conn=Depends(get_db)):
    institution_id = u["institution_id"] if u["role"] != "admin" else None
    discarded = expire_units(conn, u["id"], institution_id)
    conn.commit()
    return {"discarded": discarded}


@app.post("/api/units/{unit_id}/test")
def test_unit(unit_id: int, p: TestResult, u=Depends(roles("station")), conn=Depends(get_db)):
    unit = get_unit_for(conn, unit_id, u, strict=True)
    if unit["status"] != "testing":
        raise HTTPException(409, "Тестирование возможно только для новой единицы")
    if svc.hours_left(unit["expires_at"]) <= 0:
        raise HTTPException(409, "Срок годности истёк")
    if p.passed:
        conn.execute("UPDATE units SET status='tested' WHERE id=?", (unit_id,))
        svc.trace_event(conn, unit_id, "tested", u["id"], unit["institution_id"], unit["institution_id"], "результат: успешно")
    else:
        conn.execute("UPDATE units SET status='discarded' WHERE id=?", (unit_id,))
        svc.trace_event(conn, unit_id, "tested", u["id"], unit["institution_id"], unit["institution_id"], "результат: не пройден")
        svc.trace_event(conn, unit_id, "discarded", u["id"], unit["institution_id"], None, "не прошло тестирование")
    conn.commit()
    return {"status": "tested" if p.passed else "discarded"}


@app.post("/api/units/{unit_id}/store")
def store_unit(unit_id: int, u=Depends(roles("station")), conn=Depends(get_db)):
    unit = get_unit_for(conn, unit_id, u, strict=True)
    if unit["status"] != "tested":
        raise HTTPException(409, "На хранение можно поместить только протестированную единицу")
    if svc.hours_left(unit["expires_at"]) <= 0:
        raise HTTPException(409, "Срок годности истёк")
    conn.execute("UPDATE units SET status='stored' WHERE id=?", (unit_id,))
    svc.trace_event(conn, unit_id, "stored", u["id"], unit["institution_id"], unit["institution_id"])
    conn.commit()
    return {"status": "stored"}


@app.post("/api/units/{unit_id}/events")
def unit_event(unit_id: int, p: EventIn, u=Depends(roles("station", "hospital")), conn=Depends(get_db)):
    unit = get_unit_for(conn, unit_id, u, strict=True)
    if unit["status"] not in ("stored", "reserved"):
        raise HTTPException(409, f"Операция невозможна для статуса «{unit['status']}»")
    expired = svc.hours_left(unit["expires_at"]) <= 0
    if p.event_type != "discarded" and expired:
        raise HTTPException(409, "Срок годности истёк: единицу можно только списать")
    if p.event_type == "transferred":
        if not p.to_institution_id or not conn.execute("SELECT 1 FROM institutions WHERE id=?", (p.to_institution_id,)).fetchone():
            raise HTTPException(422, "Укажите существующее учреждение назначения")
        conn.execute("UPDATE units SET institution_id=?, status='stored' WHERE id=?", (p.to_institution_id, unit_id))
    elif p.event_type == "transfused":
        if u["role"] != "hospital":
            raise HTTPException(403, "Переливание фиксирует больница")
        conn.execute("UPDATE units SET status='transfused' WHERE id=?", (unit_id,))
    else:
        conn.execute("UPDATE units SET status='discarded' WHERE id=?", (unit_id,))
    svc.trace_event(conn, unit_id, p.event_type, u["id"], unit["institution_id"], p.to_institution_id, p.note)
    conn.commit()
    return {"ok": True}


@app.get("/api/units/{unit_id}/trace")
def unit_trace(unit_id: int, u=Depends(roles("station", "hospital", "admin")), conn=Depends(get_db)):
    unit = get_unit_for(conn, unit_id, u)
    ev = conn.execute("SELECT * FROM trace WHERE unit_id=? ORDER BY id", (unit_id,)).fetchall()
    return {"unit": {k: unit[k] for k in ("id", "component", "blood_group", "rh", "status", "expires_at")},
            "events": [dict(e) for e in ev]}


@app.post("/api/requests", status_code=201)
def create_request(p: RequestIn, u=Depends(roles("hospital")), conn=Depends(get_db)):
    cur = conn.execute("INSERT INTO requests(hospital_id,component,blood_group,rh,units_needed,urgency,created_at) "
                       "VALUES(?,?,?,?,?,?,?)", (u["institution_id"], p.component, p.blood_group, p.rh,
                                                 p.units_needed, p.urgency, now()))
    req = conn.execute("SELECT * FROM requests WHERE id=?", (cur.lastrowid,)).fetchone()
    avail = len(svc.available_units(conn, req))
    notified = svc.notify(conn, req) if avail < p.units_needed else 0
    conn.commit()
    return {"request_id": req["id"], "available_units": avail, "notified_donors": notified}


@app.get("/api/requests")
def list_requests(u=Depends(roles("hospital", "station", "admin")), conn=Depends(get_db)):
    q = ("SELECT r.*, i.name hospital FROM requests r JOIN institutions i ON i.id=r.hospital_id ")
    if u["role"] == "hospital":
        rows = conn.execute(q + "WHERE r.hospital_id=? ORDER BY r.id DESC LIMIT 100", (u["institution_id"],))
    elif u["role"] == "station":
        rows = conn.execute(q + "WHERE i.region=(SELECT region FROM institutions WHERE id=?) ORDER BY r.id DESC LIMIT 100",
                            (u["institution_id"],))
    else:
        rows = conn.execute(q + "ORDER BY r.id DESC LIMIT 100")
    return [dict(r) for r in rows]


@app.get("/api/requests/{rid}/donors")
def request_donors(rid: int, u=Depends(roles("station", "hospital")), conn=Depends(get_db)):
    req = get_request_for(conn, rid, u)
    return svc.find_donors(conn, req)


@app.post("/api/requests/{rid}/notify")
def request_notify(rid: int, u=Depends(roles("station", "hospital")), conn=Depends(get_db)):
    req = get_request_for(conn, rid, u)
    n = svc.notify(conn, req)
    conn.commit()
    return {"new_notifications": n}


@app.post("/api/requests/{rid}/reserve")
def request_reserve(rid: int, u=Depends(roles("station", "hospital")), conn=Depends(get_db)):
    req = get_request_for(conn, rid, u)
    if req["status"] in ("fulfilled", "cancelled"):
        raise HTTPException(409, "Заявка закрыта")
    n = svc.reserve(conn, req, u["id"])
    conn.commit()
    return {"reserved_now": n}


@app.post("/api/requests/{rid}/close")
def request_close(rid: int, p: CloseIn, u=Depends(roles("hospital")), conn=Depends(get_db)):
    req = get_request_for(conn, rid, u, owner_only=True)
    if req["status"] in ("fulfilled", "cancelled"):
        raise HTTPException(409, "Заявка уже закрыта")
    conn.execute("UPDATE requests SET status=?, closed_at=? WHERE id=?", (p.status, now(), rid))
    conn.commit()
    return {"ok": True}



@app.get("/api/notifications/my")
def my_notifications(u=Depends(roles("donor")), conn=Depends(get_db)):
    rows = conn.execute(
        "SELECT n.id, n.request_id, n.status, n.sent_at, r.component, r.blood_group, r.rh, r.urgency, i.name hospital "
        "FROM notifications n JOIN donors d ON d.id=n.donor_id JOIN requests r ON r.id=n.request_id "
        "JOIN institutions i ON i.id=r.hospital_id WHERE d.user_id=? ORDER BY n.id DESC", (u["id"],))
    return [dict(r) for r in rows]


@app.post("/api/notifications/{nid}/respond")
def respond(nid: int, p: RespondIn, u=Depends(roles("donor")), conn=Depends(get_db)):
    cur = conn.execute("UPDATE notifications SET status=? WHERE id=? AND donor_id=(SELECT id FROM donors WHERE user_id=?)",
                       ("accepted" if p.accept else "declined", nid, u["id"]))
    if not cur.rowcount:
        raise HTTPException(404, "Уведомление не найдено")
    conn.commit()
    return {"ok": True}


@app.get("/api/forecast/{hospital_id}")
def forecast(hospital_id: int, u=Depends(roles("hospital", "station", "admin")), conn=Depends(get_db)):
    if u["role"] == "hospital" and u["institution_id"] != hospital_id:
        raise HTTPException(403, "Чужая больница")
    return [{"component": c, "blood_group": g, "rh": r, "expected_units_7d": n}
            for (_, c, g, r), n in svc.forecast_need(conn, hospital_id).items()]


@app.get("/api/rebalance")
def rebalance(u=Depends(roles("station", "admin")), conn=Depends(get_db)):
    return svc.rebalance(conn)


@app.get("/api/reports/summary")
def report(u=Depends(roles("station", "admin")), conn=Depends(get_db)):
    st = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM units GROUP BY 1")}
    rq = {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM requests GROUP BY 1")}
    stale = conn.execute("SELECT COUNT(*) FROM units WHERE status IN ('testing','tested','stored','reserved') AND expires_at<=?",
                         (now(),)).fetchone()[0]
    durations = [max((datetime.fromisoformat(r["closed_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() / 3600, 0)
                 for r in conn.execute("SELECT created_at,closed_at FROM requests WHERE status='fulfilled' AND closed_at IS NOT NULL")]
    durations.sort()
    median = (durations[len(durations) // 2] if len(durations) % 2 else
              (durations[len(durations) // 2 - 1] + durations[len(durations) // 2]) / 2) if durations else None
    return {"units_by_status": st, "requests_by_status": rq, "expired_not_discarded": stale,
            "request_turnaround": {"completed_requests": len(durations),
                                   "average_hours": round(sum(durations) / len(durations), 1) if durations else None,
                                   "median_hours": round(median, 1) if median is not None else None}}


@app.get("/api/map")
def map_data(u=Depends(roles("station", "hospital", "admin")), conn=Depends(get_db)):
    """Координаты доноров выдаются только крупными анонимными кластерами, не персональными точками."""
    region = None
    if u["role"] in ("station", "hospital"):
        row = conn.execute("SELECT region FROM institutions WHERE id=?", (u["institution_id"],)).fetchone()
        region = row["region"] if row else None
    institutions = conn.execute(
        "SELECT id,type,name,region,lat,lon FROM institutions WHERE (? IS NULL OR region=?) ORDER BY type,id",
        (region, region)).fetchall()
    donor_rows = conn.execute(
        "SELECT d.lat,d.lon FROM donors d JOIN users u ON u.id=d.user_id "
        "WHERE d.consent=1 AND u.active=1").fetchall()
    region_centers = conn.execute("SELECT region,lat,lon FROM institutions").fetchall()
    cells = defaultdict(int)
    for donor in donor_rows:
        if region and region_centers:
            closest = min(region_centers, key=lambda place: svc.haversine(
                donor["lat"], donor["lon"], place["lat"], place["lon"]))
            if closest["region"] != region:
                continue
        cells[(round(donor["lat"], 1), round(donor["lon"], 1))] += 1
    donor_clusters = [{"lat": lat, "lon": lon, "count": count} for (lat, lon), count in cells.items() if count >= 3]
    open_requests = conn.execute(
        "SELECT r.id,r.component,r.blood_group,r.rh,r.units_needed,r.reserved_units,r.urgency,r.status,"
        "i.name hospital,i.lat,i.lon FROM requests r JOIN institutions i ON i.id=r.hospital_id "
        "WHERE r.status NOT IN ('fulfilled','cancelled') AND (? IS NULL OR i.region=?) ORDER BY r.id DESC",
        (region, region)).fetchall()
    return {"institutions": [dict(row) for row in institutions], "donor_clusters": donor_clusters,
            "requests": [dict(row) for row in open_requests]}



@app.get("/api/public/stats")
def public_stats(conn=Depends(get_db)):
    """Обезличенные агрегаты для главной страницы (без входа). Персональных данных здесь нет."""
    one = lambda q, *a: conn.execute(q, a).fetchone()[0]
    stock = conn.execute("SELECT blood_group, rh, COUNT(*) c FROM units WHERE status='stored' AND expires_at>? "
                         "GROUP BY 1,2", (now(),)).fetchall()
    by = {(r["blood_group"], r["rh"]): r["c"] for r in stock}
    return {"stations": one("SELECT COUNT(*) FROM institutions WHERE type='station'"),
            "hospitals": one("SELECT COUNT(*) FROM institutions WHERE type='hospital'"),
            "donors": one("SELECT COUNT(*) FROM donors d JOIN users u ON u.id=d.user_id WHERE d.consent=1 AND u.active=1"),
            "units_in_stock": sum(by.values()),
            "requests_fulfilled": one("SELECT COUNT(*) FROM requests WHERE status='fulfilled'"),
            "stock_by_group": [{"blood_group": g, "rh": r, "count": by.get((g, r), 0)}
                               for g in ("O", "A", "B", "AB") for r in ("+", "-")]}


@app.get("/api/stations")
def stations(u=Depends(current_user), conn=Depends(get_db)):
    return [dict(r) for r in conn.execute("SELECT id,name,region,lat,lon FROM institutions WHERE type='station' ORDER BY id")]


def station_or_404(conn, sid):
    st = conn.execute("SELECT * FROM institutions WHERE id=? AND type='station'", (sid,)).fetchone()
    if not st:
        raise HTTPException(404, "Станция не найдена")
    return st


@app.get("/api/stations/{sid}/slots")
def station_slots(sid: int, day: date, u=Depends(roles("donor")), conn=Depends(get_db)):
    station_or_404(conn, sid)
    if day < svc.local_today() or day > svc.local_today() + timedelta(days=svc.BOOKING_DAYS):
        raise HTTPException(422, f"Запись доступна на {svc.BOOKING_DAYS} дней вперёд")
    out = []
    for dt in svc.day_slots(day):
        if not svc.valid_slot(dt):
            continue
        iso = dt.isoformat(timespec="seconds")
        taken = conn.execute("SELECT COUNT(*) FROM appointments WHERE station_id=? AND slot_at=? AND status='booked'",
                             (sid, iso)).fetchone()[0]
        out.append({"slot_at": iso, "time": dt.astimezone(svc.LOCAL_TZ).strftime("%H:%M"),
                    "free": max(svc.SLOT_CAPACITY - taken, 0)})
    return out


def my_donor(conn, u):
    return conn.execute("SELECT * FROM donors WHERE user_id=?", (u["id"],)).fetchone()


def appt_row(r):
    return {"id": r["id"], "station_id": r["station_id"], "station": r["station"], "slot_at": r["slot_at"],
            "component": r["component"], "status": r["status"], "request_id": r["request_id"], "unit_id": r["unit_id"]}


APPT_SQL = ("SELECT a.*, i.name station FROM appointments a JOIN institutions i ON i.id=a.station_id ")


@app.post("/api/appointments", status_code=201)
def book(p: AppointmentIn, u=Depends(roles("donor")), conn=Depends(get_db)):
    d = my_donor(conn, u)
    if not d["consent"]:
        raise HTTPException(409, "Включите участие в подборе в профиле, чтобы записаться")
    station_or_404(conn, p.station_id)
    slot = p.slot_at if p.slot_at.tzinfo else p.slot_at.replace(tzinfo=timezone.utc)
    slot = slot.astimezone(timezone.utc).replace(microsecond=0)
    if not svc.valid_slot(slot):
        raise HTTPException(422, "Это время недоступно для записи")
    if svc.next_eligible(d["last_donation_date"], p.component) > slot.astimezone(svc.LOCAL_TZ).date():
        nxt = svc.next_eligible(d["last_donation_date"], p.component).isoformat()
        raise HTTPException(409, f"Сдавать этот компонент можно с {nxt}")
    if p.request_id and not conn.execute("SELECT 1 FROM notifications WHERE request_id=? AND donor_id=?",
                                         (p.request_id, d["id"])).fetchone():
        raise HTTPException(404, "Запрос не найден среди ваших уведомлений")
    conn.execute("BEGIN IMMEDIATE")  # слот проверяется и занимается без гонки между запросами
    if conn.execute("SELECT 1 FROM appointments WHERE donor_id=? AND status='booked' AND slot_at>?",
                    (d["id"], now())).fetchone():
        raise HTTPException(409, "У вас уже есть активная запись. Отмените её, чтобы выбрать другое время")
    iso = slot.isoformat(timespec="seconds")
    taken = conn.execute("SELECT COUNT(*) FROM appointments WHERE station_id=? AND slot_at=? AND status='booked'",
                         (p.station_id, iso)).fetchone()[0]
    if taken >= svc.SLOT_CAPACITY:
        raise HTTPException(409, "Это время уже занято, выберите другое")
    cur = conn.execute("INSERT INTO appointments(donor_id,station_id,slot_at,component,request_id,created_at) "
                       "VALUES(?,?,?,?,?,?)", (d["id"], p.station_id, iso, p.component, p.request_id, now()))
    if p.request_id:
        conn.execute("UPDATE notifications SET status='accepted' WHERE request_id=? AND donor_id=? AND status='sent'",
                     (p.request_id, d["id"]))
    conn.commit()
    return {"id": cur.lastrowid, "slot_at": iso}


@app.get("/api/appointments/my")
def my_appointments(u=Depends(roles("donor")), conn=Depends(get_db)):
    d = my_donor(conn, u)
    rows = conn.execute(APPT_SQL + "WHERE a.donor_id=? ORDER BY a.slot_at DESC LIMIT 50", (d["id"],))
    return [appt_row(r) for r in rows]


@app.post("/api/appointments/{aid}/cancel")
def cancel_appointment(aid: int, u=Depends(roles("donor")), conn=Depends(get_db)):
    d = my_donor(conn, u)
    a = conn.execute("SELECT * FROM appointments WHERE id=? AND donor_id=?", (aid, d["id"])).fetchone()
    if not a:
        raise HTTPException(404, "Запись не найдена")
    if a["status"] != "booked" or a["slot_at"] <= now():
        raise HTTPException(409, "Эту запись уже нельзя отменить")
    conn.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (aid,))
    conn.commit()
    return {"ok": True}


@app.get("/api/donors/me/overview")
def donor_overview(u=Depends(roles("donor")), conn=Depends(get_db)):
    d = my_donor(conn, u)
    today = svc.local_today()
    elig = []
    for c, (_, interval) in svc.COMPONENTS.items():
        nxt = svc.next_eligible(d["last_donation_date"], c)
        elig.append({"component": c, "interval_days": interval, "next_date": nxt.isoformat(),
                     "eligible_now": nxt <= today, "days_left": (nxt - today).days})
    units = conn.execute("SELECT u.id, u.component, u.volume_ml, u.collected_at, u.status, i.name station "
                         "FROM units u JOIN institutions i ON i.id=u.institution_id WHERE u.donor_id=? "
                         "ORDER BY u.collected_at DESC LIMIT 100", (d["id"],)).fetchall()
    nxt_appt = conn.execute(APPT_SQL + "WHERE a.donor_id=? AND a.status='booked' AND a.slot_at>? ORDER BY a.slot_at LIMIT 1",
                            (d["id"], now())).fetchone()
    return {"eligibility": elig, "history": [dict(r) for r in units],
            "stats": {"donations": len(units), "volume_ml": sum(r["volume_ml"] for r in units),
                      "transfused": sum(1 for r in units if r["status"] == "transfused")},
            "next_appointment": appt_row(nxt_appt) if nxt_appt else None}


def visit_for_station(conn, aid, u):
    a = conn.execute("SELECT * FROM appointments WHERE id=?", (aid,)).fetchone()
    if not a or a["station_id"] != u["institution_id"]:
        raise HTTPException(404, "Запись не найдена")  # ABAC: чужие записи станция не видит
    if a["status"] != "booked":
        raise HTTPException(409, "Запись уже обработана")
    if datetime.fromisoformat(a["slot_at"]).astimezone(svc.LOCAL_TZ).date() > svc.local_today():
        raise HTTPException(409, "Визит ещё не наступил")
    return a


@app.get("/api/appointments")
def station_appointments(u=Depends(roles("station")), conn=Depends(get_db)):
    start = svc.slot_utc(svc.local_today(), 0).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT a.*, d.full_name_enc, d.blood_group, d.rh, d.last_donation_date FROM appointments a "
        "JOIN donors d ON d.id=a.donor_id WHERE a.station_id=? AND a.slot_at>=? ORDER BY a.slot_at LIMIT 200",
        (u["institution_id"], start)).fetchall()
    svc.audit(conn, u["id"], "view_donor_pii", f"appointments:{len(rows)}")
    conn.commit()
    return [{"id": r["id"], "slot_at": r["slot_at"], "component": r["component"], "status": r["status"],
             "donor_id": r["donor_id"], "full_name": sec.decrypt(r["full_name_enc"]),
             "blood_group": r["blood_group"], "rh": r["rh"], "request_id": r["request_id"],
             "last_donation_date": r["last_donation_date"]} for r in rows]


@app.post("/api/appointments/{aid}/complete")
def complete_visit(aid: int, p: VisitDone = VisitDone(), u=Depends(roles("station")), conn=Depends(get_db)):
    a = visit_for_station(conn, aid, u)
    d = conn.execute("SELECT * FROM donors WHERE id=? AND consent=1", (a["donor_id"],)).fetchone()
    if not d:
        raise HTTPException(409, "Донор отозвал согласие")
    uid, exp = register_donation(conn, u, d, a["component"], p.volume_ml, datetime.now(timezone.utc))
    conn.execute("UPDATE appointments SET status='completed', unit_id=? WHERE id=?", (uid, aid))
    conn.commit()
    return {"unit_id": uid, "expires_at": exp}


@app.post("/api/appointments/{aid}/no-show")
def no_show(aid: int, u=Depends(roles("station")), conn=Depends(get_db)):
    visit_for_station(conn, aid, u)
    conn.execute("UPDATE appointments SET status='no_show' WHERE id=?", (aid,))
    conn.commit()
    return {"ok": True}


@app.get("/api/admin/users")
def admin_users(u=Depends(roles("admin")), conn=Depends(get_db)):
    return [dict(r) for r in conn.execute(
        "SELECT id,email,role,institution_id,active,failed_attempts FROM users ORDER BY id LIMIT 300")]


@app.post("/api/admin/users", status_code=201)
def admin_create(p: StaffIn, u=Depends(roles("admin")), conn=Depends(get_db)):
    if p.role != "admin" and not p.institution_id:
        raise HTTPException(422, "Для сотрудника укажите учреждение")
    if len(p.password) < 8:
        raise HTTPException(422, "Пароль: минимум 8 символов")
    if conn.execute("SELECT 1 FROM users WHERE email=?", (p.email,)).fetchone():
        raise HTTPException(409, "Email уже зарегистрирован")
    cur = conn.execute("INSERT INTO users(email,password_hash,role,institution_id) VALUES(?,?,?,?)",
                       (p.email, sec.hash_password(p.password), p.role, p.institution_id))
    svc.audit(conn, u["id"], "create_user", f"user:{cur.lastrowid}")
    conn.commit()
    return {"id": cur.lastrowid}


@app.patch("/api/admin/users/{uid}")
def admin_patch(uid: int, p: UserPatch, u=Depends(roles("admin")), conn=Depends(get_db)):
    conn.execute("UPDATE users SET active=?, failed_attempts=0 WHERE id=?", (int(p.active), uid))
    svc.audit(conn, u["id"], "set_active", f"user:{uid}={p.active}")
    conn.commit()
    return {"ok": True}


@app.get("/api/audit")
def audit_log(u=Depends(roles("admin")), conn=Depends(get_db)):
    return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200")]


if (STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
