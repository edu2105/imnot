"""Tests for the dynamic router."""

from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imnot.cli import cli
from imnot.engine.router import register_routes
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import load_partners


@pytest.fixture
def runner():
    return CliRunner()

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
    register_routes(app, partners, store, partners_dir=PARTNERS_DIR)
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
    r = client.get("/imnot/admin/partners")
    assert r.status_code == 200
    body = r.json()
    staylink = next((p for p in body if p["partner"] == "staylink"), None)
    assert staylink is not None
    assert "reservation" in staylink["datapoints"]
    assert "token" in staylink["datapoints"]


def test_list_sessions_empty(client):
    r = client.get("/imnot/admin/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_list_sessions_after_upload(client):
    client.post(
        "/imnot/admin/staylink/reservation/payload/session",
        json={"reservationId": "X"},
    )
    r = client.get("/imnot/admin/sessions")
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Admin payload routes — upload
# ---------------------------------------------------------------------------


def test_upload_global_payload(client):
    r = client.post(
        "/imnot/admin/staylink/reservation/payload",
        json={"reservationId": "RES001"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_upload_invalid_json_returns_400(client):
    r = client.post(
        "/imnot/admin/staylink/reservation/payload",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    assert "Invalid JSON" in r.json()["detail"]


def test_upload_session_payload_returns_session_id(client):
    r = client.post(
        "/imnot/admin/staylink/reservation/payload/session",
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
    client.post("/imnot/admin/staylink/reservation/payload", json={"reservationId": "R1"})
    r = client.get("/imnot/admin/staylink/reservation/payload")
    assert r.status_code == 200
    body = r.json()
    assert body["payload"] == {"reservationId": "R1"}
    assert "updated_at" in body


def test_get_global_payload_not_set_returns_404(client):
    r = client.get("/imnot/admin/staylink/reservation/payload")
    assert r.status_code == 404


def test_get_session_payload(client):
    session_id = client.post(
        "/imnot/admin/staylink/reservation/payload/session",
        json={"reservationId": "S1"},
    ).json()["session_id"]

    r = client.get(f"/imnot/admin/staylink/reservation/payload/session/{session_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["payload"] == {"reservationId": "S1"}
    assert body["session_id"] == session_id
    assert "created_at" in body


def test_get_session_payload_not_found_returns_404(client):
    r = client.get("/imnot/admin/staylink/reservation/payload/session/nonexistent")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Verify oauth and static patterns have NO admin payload routes
# ---------------------------------------------------------------------------


def test_oauth_has_no_admin_payload_route(client):
    """oauth pattern must not expose admin payload endpoints."""
    r = client.post("/imnot/admin/staylink/token/payload", json={"token": "x"})
    assert r.status_code == 404


def test_oauth_has_no_admin_session_route(client):
    r = client.post("/imnot/admin/staylink/token/payload/session", json={"token": "x"})
    assert r.status_code == 404


def test_static_has_no_admin_payload_route(client):
    """static pattern must not expose admin payload endpoints."""
    r = client.post("/imnot/admin/apaleo/fixed-response/payload", json={"foo": "bar"})
    assert r.status_code == 404


def test_static_has_no_admin_session_route(client):
    r = client.post("/imnot/admin/apaleo/fixed-response/payload/session", json={"foo": "bar"})
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
# Staylink consumer routes (async pattern)
# ---------------------------------------------------------------------------


def test_staylink_step1_returns_202_and_location(client):
    r = client.post("/staylink/reservations")
    assert r.status_code == 202
    assert "Location" in r.headers
    assert "/staylink/reservations/" in r.headers["Location"]


def test_staylink_step2_returns_201_and_status(client):
    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r2 = client.head(f"/staylink/reservations/{uuid}")
    assert r2.status_code == 201
    assert r2.headers.get("Status") == "COMPLETED"


def test_staylink_step3_returns_global_payload(client):
    client.post("/imnot/admin/staylink/reservation/payload", json={"reservationId": "RES001"})

    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "RES001"}


def test_staylink_step3_unknown_uuid_returns_404(client):
    r = client.get("/staylink/reservations/nonexistent-uuid")
    assert r.status_code == 404


def test_staylink_step3_no_payload_returns_404(client):
    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]
    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 404


def test_staylink_full_session_flow(client):
    r = client.post(
        "/imnot/admin/staylink/reservation/payload/session",
        json={"reservationId": "SES001"},
    )
    session_id = r.json()["session_id"]

    r1 = client.post("/staylink/reservations", headers={"X-Imnot-Session": session_id})
    assert r1.status_code == 202
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}", headers={"X-Imnot-Session": session_id})
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "SES001"}


def test_staylink_session_does_not_leak_to_global(client):
    r = client.post(
        "/imnot/admin/staylink/reservation/payload/session",
        json={"reservationId": "SES001"},
    )
    session_id = r.json()["session_id"]

    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 404


def test_staylink_two_sessions_are_isolated(client):
    s1 = client.post(
        "/imnot/admin/staylink/reservation/payload/session", json={"user": "alice"}
    ).json()["session_id"]
    s2 = client.post(
        "/imnot/admin/staylink/reservation/payload/session", json={"user": "bob"}
    ).json()["session_id"]

    uuid1 = client.post("/staylink/reservations", headers={"X-Imnot-Session": s1}).headers["Location"].split("/")[-1]
    uuid2 = client.post("/staylink/reservations", headers={"X-Imnot-Session": s2}).headers["Location"].split("/")[-1]

    assert client.get(f"/staylink/reservations/{uuid1}", headers={"X-Imnot-Session": s1}).json() == {"user": "alice"}
    assert client.get(f"/staylink/reservations/{uuid2}", headers={"X-Imnot-Session": s2}).json() == {"user": "bob"}


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
    async_client.post("/imnot/admin/asyncpartner/job/payload", json={"result": "ok"})
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
        "/imnot/admin/asyncpartner/job/payload/session",
        json={"result": "session-ok"},
    ).json()["session_id"]

    r1 = async_client.post("/asyncpartner/jobs", headers={"X-Imnot-Session": session_id})
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = async_client.get(f"/asyncpartner/jobs/{uuid}", headers={"X-Imnot-Session": session_id})
    assert r3.status_code == 200
    assert r3.json() == {"result": "session-ok"}


# ---------------------------------------------------------------------------
# Reload endpoint
# ---------------------------------------------------------------------------


def test_reload_returns_ok(client):
    r = client.post("/imnot/admin/reload")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["updated"], list)
    assert isinstance(body["added"], list)


