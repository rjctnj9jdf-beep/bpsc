"bd"
import os
import sqlite3
from datetime import datetime, timezone


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS institutions(
  id INTEGER PRIMARY KEY, type TEXT NOT NULL CHECK(type IN ('station','hospital')),
  name TEXT NOT NULL, region TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('donor','station','hospital','admin')),
  institution_id INTEGER REFERENCES institutions(id), active INTEGER NOT NULL DEFAULT 1,
  failed_attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS donors(
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  full_name_enc TEXT NOT NULL, contacts_enc TEXT NOT NULL,
  blood_group TEXT NOT NULL, rh TEXT NOT NULL, last_donation_date TEXT,
  lat REAL NOT NULL, lon REAL NOT NULL, notify_radius_km INTEGER NOT NULL DEFAULT 10,
  consent INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS units(
  id INTEGER PRIMARY KEY, component TEXT NOT NULL, blood_group TEXT NOT NULL, rh TEXT NOT NULL,
  volume_ml INTEGER NOT NULL, collected_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  status TEXT NOT NULL, institution_id INTEGER NOT NULL REFERENCES institutions(id),
  donor_id INTEGER REFERENCES donors(id), request_id INTEGER);
CREATE TABLE IF NOT EXISTS requests(
  id INTEGER PRIMARY KEY, hospital_id INTEGER NOT NULL REFERENCES institutions(id),
  component TEXT NOT NULL, blood_group TEXT NOT NULL, rh TEXT NOT NULL,
  units_needed INTEGER NOT NULL, urgency TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open',
  reserved_units INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL REFERENCES requests(id),
  donor_id INTEGER NOT NULL REFERENCES donors(id), status TEXT NOT NULL DEFAULT 'sent',
  sent_at TEXT NOT NULL, UNIQUE(request_id, donor_id));
CREATE TABLE IF NOT EXISTS trace(
  id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL REFERENCES units(id), event_type TEXT NOT NULL,
  from_institution INTEGER, to_institution INTEGER, actor_id INTEGER, note TEXT, timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, actor_id INTEGER, action TEXT NOT NULL, target TEXT, timestamp TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS appointments(
  id INTEGER PRIMARY KEY, donor_id INTEGER NOT NULL REFERENCES donors(id),
  station_id INTEGER NOT NULL REFERENCES institutions(id), slot_at TEXT NOT NULL, component TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'booked' CHECK(status IN ('booked','completed','cancelled','no_show')),
  request_id INTEGER REFERENCES requests(id), unit_id INTEGER REFERENCES units(id), created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_appt_station_slot ON appointments(station_id, slot_at);
CREATE INDEX IF NOT EXISTS ix_appt_donor ON appointments(donor_id);
CREATE TRIGGER IF NOT EXISTS trace_no_update BEFORE UPDATE ON trace BEGIN SELECT RAISE(ABORT,'trace is append-only'); END;
CREATE TRIGGER IF NOT EXISTS trace_no_delete BEFORE DELETE ON trace BEGIN SELECT RAISE(ABORT,'trace is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(os.getenv("BPSC_DB", "bpsc.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    request_columns = {r["name"] for r in conn.execute("PRAGMA table_info(requests)")}
    if "closed_at" not in request_columns:
        conn.execute("ALTER TABLE requests ADD COLUMN closed_at TEXT")
    conn.commit()
    conn.close()


def get_db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
