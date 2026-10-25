"""Синтетические данные для демонстрации: 3 станции, 5 больниц, N доноров, запасы и история заявок."""
import random
from datetime import datetime, timedelta, timezone

from . import security as sec
from .db import connect, init_db, now
from .services import COMPONENTS, trace_event

STATIONS = [("Республиканский центр крови", 51.128, 71.430), ("Городская станция №2", 51.170, 71.470),
            ("Станция переливания, левый берег", 51.100, 71.400)]
HOSPITALS = [("Городская больница №1", 51.140, 71.440), ("Областная больница", 51.160, 71.410),
             ("Детская больница", 51.120, 71.480), ("Больница скорой помощи", 51.150, 71.460),
             ("Кардиоцентр", 51.110, 71.420)]


def seed(conn, n_donors: int = 500) -> None:
    rnd = random.Random(42)
    admin_h, staff_h, donor_h = (sec.hash_password(p) for p in ("Admin12345", "Staff12345", "Donor12345"))
    ids = {"station": [], "hospital": []}
    for kind, items in (("station", STATIONS), ("hospital", HOSPITALS)):
        for name, lat, lon in items:
            ids[kind].append(conn.execute("INSERT INTO institutions(type,name,region,lat,lon) VALUES(?,?,?,?,?)",
                                          (kind, name, "Астана", lat, lon)).lastrowid)
    conn.execute("INSERT INTO users(email,password_hash,role) VALUES('admin@bpsc.kz',?,'admin')", (admin_h,))
    for kind in ids:
        for i, inst in enumerate(ids[kind], 1):
            conn.execute("INSERT INTO users(email,password_hash,role,institution_id) VALUES(?,?,?,?)",
                         (f"{kind}{i}@bpsc.kz", staff_h, kind, inst))
    today = datetime.now(timezone.utc).date()
    donor_ids = []
    for i in range(1, n_donors + 1):
        uid = conn.execute("INSERT INTO users(email,password_hash,role) VALUES(?,?,'donor')",
                           (f"donor{i}@example.kz", donor_h)).lastrowid
        g = rnd.choices(["O", "A", "B", "AB"], [45, 35, 15, 5])[0]
        last = None if rnd.random() < 0.3 else (today - timedelta(days=rnd.randint(1, 200))).isoformat()
        donor_ids.append(conn.execute(
            "INSERT INTO donors(user_id,full_name_enc,contacts_enc,blood_group,rh,last_donation_date,lat,lon,"
            "notify_radius_km,consent) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (uid, sec.encrypt(f"Донор {i}"), sec.encrypt(f"+7700{i:07d}"), g, rnd.choices("+-", [85, 15])[0], last,
             51.13 + rnd.uniform(-0.12, 0.12), 71.43 + rnd.uniform(-0.15, 0.15), rnd.choice([5, 10, 15, 30]),
             int(rnd.random() < 0.95))).lastrowid)
    t0 = datetime.now(timezone.utc)
    for st in ids["station"]:
        for _ in range(40):
            comp = rnd.choices(list(COMPONENTS), [50, 15, 25, 10])[0]
            shelf = COMPONENTS[comp][0]
            col = t0 - timedelta(days=rnd.uniform(0, shelf - 0.5))
            g = rnd.choices(["O", "A", "B", "AB"], [45, 35, 15, 5])[0]
            uid = conn.execute(
                "INSERT INTO units(component,blood_group,rh,volume_ml,collected_at,expires_at,status,institution_id,donor_id)"
                " VALUES(?,?,?,?,?,?,'stored',?,?)",
                (comp, g, rnd.choices("+-", [85, 15])[0], 450, col.isoformat(timespec="seconds"),
                 (col + timedelta(days=shelf)).isoformat(timespec="seconds"), st, rnd.choice(donor_ids))).lastrowid
            trace_event(conn, uid, "collected", None, None, st)
            trace_event(conn, uid, "stored", None, None, st)
    for h in ids["hospital"]:
        for _ in range(15):
            conn.execute("INSERT INTO requests(hospital_id,component,blood_group,rh,units_needed,urgency,status,created_at)"
                         " VALUES(?,?,?,?,?,?,'fulfilled',?)",
                         (h, rnd.choice(["red_cells", "plasma", "platelets"]), rnd.choices(["O", "A", "B"], [50, 35, 15])[0],
                          rnd.choices("+-", [85, 15])[0], rnd.randint(1, 4), "urgent",
                          (t0 - timedelta(days=rnd.uniform(0, 27))).isoformat(timespec="seconds")))
    conn.commit()


if __name__ == "__main__":
    init_db()
    c = connect()
    if c.execute("SELECT 1 FROM institutions").fetchone():
        print("База уже заполнена")
    else:
        seed(c)
        print("Готово. Вход: admin@bpsc.kz / Admin12345, station1@bpsc.kz и hospital1@bpsc.kz / Staff12345, "
              "donor1@example.kz / Donor12345")
