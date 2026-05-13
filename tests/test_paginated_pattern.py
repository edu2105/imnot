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


def _make_cursor_datapoint(
    name: str = "listing",
    cursor_field: str = "nextCursor",
    cursor_ttl_seconds: int = 3600,
    total_field: str | None = None,
    has_more_field: str | None = None,
) -> DatapointDef:
    pagination: dict = {
        "style": "cursor",
        "items_field": "items",
        "cursor_field": cursor_field,
        "cursor_ttl_seconds": cursor_ttl_seconds,
    }
    if total_field:
        pagination["total_field"] = total_field
    if has_more_field:
        pagination["has_more_field"] = has_more_field
    return DatapointDef(name=name, description="", pattern="paginated", endpoints=[], pagination=pagination)


def _make_page_number_datapoint(
    name: str = "listing",
    page_param: str = "page",
    size_param: str = "size",
    total_field: str | None = None,
    has_more_field: str | None = None,
) -> DatapointDef:
    pagination: dict = {
        "style": "page_number",
        "items_field": "items",
        "page_param": page_param,
        "size_param": size_param,
    }
    if total_field:
        pagination["total_field"] = total_field
    if has_more_field:
        pagination["has_more_field"] = has_more_field
    return DatapointDef(name=name, description="", pattern="paginated", endpoints=[], pagination=pagination)


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


# ---------------------------------------------------------------------------
# Cursor handler
# ---------------------------------------------------------------------------