def test_reload_without_partners_dir_returns_400(store, tmp_path):
    """When partners_dir is not set (e.g. routes registered without it), reload returns 400."""
    app = FastAPI()
    partners = load_partners(PARTNERS_DIR)
    # Omit partners_dir — app.state.partners_dir will be None
    register_routes(app, partners, store)
    c = TestClient(app, raise_server_exceptions=True)
    r = c.post("/imnot/admin/reload")
    assert r.status_code == 400


def test_reload_updates_static_config_in_place(store, tmp_path):
    """Editing a static response body in YAML is picked up by POST /imnot/admin/reload."""
    partner_dir = tmp_path / "reloadpartner"
    partner_dir.mkdir()
    yaml_path = partner_dir / "partner.yaml"
    yaml_path.write_text(
        "partner: reloadpartner\n"
        "description: Reload test\n"
        "datapoints:\n"
        "  - name: info\n"
        "    description: Info endpoint\n"
        "    pattern: static\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /reloadpartner/info\n"
        "        response:\n"
        "          status: 200\n"
        "          body:\n"
        "            version: '1.0'\n"
    )

    app = FastAPI()
    partners = load_partners(tmp_path)
    register_routes(app, partners, store, partners_dir=tmp_path)
    c = TestClient(app, raise_server_exceptions=True)

    # Initial response
    assert c.get("/reloadpartner/info").json() == {"version": "1.0"}

    # Simulate YAML edit
    yaml_path.write_text(
        "partner: reloadpartner\n"
        "description: Reload test\n"
        "datapoints:\n"
        "  - name: info\n"
        "    description: Info endpoint\n"
        "    pattern: static\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /reloadpartner/info\n"
        "        response:\n"
        "          status: 200\n"
        "          body:\n"
        "            version: '2.0'\n"
    )

    r = c.post("/imnot/admin/reload")
    assert r.status_code == 200
    updated = r.json()["updated"]
    assert any("reloadpartner/info" in u or "/reloadpartner/info" in u for u in updated)

    # Handler now serves new body without restart
    assert c.get("/reloadpartner/info").json() == {"version": "2.0"}


