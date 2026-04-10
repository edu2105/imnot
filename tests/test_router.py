"""Tests for the dynamic router."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mirage.engine.router import register_routes
from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import load_partners

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


@pytest.fixture
def client(store):
    app = FastAPI()
    partners = load_partners(PARTNERS_DIR)
    register_routes(app, partners, store)
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def async_client(tmp_path, store):
    partner_dir = tmp_path / "asyncpartner"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: asyncpartner\n"
        "description: Async test partner\n"
        "datapoints:\n"
        "  - name: job\n"
        "    description: Async job\n"
        "    pattern: async\n"
        "    endpoints:\n"
        "      - step: 1\n"
        "        method: POST\n"
        "        path: /asyncpartner/jobs\n"
        "        response:\n"
        "          status: 202\n"
        "          generates_id: true\n"
        "          id_header: Location\n"
        "          id_header_value: /asyncpartner/jobs/{id}\n"
        "      - step: 2\n"
        "        method: HEAD\n"
        "        path: /asyncpartner/jobs/{id}\n"
        "        response:\n"
        "          status: 201\n"
        "          headers:\n"
        "            Status: COMPLETED\n"
        "      - step: 3\n"
        "        method: GET\n"
        "        path: /asyncpartner/jobs/{id}\n"
        "        response:\n"
        "          status: 200\n"
        "          returns_payload: true\n"
    )
    app = FastAPI()
    partners = load_partners(tmp_path)
    register_routes(app, partners, store)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Infra routes
# ---------------------------------------------------------------------------


def test_list_partners(client):
    r = client.get("/mirage/admin/partners")
    assert r.status_code == 200
    body = r.json()
    staylink = next((p for p in body if p["partner"] == "staylink"), None)
    assert staylink is not None
    assert "reservation" in staylink["datapoints"]
    assert "token" in staylink["datapoints"]


def test_list_sessions_empty(client):
    r = client.get("/mirage/admin/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_list_sessions_after_upload(client):
    client.post(
        "/mirage/admin/staylink/reservation/payload/session",
        json={"reservationId": "X"},
    )
    r = client.get("/mirage/admin/sessions")
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Admin payload routes — upload
# ---------------------------------------------------------------------------


def test_upload_global_payload(client):
    r = client.post(
        "/mirage/admin/staylink/reservation/payload",
        json={"reservationId": "RES001"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_invalid_json_returns_400(client):
    r = client.post(
        "/mirage/admin/staylink/reservation/payload",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert "Invalid JSON" in r.json()["detail"]


def test_upload_session_payload_returns_session_id(client):
    r = client.post(
        "/mirage/admin/staylink/reservation/payload/session",
        json={"reservationId": "RES002"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "session_id" in body
    assert len(body["session_id"]) == 36  # UUID


# ---------------------------------------------------------------------------
# Admin payload routes — inspect
# ---------------------------------------------------------------------------


def test_get_global_payload(client):
    client.post("/mirage/admin/staylink/reservation/payload", json={"reservationId": "R1"})
    r = client.get("/mirage/admin/staylink/reservation/payload")
    assert r.status_code == 200
    body = r.json()
    assert body["payload"] == {"reservationId": "R1"}
    assert "updated_at" in body


def test_get_global_payload_not_set_returns_404(client):
    r = client.get("/mirage/admin/staylink/reservation/payload")
    assert r.status_code == 404


def test_get_session_payload(client):
    session_id = client.post(
        "/mirage/admin/staylink/reservation/payload/session",
        json={"reservationId": "S1"},
    ).json()["session_id"]

    r = client.get(f"/mirage/admin/staylink/reservation/payload/session/{session_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["payload"] == {"reservationId": "S1"}
    assert body["session_id"] == session_id
    assert "created_at" in body


def test_get_session_payload_not_found_returns_404(client):
    r = client.get("/mirage/admin/staylink/reservation/payload/session/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# OAuth consumer route
# ---------------------------------------------------------------------------


def test_oauth_token(client):
    r = client.post("/oauth/token")
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert isinstance(body["access_token"], str)


# ---------------------------------------------------------------------------
# Poll consumer routes — global payload flow
# ---------------------------------------------------------------------------


def test_poll_step1_returns_202_and_location(client):
    r = client.post("/staylink/reservations")
    assert r.status_code == 202
    assert "Location" in r.headers
    assert "/staylink/reservations/" in r.headers["Location"]


def test_poll_step2_returns_201_and_status(client):
    # Step 1 to get a UUID
    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r2 = client.head(f"/staylink/reservations/{uuid}")
    assert r2.status_code == 201
    assert r2.headers.get("Status") == "COMPLETED"


def test_poll_step3_returns_global_payload(client):
    client.post("/mirage/admin/staylink/reservation/payload", json={"reservationId": "RES001"})

    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "RES001"}


def test_poll_step3_unknown_uuid_returns_404(client):
    r = client.get("/staylink/reservations/nonexistent-uuid")
    assert r.status_code == 404


def test_poll_step3_no_payload_returns_404(client):
    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 404


# ---------------------------------------------------------------------------
# Poll consumer routes — session payload flow
# ---------------------------------------------------------------------------


def test_full_session_flow(client):
    # Upload session payload
    r = client.post(
        "/mirage/admin/staylink/reservation/payload/session",
        json={"reservationId": "SES001"},
    )
    session_id = r.json()["session_id"]

    # Step 1 with session header
    r1 = client.post("/staylink/reservations", headers={"X-Mirage-Session": session_id})
    assert r1.status_code == 202
    uuid = r1.headers["Location"].split("/")[-1]

    # Step 3 with session header
    r3 = client.get(f"/staylink/reservations/{uuid}", headers={"X-Mirage-Session": session_id})
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "SES001"}


def test_session_does_not_leak_to_global(client):
    # Upload session payload only — no global
    r = client.post(
        "/mirage/admin/staylink/reservation/payload/session",
        json={"reservationId": "SES001"},
    )
    session_id = r.json()["session_id"]

    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    # GET without session header → no global payload → 404
    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 404


def test_two_sessions_are_isolated(client):
    s1 = client.post(
        "/mirage/admin/staylink/reservation/payload/session", json={"user": "alice"}
    ).json()["session_id"]
    s2 = client.post(
        "/mirage/admin/staylink/reservation/payload/session", json={"user": "bob"}
    ).json()["session_id"]

    uuid1 = client.post("/staylink/reservations", headers={"X-Mirage-Session": s1}).headers["Location"].split("/")[-1]
    uuid2 = client.post("/staylink/reservations", headers={"X-Mirage-Session": s2}).headers["Location"].split("/")[-1]

    assert client.get(f"/staylink/reservations/{uuid1}", headers={"X-Mirage-Session": s1}).json() == {"user": "alice"}
    assert client.get(f"/staylink/reservations/{uuid2}", headers={"X-Mirage-Session": s2}).json() == {"user": "bob"}


# ---------------------------------------------------------------------------
# Async consumer routes
# ---------------------------------------------------------------------------


def test_async_step1_returns_202_and_location(async_client):
    r = async_client.post("/asyncpartner/jobs")
    assert r.status_code == 202
    assert "Location" in r.headers
    assert "/asyncpartner/jobs/" in r.headers["Location"]


def test_async_step2_returns_201_and_status_header(async_client):
    r1 = async_client.post("/asyncpartner/jobs")
    uuid = r1.headers["Location"].split("/")[-1]

    r2 = async_client.head(f"/asyncpartner/jobs/{uuid}")
    assert r2.status_code == 201
    assert r2.headers.get("Status") == "COMPLETED"


def test_async_step3_returns_global_payload(async_client):
    async_client.post("/mirage/admin/asyncpartner/job/payload", json={"result": "ok"})
    r1 = async_client.post("/asyncpartner/jobs")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = async_client.get(f"/asyncpartner/jobs/{uuid}")
    assert r3.status_code == 200
    assert r3.json() == {"result": "ok"}


def test_async_step3_unknown_uuid_returns_404(async_client):
    r = async_client.get("/asyncpartner/jobs/nonexistent-uuid")
    assert r.status_code == 404


def test_async_step3_no_payload_returns_404(async_client):
    r1 = async_client.post("/asyncpartner/jobs")
    uuid = r1.headers["Location"].split("/")[-1]
    r3 = async_client.get(f"/asyncpartner/jobs/{uuid}")
    assert r3.status_code == 404


def test_async_full_session_flow(async_client):
    session_id = async_client.post(
        "/mirage/admin/asyncpartner/job/payload/session",
        json={"result": "session-ok"},
    ).json()["session_id"]

    r1 = async_client.post("/asyncpartner/jobs", headers={"X-Mirage-Session": session_id})
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = async_client.get(f"/asyncpartner/jobs/{uuid}", headers={"X-Mirage-Session": session_id})
    assert r3.status_code == 200
    assert r3.json() == {"result": "session-ok"}
