import time
from datetime import datetime, timedelta, timezone

import pytest

from app import services as svc
from tests.conftest import auth

DONOR = {"email": "new.donor@example.kz", "password": "Strong123", "full_name": "Айдар Тестов", "phone": "+77001112233",
         "blood_group": "A", "rh": "+", "lat": 51.14, "lon": 71.44, "notify_radius_km": 20}


def fresh_donor_id(client, station, used=set()):
    """Донор без донаций (для сценариев, где важна дата)."""
    for d in client.get("/api/donors", headers=station).json():
        if d["last_donation_date"] is None and d["id"] not in used:
            used.add(d["id"])
            return d["id"]
    raise AssertionError("нет подходящего донора")


def test_t01_register_donor_hashes_password(client, db):
    r = client.post("/api/auth/register", json=DONOR)
    assert r.status_code == 201
    h = db.execute("SELECT password_hash FROM users WHERE email=?", (DONOR["email"],)).fetchone()[0]
    assert h.startswith("$2") and "Strong123" not in h
    enc = db.execute("SELECT full_name_enc FROM donors WHERE id=?", (r.json()["donor_id"],)).fetchone()[0]
    assert "Айдар" not in enc


@pytest.mark.parametrize("patch", [{"email": ""}, {"email": "no-at-sign"}, {"password": "short1"},
                                   {"password": "onlyletters"}, {"blood_group": "X"}, {"lat": 200}])
def test_t02_invalid_registration(client, patch):
    r = client.post("/api/auth/register", json={**DONOR, "email": "x@example.kz", **patch})
    assert r.status_code == 422


def test_t03_t04_donation_creates_unit_trace_and_expiring_flag(client, station):
    donor = fresh_donor_id(client, station)
    collected = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    r = client.post("/api/donations", headers=station, json={"donor_id": donor, "component": "platelets",
                                                              "collected_at": collected})
    assert r.status_code == 201
    uid = r.json()["unit_id"]
    inv = client.get("/api/inventory", headers=station).json()
    unit = next(u for u in inv["units"] if u["id"] == uid)
    assert unit["expiring"] and not unit["expired"]  # T-04: осталось ≤ 72 ч
    assert unit["status"] == "testing"
    events = client.get(f"/api/units/{uid}/trace", headers=station).json()["events"]
    assert [e["event_type"] for e in events] == ["collected"]
    assert client.post(f"/api/units/{uid}/test", headers=station, json={"passed": True}).json()["status"] == "tested"
    assert client.post(f"/api/units/{uid}/store", headers=station).json()["status"] == "stored"
    events = client.get(f"/api/units/{uid}/trace", headers=station).json()["events"]
    assert [e["event_type"] for e in events] == ["collected", "tested", "stored"]


def test_failed_testing_discards_unit(client, station):
    donor = fresh_donor_id(client, station)
    donation = client.post("/api/donations", headers=station, json={"donor_id": donor, "component": "plasma"}).json()
    uid = donation["unit_id"]
    result = client.post(f"/api/units/{uid}/test", headers=station, json={"passed": False})
    assert result.status_code == 200 and result.json()["status"] == "discarded"
    assert client.post(f"/api/units/{uid}/store", headers=station).status_code == 409
    assert [e["event_type"] for e in client.get(f"/api/units/{uid}/trace", headers=station).json()["events"]] == [
        "collected", "tested", "discarded"]


def test_donation_interval_enforced(client, station):
    donor = fresh_donor_id(client, station)
    assert client.post("/api/donations", headers=station, json={"donor_id": donor, "component": "red_cells"}).status_code == 201
    assert client.post("/api/donations", headers=station, json={"donor_id": donor, "component": "red_cells"}).status_code == 409


def make_request(client, hospital, **kw):
    body = {"component": "red_cells", "blood_group": "A", "rh": "+", "units_needed": 40, "urgency": "critical", **kw}
    r = client.post("/api/requests", headers=hospital, json=body)
    assert r.status_code == 201
    return r.json()


def test_t05_matching_rules(client, hospital):
    rid = make_request(client, hospital)["request_id"]
    donors = client.get(f"/api/requests/{rid}/donors", headers=hospital).json()
    assert donors
    for d in donors:
        assert d["blood_group"] in ("O", "A")
        assert d["days_since_last_donation"] is None or d["days_since_last_donation"] >= 56