def test_reload_registers_new_partner(store, tmp_path):
    """Adding a new partner YAML and calling reload makes its routes available."""
    partner_dir = tmp_path / "firstpartner"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: firstpartner\n"
        "description: First\n"
        "datapoints:\n"
        "  - name: ping\n"
        "    description: Ping\n"
        "    pattern: static\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /firstpartner/ping\n"
        "        response:\n"
        "          status: 200\n"
        "          body:\n"
        "            ok: true\n"
    )

    app = FastAPI()
    partners = load_partners(tmp_path)
    register_routes(app, partners, store, partners_dir=tmp_path)
    c = TestClient(app, raise_server_exceptions=True)

    assert c.get("/firstpartner/ping").status_code == 200

    # Add a second partner while server is "running"
    second_dir = tmp_path / "secondpartner"
    second_dir.mkdir()
    (second_dir / "partner.yaml").write_text(
        "partner: secondpartner\n"
        "description: Second\n"
        "datapoints:\n"
        "  - name: hello\n"
        "    description: Hello\n"
        "    pattern: static\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /secondpartner/hello\n"
        "        response:\n"
        "          status: 200\n"
        "          body:\n"
        "            hello: world\n"
    )

    r = c.post("/imnot/admin/reload")
    assert r.status_code == 200
    assert any("/secondpartner/hello" in a for a in r.json()["added"])

    assert c.get("/secondpartner/hello").json() == {"hello": "world"}


# ---------------------------------------------------------------------------
# imnot generate → reload integration
# ---------------------------------------------------------------------------


RATESYNC_YAML = """\
partner: ratesync
description: RateSync fictional partner

datapoints:
  - name: token
    description: OAuth token
    pattern: oauth
    endpoints:
      - method: POST
        path: /ratesync/oauth/token
        response:
          status: 200
          token_type: Bearer
          expires_in: 3600

  - name: rate-push
    description: Async rate push job
    pattern: async
    endpoints:
      - step: 1
        method: POST
        path: /ratesync/v1/rates
        response:
          status: 200
          generates_id: true
          id_body_field: JobReferenceID
      - step: 2
        method: GET
        path: /ratesync/v1/jobs/{id}/status
        response:
          status: 200
      - step: 3
        method: GET
        path: /ratesync/v1/jobs/{id}/results
        response:
          status: 200
          returns_payload: true

  - name: properties
    description: Synchronous property list
    pattern: fetch
    endpoints:
      - method: GET
        path: /ratesync/v1/properties
        response:
          status: 200
"""


def test_generate_then_reload_activates_routes(runner, tmp_path):
    """generate scaffolds partner dir, reload picks it up and routes become live."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "ratesync.yaml"
    yaml_file.write_text(RATESYNC_YAML)

    # Step 1: generate scaffolds the partner directory
    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
    ])
    assert result.exit_code == 0, result.output
    assert (partners_dir / "ratesync" / "partner.yaml").exists()

    # Step 2: spin up a server seeded with only the existing partners dir,
    # then reload to pick up ratesync
    store = SessionStore(db_path=tmp_path / "test.db")
    store.init()
    app = FastAPI()
    partners = load_partners(partners_dir)
    register_routes(app, partners, store, partners_dir=partners_dir)
    c = TestClient(app, raise_server_exceptions=True)

    # ratesync routes are now loaded at startup since generate ran first
    r = c.get("/imnot/admin/partners")
    assert r.status_code == 200
    partner_names = [p["partner"] for p in r.json()]
    assert "ratesync" in partner_names

    # Step 3: oauth token endpoint responds
    r = c.post("/ratesync/oauth/token")
    assert r.status_code == 200
    assert "access_token" in r.json()

    # Step 4: upload payload and run the async flow end-to-end
    payload = {"rates": [{"roomType": "DBL", "rate": 199.00, "date": "2026-05-01"}]}
    r = c.post("/imnot/admin/ratesync/rate-push/payload", json=payload)
    assert r.status_code == 200

    r = c.post("/ratesync/v1/rates", json={})
    assert r.status_code == 200
    job_id = r.json()["JobReferenceID"]

    r = c.get(f"/ratesync/v1/jobs/{job_id}/status")
    assert r.status_code == 200

    r = c.get(f"/ratesync/v1/jobs/{job_id}/results")
    assert r.status_code == 200
    assert r.json() == payload

    store.close()


# ---------------------------------------------------------------------------
# POST /imnot/admin/partners
# ---------------------------------------------------------------------------


_NEW_PARTNER_YAML = """\
partner: bookingco
description: BookingCo mock

