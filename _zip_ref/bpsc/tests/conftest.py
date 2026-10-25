import os
import sys
import tempfile
from pathlib import Path

os.environ["BPSC_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["BPSC_BCRYPT_ROUNDS"] = "4"
os.environ["BPSC_RATE_LIMIT"] = "100000"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app import seed
from app.db import connect, init_db
from app.main import app


@pytest.fixture(scope="session")
def client():
    init_db()
    conn = connect()
    seed.seed(conn, 500)
    conn.close()
    with TestClient(app) as c:
        yield c


def auth(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def station(client):
    return auth(client, "station1@bpsc.kz", "Staff12345")


@pytest.fixture(scope="session")
def hospital(client):
    return auth(client, "hospital1@bpsc.kz", "Staff12345")


@pytest.fixture(scope="session")
def admin(client):
    return auth(client, "admin@bpsc.kz", "Admin12345")


@pytest.fixture()
def db():
    c = connect()
    yield c
    c.close()