def test_t06_t07_recent_donor_excluded_and_notifications_targeted(client, hospital):
    recent = (datetime.now(timezone.utc) - timedelta(days=10)).date().isoformat()
    ok = client.post("/api/auth/register", json={**DONOR, "email": "ok@example.kz", "last_donation_date": "2024-01-01"}).json()
    bad = client.post("/api/auth/register", json={**DONOR, "email": "bad@example.kz", "last_donation_date": recent}).json()
    far = client.post("/api/auth/register", json={**DONOR, "email": "far@example.kz", "lat": 52.5, "lon": 73.0}).json()
    made = make_request(client, hospital, component="platelets", units_needed=50)  # дефицит → авто-оповещение
    ids = {d["donor_id"] for d in client.get(f"/api/requests/{made['request_id']}/donors", headers=hospital).json()}
    assert ok["donor_id"] in ids and bad["donor_id"] not in ids and far["donor_id"] not in ids
    assert made["notified_donors"] == len(ids)
    again = client.post(f"/api/requests/{made['request_id']}/notify", headers=hospital).json()
    assert again["new_notifications"] == 0
    ok_h = auth(client, "ok@example.kz", "Strong123")
    bad_h = auth(client, "bad@example.kz", "Strong123")
    got = client.get("/api/notifications/my", headers=ok_h).json()
    assert got and client.get("/api/notifications/my", headers=bad_h).json() == []
    assert client.post(f"/api/notifications/{got[0]['id']}/respond", headers=ok_h, json={"accept": True}).status_code == 200


def test_t08_donor_cannot_read_other_donors_and_access_is_audited(client, station, admin):
    donor_h = auth(client, "donor1@example.kz", "Donor12345")
    assert client.get("/api/donors", headers=donor_h).status_code == 403
    assert client.get("/api/donors/2", headers=donor_h).status_code == 403
    assert client.get("/api/donors/2", headers=station).status_code in (200, 404)
    log = client.get("/api/audit", headers=admin).json()
    assert any(a["action"] == "view_donor_pii" for a in log)
    assert client.get("/api/audit", headers=station).status_code == 403


def test_t09_hospital_sees_only_anonymous_donors(client, hospital):
    rid = make_request(client, hospital)["request_id"]
    for d in client.get(f"/api/requests/{rid}/donors", headers=hospital).json():
        assert set(d) == {"donor_id", "blood_group", "rh", "distance_km", "days_since_last_donation"}
    assert client.get("/api/donors", headers=hospital).status_code == 403


def test_t10_trace_is_append_only(client, station, db):
    import sqlite3
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("UPDATE trace SET note='x' WHERE id=1")
    with pytest.raises(sqlite3.DatabaseError):
        db.execute("DELETE FROM trace WHERE id=1")
    assert client.delete("/api/units/1/trace", headers=station).status_code == 405


def test_t11_injection_attempts(client, db):
    assert client.get("/api/units/1' OR '1'='1/trace").status_code in (401, 404, 422)
    r = client.post("/api/auth/login", json={"email": "a@b.kz", "password": "' OR '1'='1"})
    assert r.status_code == 401
    r = client.post("/api/auth/register", json={**DONOR, "email": "x'; DROP TABLE users;--@a.kz"})
    assert r.status_code == 422
    assert db.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0


def test_t12_matching_under_3_seconds(client, hospital, db):
    assert db.execute("SELECT COUNT(*) FROM donors").fetchone()[0] >= 500
    rid = make_request(client, hospital, blood_group="O", rh="-", component="whole_blood")["request_id"]
    t = time.perf_counter()
    assert client.get(f"/api/requests/{rid}/donors", headers=hospital).status_code == 200
    assert time.perf_counter() - t < 3


def test_t13_rebalance_recommends_surplus_to_deficit(client, station, db):
    hosp = db.execute("SELECT id FROM institutions WHERE type='hospital' ORDER BY id LIMIT 1").fetchone()[0]
    st = db.execute("SELECT id FROM institutions WHERE type='station' ORDER BY id LIMIT 1").fetchone()[0]
    ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    db.execute("INSERT INTO requests(hospital_id,component,blood_group,rh,units_needed,urgency,status,created_at) "
               "VALUES(?,?,?,?,?,?,?,?)", (hosp, "plasma", "AB", "-", 8, "urgent", "fulfilled", ts))
    exp = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds")
    for _ in range(3):
        db.execute("INSERT INTO units(component,blood_group,rh,volume_ml,collected_at,expires_at,status,institution_id) "
                   "VALUES('plasma','AB','-',250,?,?,'stored',?)", (ts, exp, st))
    db.commit()
    recs = client.get("/api/rebalance", headers=station).json()
    assert any(r["to_institution_id"] == hosp and r["component"] == "plasma" and r["blood_group"] == "AB"
               and r["rh"] == "-" and r["units"] >= 1 for r in recs)


