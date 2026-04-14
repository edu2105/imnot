"""Tests for the app factory."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


@pytest.fixture
def client(tmp_path):
    app = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "test.db")
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# App boots correctly
# ---------------------------------------------------------------------------


def test_app_starts_and_lists_partners(client):
    r = client.get("/imnot/admin/partners")
    assert r.status_code == 200
    assert any(p["partner"] == "staylink" for p in r.json())


def test_app_has_openapi_schema(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json()["info"]["title"] == "imnot"


# ---------------------------------------------------------------------------
# Full OHIP flow through create_app (integration smoke test)
# ---------------------------------------------------------------------------


def test_full_global_flow(client):
    # Upload payload
    client.post(
        "/imnot/admin/staylink/reservation/payload",
        json={"reservationId": "GLOBAL001", "status": "CONFIRMED"},
    )

    # OAuth token
    token_r = client.post("/oauth/token")
    assert token_r.status_code == 200
    assert token_r.json()["token_type"] == "Bearer"

    # Poll step 1
    r1 = client.post("/staylink/reservations")
    assert r1.status_code == 202
    uuid = r1.headers["Location"].split("/")[-1]

    # Poll step 2
    r2 = client.head(f"/staylink/reservations/{uuid}")
    assert r2.status_code == 201
    assert r2.headers["Status"] == "COMPLETED"

    # Poll step 3
    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "GLOBAL001", "status": "CONFIRMED"}


def test_full_session_flow(client):
    # Upload session payload
    session_id = client.post(
        "/imnot/admin/staylink/reservation/payload/session",
        json={"reservationId": "SES001"},
    ).json()["session_id"]

    # Poll step 1 with session
    r1 = client.post("/staylink/reservations", headers={"X-Imnot-Session": session_id})
    uuid = r1.headers["Location"].split("/")[-1]

    # Poll step 3 with session
    r3 = client.get(f"/staylink/reservations/{uuid}", headers={"X-Imnot-Session": session_id})
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "SES001"}

    # Same UUID without session header → no global payload → 404
    r_no_session = client.get(f"/staylink/reservations/{uuid}")
    assert r_no_session.status_code == 404


def test_multiple_app_instances_do_not_share_state(tmp_path):
    """Each create_app() call gets its own isolated store."""
    app1 = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "a.db")
    app2 = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "b.db")

    with TestClient(app1) as c1, TestClient(app2) as c2:
        c1.post("/imnot/admin/staylink/reservation/payload", json={"src": "app1"})

        # app2 has no payload
        r1 = c1.post("/staylink/reservations")
        r2 = c2.post("/staylink/reservations")

        uuid1 = r1.headers["Location"].split("/")[-1]
        uuid2 = r2.headers["Location"].split("/")[-1]

        assert c1.get(f"/staylink/reservations/{uuid1}").status_code == 200
        assert c2.get(f"/staylink/reservations/{uuid2}").status_code == 404


# ---------------------------------------------------------------------------
# Admin key authentication
# ---------------------------------------------------------------------------


@pytest.fixture
def authed_client(tmp_path):
    app = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "test.db", admin_key="secret")
    with TestClient(app) as c:
        yield c


def test_admin_open_when_no_key_set(client):
    """Without admin_key, all admin endpoints are open."""
    r = client.get("/imnot/admin/partners")
    assert r.status_code == 200


def test_admin_requires_auth_when_key_set(authed_client):
    r = authed_client.get("/imnot/admin/partners")
    assert r.status_code == 401


def test_admin_accepts_correct_bearer_token(authed_client):
    r = authed_client.get("/imnot/admin/partners", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200


def test_admin_rejects_wrong_token(authed_client):
    r = authed_client.get("/imnot/admin/partners", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_admin_rejects_missing_bearer_prefix(authed_client):
    r = authed_client.get("/imnot/admin/partners", headers={"Authorization": "secret"})
    assert r.status_code == 401


def test_consumer_endpoints_not_affected_by_admin_key(authed_client):
    """Consumer routes (non-admin) must remain accessible without auth."""
    r = authed_client.post("/oauth/token")
    assert r.status_code == 200
