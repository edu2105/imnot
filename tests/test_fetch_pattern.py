"""Tests for the fetch pattern handler."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imnot.engine.patterns.fetch import make_fetch_handler
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


def _make_datapoint(name: str = "charges") -> DatapointDef:
    return DatapointDef(
        name=name,
        description="",
        pattern="fetch",
        endpoints=[],
    )


def _make_endpoint(status: int = 200) -> EndpointDef:
    return EndpointDef(method="GET", path="/api/v2/charges", step=None, response={"status": status})


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


@pytest.fixture
def client(store):
    app = FastAPI()
    datapoint = _make_datapoint()
    endpoint = _make_endpoint()
    handler = make_fetch_handler("leanpms", datapoint, endpoint, store)
    app.add_api_route("/api/v2/charges", handler, methods=["GET"])
    return TestClient(app, raise_server_exceptions=True), store


# ---------------------------------------------------------------------------
# Handler construction
# ---------------------------------------------------------------------------


def test_handler_is_callable(store):
    handler = make_fetch_handler("leanpms", _make_datapoint(), _make_endpoint(), store)
    assert callable(handler)


def test_handler_has_unique_name(store):
    handler = make_fetch_handler("leanpms", _make_datapoint(), _make_endpoint(), store)
    assert "fetch" in handler.__name__
    assert "leanpms" in handler.__name__


# ---------------------------------------------------------------------------
# No payload uploaded
# ---------------------------------------------------------------------------


def test_returns_404_when_no_global_payload(client):
    c, _ = client
    r = c.get("/api/v2/charges")
    assert r.status_code == 404
    assert "global payload" in r.json()["detail"]


def test_returns_404_when_session_payload_missing(client):
    c, _ = client
    r = c.get("/api/v2/charges", headers={"X-Imnot-Session": "nonexistent"})
    assert r.status_code == 404
    assert "nonexistent" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Global payload flow
# ---------------------------------------------------------------------------


def test_returns_global_payload(client):
    c, store = client
    store.store_global_payload("leanpms", "charges", {"charges": [{"id": "C1", "amount": 100}]})
    r = c.get("/api/v2/charges")
    assert r.status_code == 200
    assert r.json() == {"charges": [{"id": "C1", "amount": 100}]}


def test_respects_custom_status_code(store):
    app = FastAPI()
    endpoint = _make_endpoint(status=202)
    handler = make_fetch_handler("leanpms", _make_datapoint(), endpoint, store)
    app.add_api_route("/api/v2/charges", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("leanpms", "charges", {"ok": True})
    r = c.get("/api/v2/charges")
    assert r.status_code == 202


# ---------------------------------------------------------------------------
# Session payload flow
# ---------------------------------------------------------------------------


def test_returns_session_payload_when_header_present(client):
    c, store = client
    session_id = store.store_session_payload("leanpms", "charges", {"charges": [{"id": "S1"}]})
    r = c.get("/api/v2/charges", headers={"X-Imnot-Session": session_id})
    assert r.status_code == 200
    assert r.json() == {"charges": [{"id": "S1"}]}


def test_session_does_not_leak_to_global(client):
    c, store = client
    store.store_session_payload("leanpms", "charges", {"charges": []})
    # No global payload set — request without session header should 404
    r = c.get("/api/v2/charges")
    assert r.status_code == 404


def test_two_sessions_are_isolated(client):
    c, store = client
    s1 = store.store_session_payload("leanpms", "charges", {"user": "alice"})
    s2 = store.store_session_payload("leanpms", "charges", {"user": "bob"})
    assert c.get("/api/v2/charges", headers={"X-Imnot-Session": s1}).json() == {"user": "alice"}
    assert c.get("/api/v2/charges", headers={"X-Imnot-Session": s2}).json() == {"user": "bob"}