def test_reserve_transfer_transfuse_flow_and_rbac(client, station, hospital, db):
    
    st = db.execute("SELECT id FROM institutions WHERE type='station' ORDER BY id LIMIT 1").fetchone()[0]
    exp = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(timespec="seconds")
    db.execute("INSERT INTO units(component,blood_group,rh,volume_ml,collected_at,expires_at,status,institution_id)"
               " VALUES('red_cells','O','-',450,?,?,'stored',?)", (exp, exp, st))
    db.commit()
    rid = make_request(client, hospital, blood_group="O", rh="-", units_needed=1)["request_id"]
    assert client.post(f"/api/requests/{rid}/reserve", headers=hospital).status_code == 200
    uid, st = db.execute("SELECT id, institution_id FROM units WHERE request_id=?", (rid,)).fetchone()
    station = auth(client, f"station{st}@bpsc.kz", "Staff12345")  # станция, где лежит зарезервированная единица
    hosp = client.get("/api/me", headers=hospital).json()["institution"]["id"]
    assert client.post(f"/api/units/{uid}/events", headers=hospital,
                       json={"event_type": "transfused"}).status_code == 403  # ещё не у больницы
    assert client.post(f"/api/units/{uid}/events", headers=station,
                       json={"event_type": "transferred", "to_institution_id": hosp}).status_code == 200
    assert client.post(f"/api/units/{uid}/events", headers=hospital, json={"event_type": "transfused"}).status_code == 200
    kinds = [e["event_type"] for e in client.get(f"/api/units/{uid}/trace", headers=hospital).json()["events"]]
    assert kinds[-3:] == ["reserved", "transferred", "transfused"]
    assert client.post("/api/donations", headers=hospital, json={"donor_id": 1, "component": "plasma"}).status_code == 403


def test_expired_units_are_discarded_with_trace(client, station, db):
    st = db.execute("SELECT id FROM institutions WHERE type='station' ORDER BY id LIMIT 1").fetchone()[0]
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    uid = db.execute("INSERT INTO units(component,blood_group,rh,volume_ml,collected_at,expires_at,status,institution_id)"
                     " VALUES('platelets','B','+',250,?,?,'testing',?)", (past, past, st)).lastrowid
    db.commit()
    assert client.post(f"/api/units/{uid}/events", headers=station, json={"event_type": "transferred", "to_institution_id": 2}).status_code == 409
    assert client.post("/api/maintenance/expire", headers=station).json()["discarded"] >= 1
    assert client.get(f"/api/units/{uid}/trace", headers=station).json()["events"][-1]["event_type"] == "discarded"


def test_login_lockout_and_admin_unlock(client, admin):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "donor7@example.kz", "password": "wrong-pass1"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "donor7@example.kz", "password": "Donor12345"}).status_code == 423
    uid = next(u["id"] for u in client.get("/api/admin/users", headers=admin).json() if u["email"] == "donor7@example.kz")
    client.patch(f"/api/admin/users/{uid}", headers=admin, json={"active": True})
    assert client.post("/api/auth/login", json={"email": "donor7@example.kz", "password": "Donor12345"}).status_code == 200


def test_unauthenticated_and_foreign_access(client, hospital):
    assert client.get("/api/inventory").status_code == 401
    h2 = auth(client, "hospital2@bpsc.kz", "Staff12345")
    rid = make_request(client, hospital)["request_id"]
    assert client.get(f"/api/requests/{rid}/donors", headers=h2).status_code == 403


def test_compatibility_table():
    assert svc.compatible("red_cells", "O", "-", "AB", "+")
    assert not svc.compatible("red_cells", "A", "+", "O", "+")
    assert not svc.compatible("red_cells", "O", "+", "O", "-")
    assert svc.compatible("plasma", "AB", "+", "O", "-")
    assert not svc.compatible("plasma", "O", "+", "A", "+")
    assert svc.compatible("platelets", "B", "+", "B", "-") and not svc.compatible("platelets", "A", "+", "B", "+")


def test_map_exposes_facilities_and_anonymous_donor_clusters(client, hospital):
    request_id = make_request(client, hospital, units_needed=50)["request_id"]
    data = client.get("/api/map", headers=hospital)
    assert data.status_code == 200
    result = data.json()
    assert any(x["type"] == "station" for x in result["institutions"])
    assert any(x["type"] == "hospital" for x in result["institutions"])
    assert any(x["id"] == request_id for x in result["requests"])
    assert result["donor_clusters"] and all(x["count"] >= 3 for x in result["donor_clusters"])
    assert all(set(x) == {"lat", "lon", "count"} for x in result["donor_clusters"])
    assert client.get("/api/map").status_code == 401


def test_report_measures_fulfilled_request_turnaround(client, hospital, station, db):
    request_id = make_request(client, hospital, units_needed=1)["request_id"]
    created = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(timespec="seconds")
    db.execute("UPDATE requests SET created_at=? WHERE id=?", (created, request_id))
    db.commit()
    assert client.post(f"/api/requests/{request_id}/close", headers=hospital, json={"status": "fulfilled"}).status_code == 200
    result = client.get("/api/reports/summary", headers=station).json()["request_turnaround"]
    assert result["completed_requests"] >= 1
    assert result["average_hours"] is not None and result["average_hours"] >= 4.9
    assert result["median_hours"] is not None
    assert client.post(f"/api/requests/{request_id}/close", headers=hospital, json={"status": "fulfilled"}).status_code == 409
