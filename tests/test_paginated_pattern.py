"""Tests for the paginated pattern handler."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imnot.engine.patterns.paginated import make_paginated_handler
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


def _make_datapoint(
    name: str = "listing",
    items_field: str = "items",
    total_field: str | None = "total",
    has_more_field: str | None = "hasMore",
    next_offset_field: str | None = "nextOffset",
) -> DatapointDef:
    pagination: dict = {"style": "offset_limit", "items_field": items_field}
    if total_field:
        pagination["total_field"] = total_field
    if has_more_field:
        pagination["has_more_field"] = has_more_field
    if next_offset_field:
        pagination["next_offset_field"] = next_offset_field
    return DatapointDef(
        name=name,
        description="",
        pattern="paginated",
        endpoints=[],
        pagination=pagination,
    )


def _make_endpoint(status: int = 200) -> EndpointDef:
    return EndpointDef(method="GET", path="/ratesync/listings", step=None, response={"status": status})


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
    handler = make_paginated_handler("ratesync", datapoint, endpoint, store, default_limit=10)
    app.add_api_route("/ratesync/listings", handler, methods=["GET"])
    return TestClient(app, raise_server_exceptions=True), store


def _ten_items() -> list:
    return [{"id": i, "name": f"item-{i}"} for i in range(10)]


# ---------------------------------------------------------------------------
# Handler construction
# ---------------------------------------------------------------------------


def test_handler_is_callable(store):
    handler = make_paginated_handler("ratesync", _make_datapoint(), _make_endpoint(), store, 10)
    assert callable(handler)


def test_handler_has_unique_name(store):
    handler = make_paginated_handler("ratesync", _make_datapoint(), _make_endpoint(), store, 10)
    assert "paginated" in handler.__name__
    assert "ratesync" in handler.__name__


# ---------------------------------------------------------------------------
# No payload
# ---------------------------------------------------------------------------


def test_returns_404_when_no_global_payload(client):
    c, _ = client
    r = c.get("/ratesync/listings")
    assert r.status_code == 404
    assert "global payload" in r.json()["detail"]


def test_returns_404_when_session_payload_missing(client):
    c, _ = client
    r = c.get("/ratesync/listings", headers={"X-Imnot-Session": "nonexistent"})
    assert r.status_code == 404
    assert "nonexistent" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Slicing
# ---------------------------------------------------------------------------


def test_slice_offset_0_limit_3(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=0&limit=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["id"] == 0
    assert body["total"] == 10
    assert body["hasMore"] is True
    assert body["nextOffset"] == 3


def test_slice_mid_dataset(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=5&limit=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["id"] == 5
    assert body["total"] == 10
    assert body["hasMore"] is True
    assert body["nextOffset"] == 8


def test_out_of_bounds_offset(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=20&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 10
    assert body["hasMore"] is False
    assert body["nextOffset"] is None


def test_last_page_has_more_false(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=8&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["hasMore"] is False
    assert body["nextOffset"] is None


# ---------------------------------------------------------------------------
# Default limit
# ---------------------------------------------------------------------------


def test_default_limit_applied_when_no_limit_param(store):
    app = FastAPI()
    datapoint = _make_datapoint()
    endpoint = _make_endpoint()
    handler = make_paginated_handler("ratesync", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/ratesync/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3


def test_negative_offset_treated_as_zero(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=-5&limit=3")
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["id"] == 0


def test_zero_limit_falls_back_to_default(store):
    app = FastAPI()
    datapoint = _make_datapoint()
    endpoint = _make_endpoint()
    handler = make_paginated_handler("ratesync", datapoint, endpoint, store, default_limit=4)
    app.add_api_route("/ratesync/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?limit=0")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 4


# ---------------------------------------------------------------------------
# Optional fields absent from YAML
# ---------------------------------------------------------------------------


def test_total_field_absent_not_in_response(store):
    app = FastAPI()
    dp = _make_datapoint(total_field=None)
    handler = make_paginated_handler("ratesync", dp, _make_endpoint(), store, 10)
    app.add_api_route("/ratesync/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("ratesync", "listing", _ten_items())
    body = c.get("/ratesync/listings?offset=0&limit=3").json()
    assert "total" not in body
    assert "items" in body


def test_has_more_field_absent_not_in_response(store):
    app = FastAPI()
    dp = _make_datapoint(has_more_field=None)
    handler = make_paginated_handler("ratesync", dp, _make_endpoint(), store, 10)
    app.add_api_route("/ratesync/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("ratesync", "listing", _ten_items())
    body = c.get("/ratesync/listings?offset=0&limit=3").json()
    assert "hasMore" not in body


def test_next_offset_field_absent_not_in_response(store):
    app = FastAPI()
    dp = _make_datapoint(next_offset_field=None)
    handler = make_paginated_handler("ratesync", dp, _make_endpoint(), store, 10)
    app.add_api_route("/ratesync/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("ratesync", "listing", _ten_items())
    body = c.get("/ratesync/listings?offset=0&limit=3").json()
    assert "nextOffset" not in body


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


def test_session_isolation(client):
    c, store = client
    items_alice = [{"user": "alice", "id": i} for i in range(5)]
    items_bob = [{"user": "bob", "id": i} for i in range(8)]
    s_alice = store.store_session_payload("ratesync", "listing", items_alice)
    s_bob = store.store_session_payload("ratesync", "listing", items_bob)

    r_alice = c.get("/ratesync/listings?offset=0&limit=10", headers={"X-Imnot-Session": s_alice})
    r_bob = c.get("/ratesync/listings?offset=0&limit=10", headers={"X-Imnot-Session": s_bob})

    assert r_alice.json()["total"] == 5
    assert r_bob.json()["total"] == 8
    assert r_alice.json()["items"][0]["user"] == "alice"
    assert r_bob.json()["items"][0]["user"] == "bob"


def test_session_does_not_leak_to_global(client):
    c, store = client
    store.store_session_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Payload not a list
# ---------------------------------------------------------------------------


def test_payload_not_list_returns_422(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", {"not": "a list"})
    r = c.get("/ratesync/listings")
    assert r.status_code == 422
    assert "JSON array" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Invalid query param values (non-numeric offset / limit)
# ---------------------------------------------------------------------------


def test_non_numeric_offset_treated_as_zero(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=abc&limit=3")
    assert r.status_code == 200
    assert r.json()["items"] == _ten_items()[:3]


def test_non_numeric_limit_uses_default(client):
    c, store = client
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=0&limit=bad")
    assert r.status_code == 200
    assert len(r.json()["items"]) == len(_ten_items())


# ---------------------------------------------------------------------------
# Custom status code
# ---------------------------------------------------------------------------


def test_custom_status_code(store):
    app = FastAPI()
    endpoint = _make_endpoint(status=206)
    handler = make_paginated_handler("ratesync", _make_datapoint(), endpoint, store, 10)
    app.add_api_route("/ratesync/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("ratesync", "listing", _ten_items())
    r = c.get("/ratesync/listings?offset=0&limit=3")
    assert r.status_code == 206