@pytest.fixture
def cursor_client(store):
    app = FastAPI()
    datapoint = _make_cursor_datapoint(has_more_field="hasMore", total_field="total")
    endpoint = _make_endpoint()
    handler = make_paginated_handler("bookingco", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/bookingco/listings", handler, methods=["GET"])
    return TestClient(app, raise_server_exceptions=True), store


def test_cursor_first_request_returns_cursor(cursor_client):
    c, store = cursor_client
    store.store_global_payload("bookingco", "listing", _ten_items())
    r = c.get("/bookingco/listings?limit=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["id"] == 0
    assert body["nextCursor"] is not None
    assert body["hasMore"] is True
    assert body["total"] == 10


def test_cursor_second_request_continues(cursor_client):
    c, store = cursor_client
    store.store_global_payload("bookingco", "listing", _ten_items())
    r1 = c.get("/bookingco/listings?limit=3")
    cursor = r1.json()["nextCursor"]
    r2 = c.get(f"/bookingco/listings?limit=3&cursor={cursor}")
    assert r2.status_code == 200
    body = r2.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["id"] == 3


def test_cursor_last_page_returns_null_cursor(cursor_client):
    c, store = cursor_client
    store.store_global_payload("bookingco", "listing", _ten_items())
    r1 = c.get("/bookingco/listings?limit=9")
    assert r1.json()["hasMore"] is True
    cursor = r1.json()["nextCursor"]
    r2 = c.get(f"/bookingco/listings?limit=9&cursor={cursor}")
    assert r2.status_code == 200
    body = r2.json()
    assert len(body["items"]) == 1
    assert body["nextCursor"] is None
    assert body["hasMore"] is False


def test_cursor_expired_returns_400(cursor_client):
    c, store = cursor_client
    store.store_global_payload("bookingco", "listing", _ten_items())
    r = c.get("/bookingco/listings?cursor=00000000-0000-0000-0000-000000000000")
    assert r.status_code == 400
    assert "Cursor expired or not found" in r.json()["detail"]


def test_cursor_no_payload_returns_404(cursor_client):
    c, _ = cursor_client
    r = c.get("/bookingco/listings")
    assert r.status_code == 404


def test_cursor_session_isolation(store):
    app = FastAPI()
    datapoint = _make_cursor_datapoint()
    endpoint = _make_endpoint()
    handler = make_paginated_handler("bookingco", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/bookingco/listings", handler, methods=["GET"])
    c = TestClient(app)

    items_alice = [{"user": "alice", "id": i} for i in range(6)]
    items_bob = [{"user": "bob", "id": i} for i in range(9)]
    s_alice = store.store_session_payload("bookingco", "listing", items_alice)
    s_bob = store.store_session_payload("bookingco", "listing", items_bob)

    r_alice = c.get("/bookingco/listings?limit=3", headers={"X-Imnot-Session": s_alice})
    r_bob = c.get("/bookingco/listings?limit=3", headers={"X-Imnot-Session": s_bob})

    assert r_alice.json()["items"][0]["user"] == "alice"
    assert r_bob.json()["items"][0]["user"] == "bob"

    c_alice = r_alice.json()["nextCursor"]
    c_bob = r_bob.json()["nextCursor"]
    assert c_alice != c_bob

    r_alice2 = c.get(f"/bookingco/listings?limit=3&cursor={c_alice}", headers={"X-Imnot-Session": s_alice})
    assert r_alice2.json()["items"][0]["user"] == "alice"
    assert r_alice2.json()["items"][0]["id"] == 3


def test_cursor_ttl_zero_never_expires(store):
    app = FastAPI()
    datapoint = _make_cursor_datapoint(cursor_ttl_seconds=0)
    endpoint = _make_endpoint()
    handler = make_paginated_handler("bookingco", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/bookingco/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("bookingco", "listing", _ten_items())
    r1 = c.get("/bookingco/listings?limit=3")
    cursor = r1.json()["nextCursor"]
    assert store.resolve_cursor(cursor) == 3


def test_cursor_optional_fields_absent(store):
    app = FastAPI()
    datapoint = _make_cursor_datapoint()
    endpoint = _make_endpoint()
    handler = make_paginated_handler("bookingco", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/bookingco/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("bookingco", "listing", _ten_items())
    body = c.get("/bookingco/listings?limit=3").json()
    assert "total" not in body
    assert "hasMore" not in body
    assert "nextCursor" in body


def test_cursor_handler_name(store):
    handler = make_paginated_handler("bookingco", _make_cursor_datapoint(), _make_endpoint(), store, 10)
    assert "cursor" in handler.__name__
    assert "bookingco" in handler.__name__


def test_cursor_payload_not_list_returns_422(cursor_client):
    c, store = cursor_client
    store.store_global_payload("bookingco", "listing", {"not": "a list"})
    r = c.get("/bookingco/listings")
    assert r.status_code == 422
    assert "JSON array" in r.json()["detail"]


def test_cursor_non_numeric_limit_uses_default(cursor_client):
    c, store = cursor_client
    store.store_global_payload("bookingco", "listing", _ten_items())
    r = c.get("/bookingco/listings?limit=bad")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3  # default_limit=3


def test_cursor_limit_zero_uses_default(cursor_client):
    c, store = cursor_client
    store.store_global_payload("bookingco", "listing", _ten_items())
    r = c.get("/bookingco/listings?limit=0")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3  # default_limit=3


# ---------------------------------------------------------------------------
# Page-number handler
# ---------------------------------------------------------------------------


@pytest.fixture
def page_client(store):
    app = FastAPI()
    datapoint = _make_page_number_datapoint(total_field="total", has_more_field="hasMore")
    endpoint = _make_endpoint()
    handler = make_paginated_handler("staylink", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/staylink/listings", handler, methods=["GET"])
    return TestClient(app, raise_server_exceptions=True), store


def test_page_number_page_1(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=1&size=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["id"] == 0
    assert body["total"] == 10
    assert body["hasMore"] is True


def test_page_number_page_2(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=2&size=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["id"] == 3
    assert body["hasMore"] is True


def test_page_number_last_page(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=4&size=3")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == 9
    assert body["hasMore"] is False


def test_page_number_out_of_range(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=999&size=3")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["hasMore"] is False


def test_page_number_default_page_1(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?size=3")
    assert r.status_code == 200
    assert r.json()["items"][0]["id"] == 0


def test_page_number_page_0_clamped_to_1(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=0&size=3")
    assert r.status_code == 200
    assert r.json()["items"][0]["id"] == 0


def test_page_number_custom_params(store):
    app = FastAPI()
    datapoint = _make_page_number_datapoint(page_param="pageNum", size_param="perPage")
    endpoint = _make_endpoint()
    handler = make_paginated_handler("staylink", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/staylink/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?pageNum=2&perPage=4")
    assert r.status_code == 200
    body = r.json()
    assert body["items"][0]["id"] == 4


def test_page_number_no_payload_404(page_client):
    c, _ = page_client
    r = c.get("/staylink/listings?page=1")
    assert r.status_code == 404


def test_page_number_payload_not_list_422(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", {"not": "a list"})
    r = c.get("/staylink/listings?page=1")
    assert r.status_code == 422


def test_page_number_next_offset_field_ignored(store):
    pagination = {
        "style": "page_number",
        "items_field": "items",
        "next_offset_field": "nextOffset",
    }
    dp = DatapointDef(name="listing", description="", pattern="paginated", endpoints=[], pagination=pagination)
    app = FastAPI()
    handler = make_paginated_handler("staylink", dp, _make_endpoint(), store, default_limit=5)
    app.add_api_route("/staylink/listings", handler, methods=["GET"])
    c = TestClient(app)
    store.store_global_payload("staylink", "listing", _ten_items())
    body = c.get("/staylink/listings?page=1&size=5").json()
    assert "nextOffset" not in body


def test_page_number_handler_name(store):
    handler = make_paginated_handler("staylink", _make_page_number_datapoint(), _make_endpoint(), store, 10)
    assert "page" in handler.__name__
    assert "staylink" in handler.__name__


def test_page_number_non_numeric_page_uses_default(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=abc&size=3")
    assert r.status_code == 200
    assert r.json()["items"][0]["id"] == 0  # clamped to page 1


def test_page_number_non_numeric_size_uses_default(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=1&size=bad")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3  # default_limit=3


def test_page_number_size_zero_uses_default(page_client):
    c, store = page_client
    store.store_global_payload("staylink", "listing", _ten_items())
    r = c.get("/staylink/listings?page=1&size=0")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 3  # default_limit=3


def test_page_number_session_isolation(store):
    app = FastAPI()
    datapoint = _make_page_number_datapoint()
    endpoint = _make_endpoint()
    handler = make_paginated_handler("staylink", datapoint, endpoint, store, default_limit=3)
    app.add_api_route("/staylink/listings", handler, methods=["GET"])
    c = TestClient(app)

    items_alice = [{"user": "alice", "id": i} for i in range(6)]
    items_bob = [{"user": "bob", "id": i} for i in range(9)]
    s_alice = store.store_session_payload("staylink", "listing", items_alice)
    s_bob = store.store_session_payload("staylink", "listing", items_bob)

    r_alice = c.get("/staylink/listings?page=1&size=3", headers={"X-Imnot-Session": s_alice})
    r_bob = c.get("/staylink/listings?page=1&size=3", headers={"X-Imnot-Session": s_bob})

    assert r_alice.json()["items"][0]["user"] == "alice"
    assert r_bob.json()["items"][0]["user"] == "bob"