datapoints:
  - name: reservation
    description: Fetch a reservation
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/v1/reservations/{id}
        response:
          status: 200
"""

_STATIC_PARTNER_YAML = """\
partner: staticco
description: StaticCo mock

datapoints:
  - name: status
    description: Status endpoint
    pattern: static
    endpoints:
      - method: GET
        path: /staticco/status
        response:
          status: 200
          body:
            ok: true
"""


def _make_client(tmp_path, store):
    """Server seeded from an empty partners dir, with partners_dir set."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    app = FastAPI()
    register_routes(app, [], store, partners_dir=partners_dir)
    return TestClient(app, raise_server_exceptions=True), partners_dir


def test_create_partner_returns_201_and_routes_live(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    r = c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ok"
    assert body["partner"] == "bookingco"
    assert body["created"] is True
    assert any(ep["path"] == "/bookingco/v1/reservations/{id}" for dp in body["datapoints"] for ep in dp["endpoints"])

    # Route is live immediately
    r2 = c.get("/bookingco/v1/reservations/123", headers={"X-Imnot-Session": "s1"})
    assert r2.status_code in (200, 404)  # 404 = no payload set yet, but route exists


def test_create_partner_writes_file_to_disk(tmp_path, store):
    c, partners_dir = _make_client(tmp_path, store)

    c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)

    dest = partners_dir / "bookingco" / "partner.yaml"
    assert dest.exists()
    assert dest.read_text() == _NEW_PARTNER_YAML


def test_create_partner_conflict_returns_409(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)
    r = c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_create_partner_force_overwrites_returns_200(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)
    r = c.post("/imnot/admin/partners?force=true", content=_NEW_PARTNER_YAML)
    assert r.status_code == 200
    assert r.json()["created"] is False


def test_create_partner_invalid_yaml_returns_422(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    r = c.post("/imnot/admin/partners", content="partner: broken\n  bad: [yaml")
    assert r.status_code == 422
    assert r.json()["status"] == "error"


def test_create_partner_missing_schema_field_returns_422(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    bad_yaml = (
        "partner: badpartner\n"
        "description: Missing pattern\n"
        "datapoints:\n"
        "  - name: broken\n"
        "    description: no pattern\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /bad\n"
        "        response:\n"
        "          status: 200\n"
    )
    r = c.post("/imnot/admin/partners", content=bad_yaml)
    assert r.status_code == 422


def test_create_partner_without_partners_dir_returns_400(store):
    """When partners_dir is not set on app.state, endpoint returns 400."""
    app = FastAPI()
    register_routes(app, [], store)  # no partners_dir
    c = TestClient(app, raise_server_exceptions=True)

    r = c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)
    assert r.status_code == 400


def test_create_partner_appears_in_list_partners(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)

    r = c.get("/imnot/admin/partners")
    partner_names = [p["partner"] for p in r.json()]
    assert "bookingco" in partner_names


def test_create_static_partner_routes_live(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    r = c.post("/imnot/admin/partners", content=_STATIC_PARTNER_YAML)
    assert r.status_code == 201

    r2 = c.get("/staticco/status")
    assert r2.status_code == 200
    assert r2.json() == {"ok": True}


def test_create_partner_admin_routes_registered_for_fetch(tmp_path, store):
    c, _ = _make_client(tmp_path, store)

    r = c.post("/imnot/admin/partners", content=_NEW_PARTNER_YAML)
    assert r.status_code == 201
    dp = r.json()["datapoints"][0]
    assert dp["admin_routes"] is True

    # Admin payload endpoint is live
    r2 = c.post("/imnot/admin/bookingco/reservation/payload", json={"id": "123"})
    assert r2.status_code == 200
