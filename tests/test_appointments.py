"""Запись донора на визит, кабинет донора, публичная статистика."""
import itertools
from datetime import timedelta

from app import services as svc

_n = itertools.count(1)
STATION_ID = 1  # station1@bpsc.kz работает на станции №1


def new_donor(client, **kw):
    body = {"email": f"visit{next(_n)}@example.kz", "password": "Strong123", "full_name": "Тест Донор",
            "phone": "+77005550000", "blood_group": "O", "rh": "+", "lat": 51.13, "lon": 71.43, **kw}
    r = client.post("/api/auth/register", json=body)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()["donor_id"]


def workday(offset=1):
    d = svc.local_today() + timedelta(days=offset)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


def slots(client, h, d, sid=STATION_ID):
    r = client.get(f"/api/stations/{sid}/slots", params={"day": d.isoformat()}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def book(client, h, slot_at, **kw):
    return client.post("/api/appointments", headers=h,
                       json={"station_id": STATION_ID, "slot_at": slot_at, "component": "plasma", **kw})


def test_public_stats_has_no_personal_data(client):
    r = client.get("/api/public/stats")  # без входа
    assert r.status_code == 200
    d = r.json()
    assert d["stations"] == 3 and d["hospitals"] == 5 and len(d["stock_by_group"]) == 8
    assert set(d) == {"stations", "hospitals", "donors", "units_in_stock", "requests_fulfilled", "stock_by_group"}


def test_slots_require_donor_and_future_dates(client, station):
    h, _ = new_donor(client)
    assert len(slots(client, h, workday())) == 8
    yesterday = svc.local_today() - timedelta(days=1)
    assert client.get(f"/api/stations/{STATION_ID}/slots", params={"day": yesterday.isoformat()}, headers=h).status_code == 422
    assert client.get(f"/api/stations/{STATION_ID}/slots", params={"day": workday().isoformat()}, headers=station).status_code == 403


def test_sunday_has_no_slots(client):
    h, _ = new_donor(client)
    d = svc.local_today() + timedelta(days=1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    assert slots(client, h, d) == []


def test_book_cancel_and_single_active_visit(client):
    h, _ = new_donor(client)
    s = slots(client, h, workday())[0]["slot_at"]
    r = book(client, h, s)
    assert r.status_code == 201
    assert book(client, h, slots(client, h, workday())[1]["slot_at"]).status_code == 409  # вторая активная запись
    mine = client.get("/api/appointments/my", headers=h).json()
    assert mine[0]["status"] == "booked" and mine[0]["station_id"] == STATION_ID
    assert client.post(f"/api/appointments/{r.json()['id']}/cancel", headers=h).status_code == 200
    assert client.post(f"/api/appointments/{r.json()['id']}/cancel", headers=h).status_code == 409
    assert book(client, h, s).status_code == 201  # после отмены можно записаться снова


def test_slot_capacity(client):
    d = workday(3)
    s = slots(client, new_donor(client)[0], d)[2]["slot_at"]
    for _ in range(svc.SLOT_CAPACITY):
        assert book(client, new_donor(client)[0], s).status_code == 201
    h = new_donor(client)[0]
    assert book(client, h, s).status_code == 409
    free = {x["slot_at"]: x["free"] for x in slots(client, h, d)}
    assert free[s] == 0


def test_invalid_slots_rejected(client):
    h, _ = new_donor(client)
    s = slots(client, h, workday())[0]["slot_at"]
    assert book(client, h, s.replace(":00:00", ":30:00")).status_code == 422  # не по сетке слотов
    assert book(client, h, "2020-01-01T05:00:00+00:00").status_code == 422  # прошлое
    assert client.post("/api/appointments", headers=h, json={"station_id": 999, "slot_at": s, "component": "plasma"}).status_code == 404


def test_interval_blocks_booking(client, db):
    h, did = new_donor(client)
    recent = (svc.local_today() - timedelta(days=10)).isoformat()
    db.execute("UPDATE donors SET last_donation_date=? WHERE id=?", (recent, did))
    db.commit()
    s = slots(client, h, workday())[0]["slot_at"]
    r = client.post("/api/appointments", headers=h, json={"station_id": STATION_ID, "slot_at": s, "component": "red_cells"})
    assert r.status_code == 409 and "можно с" in r.json()["detail"]
    ov = client.get("/api/donors/me/overview", headers=h).json()
    rc = next(e for e in ov["eligibility"] if e["component"] == "red_cells")
    assert not rc["eligible_now"] and rc["days_left"] == 46


def test_foreign_request_cannot_be_linked(client):
    h, _ = new_donor(client)
    s = slots(client, h, workday())[0]["slot_at"]
    assert book(client, h, s, request_id=1).status_code == 404


def test_station_visit_flow_and_abac(client, db, station):
    h, did = new_donor(client)
    r = book(client, h, slots(client, h, workday(2))[0]["slot_at"])
    aid = r.json()["id"]
    lst = client.get("/api/appointments", headers=station).json()
    assert any(a["id"] == aid and a["full_name"] == "Тест Донор" for a in lst)
    # donor и больница не видят список записей станции
    assert client.get("/api/appointments", headers=h).status_code == 403
    # визит ещё не наступил
    assert client.post(f"/api/appointments/{aid}/complete", headers=station).status_code == 409
    # чужая станция не может обработать запись
    other = client.post("/api/auth/login", json={"email": "station2@bpsc.kz", "password": "Staff12345"}).json()["token"]
    assert client.post(f"/api/appointments/{aid}/complete", headers={"Authorization": f"Bearer {other}"}).status_code == 404
    # переносим слот на сегодняшнее утро и фиксируем донацию
    db.execute("UPDATE appointments SET slot_at=? WHERE id=?", (svc.slot_utc(svc.local_today(), 9).isoformat(timespec="seconds"), aid))
    db.commit()
    done = client.post(f"/api/appointments/{aid}/complete", headers=station, json={"volume_ml": 400})
    assert done.status_code == 200
    uid = done.json()["unit_id"]
    assert client.post(f"/api/appointments/{aid}/complete", headers=station).status_code == 409  # повторно нельзя
    ov = client.get("/api/donors/me/overview", headers=h).json()
    assert ov["stats"]["donations"] == 1 and ov["stats"]["volume_ml"] == 400 and ov["history"][0]["id"] == uid
    plasma = next(e for e in ov["eligibility"] if e["component"] == "plasma")
    assert plasma["days_left"] == 14
    assert ov["history"][0]["status"] == "testing"
    events = client.get(f"/api/units/{uid}/trace", headers=station).json()["events"]
    assert [e["event_type"] for e in events] == ["collected"]
    assert client.post(f"/api/units/{uid}/test", headers=station, json={"passed": True}).json()["status"] == "tested"
    assert client.post(f"/api/units/{uid}/store", headers=station).json()["status"] == "stored"
    assert [e["event_type"] for e in client.get(f"/api/units/{uid}/trace", headers=station).json()["events"]] == [
        "collected", "tested", "stored"]


def test_no_show(client, db, station):
    h, _ = new_donor(client)
    aid = book(client, h, slots(client, h, workday(2))[1]["slot_at"]).json()["id"]
    db.execute("UPDATE appointments SET slot_at=? WHERE id=?", (svc.slot_utc(svc.local_today(), 10).isoformat(timespec="seconds"), aid))
    db.commit()
    assert client.post(f"/api/appointments/{aid}/no-show", headers=station).status_code == 200
    assert client.get("/api/appointments/my", headers=h).json()[0]["status"] == "no_show"


def test_booking_via_notification_marks_it_accepted(client, hospital, db):
    h, did = new_donor(client, blood_group="AB", rh="+")
    req = client.post("/api/requests", headers=hospital, json={"component": "plasma", "blood_group": "A", "rh": "+",
                                                                 "units_needed": 50, "urgency": "critical"}).json()["request_id"]
    note = [n for n in client.get("/api/notifications/my", headers=h).json() if n["request_id"] == req]
    assert note and note[0]["status"] == "sent"
    s = slots(client, h, workday())[0]["slot_at"]
    assert book(client, h, s, request_id=req).status_code == 201
    note = [n for n in client.get("/api/notifications/my", headers=h).json() if n["request_id"] == req]
    assert note[0]["status"] == "accepted"
