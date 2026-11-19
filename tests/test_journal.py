"""Request journal: middleware, store and GET/DELETE /imnot/admin/requests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.engine import journal, session_store

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


@pytest.fixture
def client(tmp_path):
    app = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "j.db")
    with TestClient(app) as c:
        yield c


def _entries(c, **params):
    return c.get("/imnot/admin/requests", params=params).json()


def test_records_a_mock_request_with_owner_body_and_status(client):
    sid = client.post("/imnot/admin/bookingco/charges/payload/session", json={"ok": True}).json()["session_id"]
    client.get("/bookingco/v1/charges?property=P1", headers={"X-Imnot-Session": sid})

    (entry,) = _entries(client)
    assert entry["partner"] == "bookingco" and entry["datapoint"] == "charges"
    assert entry["method"] == "GET" and entry["path"] == "/bookingco/v1/charges"
    assert entry["query"] == "property=P1"
    assert entry["session_id"] == sid
    assert entry["status"] == 200


def test_records_post_body_and_unmatched_routes(client):
    client.post("/oauth/token", data="grant_type=client_credentials")
    client.get("/nobody/here")

    unmatched, token = _entries(client)
    assert token["partner"] == "staylink" and token["body"] == "grant_type=client_credentials"
    assert unmatched["partner"] is None and unmatched["status"] == 404


def test_does_not_record_imnot_routes_or_healthz(client):
    client.get("/healthz")
    client.get("/imnot/admin/partners")
    client.get("/imnot/docs")
    client.get("/openapi.json")
    client.get("/docs")
    assert _entries(client) == []


def test_mock_routes_that_merely_start_like_docs_are_recorded(client):
    client.get("/docsign/v1/envelopes")
    client.get("/healthzcheck")
    assert [e["path"] for e in _entries(client)] == ["/healthzcheck", "/docsign/v1/envelopes"]


def test_redacts_secret_headers(client):
    client.get(
        "/nobody",
        headers={"Authorization": "Bearer abc", "X-Client-Token": "t", "Cookie": "c=1", "X-Trace": "keep"},
    )
    (entry,) = _entries(client)
    h = entry["headers"]
    assert h["authorization"] == h["x-client-token"] == h["cookie"] == journal.REDACTED
    assert h["x-trace"] == "keep"


def test_redacts_secret_fields_in_json_body_and_keeps_the_rest_verbatim(client):
    body = '{"user": "ana", "password": "p\\"w", "auth": {"client_secret": "s"}, "access_token": "t", "n": 1}'
    client.post("/nobody", content=body, headers={"Content-Type": "application/json"})
    (entry,) = _entries(client)
    assert entry["body"] == (
        '{"user": "ana", "password": "[redacted]", "auth": {"client_secret": "[redacted]"}, '
        '"access_token": "[redacted]", "n": 1}'
    )


def test_redacts_secret_fields_in_form_body_and_query(client):
    client.post(
        "/nobody?api_key=k&page=2",
        content="grant_type=client_credentials&client_id=app&client_secret=abc",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    (entry,) = _entries(client)
    assert entry["query"] == "api_key=[redacted]&page=2"
    assert entry["body"] == "grant_type=client_credentials&client_id=app&client_secret=[redacted]"


def test_plain_text_body_with_secret_looking_pairs_is_kept(client):
    # Form redaction only applies to form bodies: a text body is not guessed at.
    client.post("/nobody", content="token=abc", headers={"Content-Type": "text/plain"})
    (entry,) = _entries(client)
    assert entry["body"] == "token=abc"


def test_secret_cut_by_truncation_is_still_redacted(client, monkeypatch):
    monkeypatch.setattr(journal, "MAX_BODY_BYTES", 16)
    client.post("/nobody", content='{"password": "abcdefgh"}', headers={"Content-Type": "application/json"})
    (entry,) = _entries(client)
    assert entry["body"] == '{"password": "[redacted]"' and entry["body_truncated"] is True


def test_large_bodies_are_truncated(client, monkeypatch):
    monkeypatch.setattr(journal, "MAX_BODY_BYTES", 10)
    client.post("/nobody", content=b"x" * 50)
    (entry,) = _entries(client)
    assert entry["body"] == "x" * 10 and entry["body_truncated"] is True


def test_filters_limit_and_clear(client):
    client.get("/a", headers={"X-Imnot-Session": "s1"})
    client.post("/b", headers={"X-Imnot-Session": "s2"})
    client.get("/c", headers={"X-Imnot-Session": "s2"})

    assert [e["path"] for e in _entries(client, session="s2")] == ["/c", "/b"]
    assert [e["path"] for e in _entries(client, method="post")] == ["/b"]
    assert [e["path"] for e in _entries(client, limit=1)] == ["/c"]
    assert client.get("/imnot/admin/requests", params={"limit": 0}).status_code == 422

    assert client.delete("/imnot/admin/requests", params={"session": "s2"}).json()["deleted"] == 2
    assert [e["path"] for e in _entries(client)] == ["/a"]
    client.delete("/imnot/admin/requests")
    assert _entries(client) == []


def test_keeps_only_the_newest_entries(client, monkeypatch):
    monkeypatch.setattr(session_store, "JOURNAL_MAX_ENTRIES", 3)
    for i in range(5):
        client.get(f"/r{i}")
    assert [e["path"] for e in _entries(client, limit=10)] == ["/r4", "/r3", "/r2"]


def test_requests_endpoint_requires_admin_key(tmp_path):
    app = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "k.db", admin_key="secret")
    with TestClient(app) as c:
        assert c.get("/imnot/admin/requests").status_code == 401
        assert c.get("/imnot/admin/requests", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_a_journal_failure_never_breaks_the_mock_response(client, monkeypatch):
    def boom(entry):
        raise RuntimeError("disk full")

    monkeypatch.setattr(client.app.state.store, "log_request", boom)
    client.post("/imnot/admin/bookingco/charges/payload", json={"ok": True})
    assert client.get("/bookingco/v1/charges").json() == {"ok": True}


def test_handlers_still_read_the_replayed_body(tmp_path):
    """A handler that parses the JSON body (validate: body) must get it intact after the journal read it."""
    d = tmp_path / "partners" / "echo"
    d.mkdir(parents=True)
    (d / "partner.yaml").write_text(
        "partner: echo\n"
        "datapoints:\n"
        "  - name: order\n"
        "    pattern: static\n"
        "    endpoints:\n"
        "      - method: POST\n"
        "        path: /echo/orders\n"
        "        validate:\n"
        "          body:\n"
        "            id: {required: true, type: string}\n"
        "        response: {status: 201, body: {}}\n"
    )
    app = create_app(partners_dir=tmp_path / "partners", db_path=tmp_path / "e.db")
    with TestClient(app) as c:
        assert c.post("/echo/orders", json={"id": "O1"}).status_code == 201
        assert c.post("/echo/orders", json={}).status_code == 422
        assert [e["body"] for e in _entries(c)] == ["{}", '{"id":"O1"}']
