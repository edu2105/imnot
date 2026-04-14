"""Tests for the async pattern handler."""

import json
from pathlib import Path

import pytest
from fastapi import Request

from imnot.engine.patterns.async_ import make_async_handlers
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


def _make_datapoint(endpoints: list[EndpointDef]) -> DatapointDef:
    return DatapointDef(
        name="job",
        description="",
        pattern="async",
        endpoints=endpoints,
    )


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "headers": headers or []})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_one_handler_per_step(store):
    endpoints = [
        EndpointDef(method="POST", path="/jobs", step=1,
                    response={"status": 202, "generates_id": True,
                              "id_header": "Location", "id_header_value": "/jobs/{id}"}),
        EndpointDef(method="GET", path="/jobs/{id}", step=2,
                    response={"status": 200, "returns_payload": True}),
    ]
    handlers = make_async_handlers("partner", _make_datapoint(endpoints), store)
    assert set(handlers.keys()) == {1, 2}
    assert all(callable(h) for h in handlers.values())


def test_handler_names_are_unique(store):
    endpoints = [
        EndpointDef(method="POST", path="/jobs", step=1,
                    response={"status": 202, "generates_id": True,
                              "id_header": "Location", "id_header_value": "/jobs/{id}"}),
        EndpointDef(method="GET", path="/jobs/{id}", step=2,
                    response={"status": 200, "returns_payload": True}),
    ]
    handlers = make_async_handlers("partner", _make_datapoint(endpoints), store)
    names = [h.__name__ for h in handlers.values()]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Submit handler — id_header delivery
# ---------------------------------------------------------------------------


@pytest.fixture
def header_submit_handler(store):
    ep = EndpointDef(
        method="POST", path="/jobs", step=1,
        response={
            "status": 202,
            "generates_id": True,
            "id_header": "Location",
            "id_header_value": "/jobs/{id}",
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[1]


@pytest.mark.asyncio
async def test_submit_header_returns_configured_status(header_submit_handler):
    response = await header_submit_handler(_request())
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_submit_header_injects_uuid_into_header(header_submit_handler):
    response = await header_submit_handler(_request())
    location = response.headers.get("Location")
    assert location is not None
    assert location.startswith("/jobs/")
    uuid_part = location.split("/")[-1]
    assert len(uuid_part) == 36  # UUID


@pytest.mark.asyncio
async def test_submit_header_persists_uuid(header_submit_handler, store):
    response = await header_submit_handler(_request())
    uuid = response.headers["Location"].split("/")[-1]
    row = store.get_async_request(uuid)
    assert row is not None
    assert row["partner"] == "partner"
    assert row["datapoint"] == "job"
    assert row["session_id"] is None


@pytest.mark.asyncio
async def test_submit_header_persists_session_id(header_submit_handler, store):
    headers = [(b"x-imnot-session", b"test-session-abc")]
    response = await header_submit_handler(_request(headers))
    uuid = response.headers["Location"].split("/")[-1]
    row = store.get_async_request(uuid)
    assert row["session_id"] == "test-session-abc"


# ---------------------------------------------------------------------------
# Submit handler — id_body_field delivery
# ---------------------------------------------------------------------------


@pytest.fixture
def body_submit_handler(store):
    ep = EndpointDef(
        method="POST", path="/jobs", step=1,
        response={
            "status": 200,
            "generates_id": True,
            "id_body_field": "JobReferenceID",
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[1]


@pytest.mark.asyncio
async def test_submit_body_returns_configured_status(body_submit_handler):
    response = await body_submit_handler(_request())
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_submit_body_injects_uuid_into_body(body_submit_handler):
    response = await body_submit_handler(_request())
    body = json.loads(response.body)
    assert "JobReferenceID" in body
    assert len(body["JobReferenceID"]) == 36  # UUID


@pytest.mark.asyncio
async def test_submit_body_persists_uuid(body_submit_handler, store):
    response = await body_submit_handler(_request())
    uuid = json.loads(response.body)["JobReferenceID"]
    row = store.get_async_request(uuid)
    assert row is not None
    assert row["partner"] == "partner"
    assert row["datapoint"] == "job"


@pytest.mark.asyncio
async def test_submit_body_merges_static_body_fields(store):
    ep = EndpointDef(
        method="POST", path="/jobs", step=1,
        response={
            "status": 200,
            "generates_id": True,
            "id_body_field": "JobReferenceID",
            "body": {"extraField": "extraValue"},
        },
    )
    handler = make_async_handlers("partner", _make_datapoint([ep]), store)[1]
    response = await handler(_request())
    body = json.loads(response.body)
    assert body["extraField"] == "extraValue"
    assert len(body["JobReferenceID"]) == 36


# ---------------------------------------------------------------------------
# Static handler
# ---------------------------------------------------------------------------


@pytest.fixture
def static_handler_headers_only(store):
    ep = EndpointDef(
        method="HEAD", path="/jobs/{id}", step=2,
        response={
            "status": 201,
            "headers": {"Status": "COMPLETED"},
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[2]


@pytest.fixture
def static_handler_with_body(store):
    ep = EndpointDef(
        method="GET", path="/jobs/{id}/status", step=2,
        response={
            "status": 200,
            "body": {"status": "COMPLETED"},
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[2]


@pytest.mark.asyncio
async def test_static_returns_configured_status(static_handler_headers_only):
    response = await static_handler_headers_only(_request())
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_static_returns_configured_headers(static_handler_headers_only):
    response = await static_handler_headers_only(_request())
    assert response.headers.get("Status") == "COMPLETED"


@pytest.mark.asyncio
async def test_static_with_body_returns_body(static_handler_with_body):
    response = await static_handler_with_body(_request())
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body == {"status": "COMPLETED"}


# ---------------------------------------------------------------------------
# Fetch handler
# ---------------------------------------------------------------------------


@pytest.fixture
def fetch_handler(store):
    ep = EndpointDef(
        method="GET", path="/jobs/{id}", step=3,
        response={"status": 200, "returns_payload": True},
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[3]


def _request_with_id(async_uuid: str, session_id: str | None = None) -> Request:
    headers = []
    if session_id:
        headers.append((b"x-imnot-session", session_id.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "path_params": {"id": async_uuid},
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_fetch_unknown_uuid_returns_404(fetch_handler):
    response = await fetch_handler(_request_with_id("nonexistent-uuid"))
    assert response.status_code == 404
    assert "nonexistent-uuid" in json.loads(response.body)["detail"]


@pytest.mark.asyncio
async def test_fetch_returns_global_payload(fetch_handler, store):
    async_uuid = store.register_async_request("partner", "job", session_id=None)
    store.store_global_payload("partner", "job", {"result": "ok"})

    response = await fetch_handler(_request_with_id(async_uuid))
    assert response.status_code == 200
    assert json.loads(response.body) == {"result": "ok"}


@pytest.mark.asyncio
async def test_fetch_returns_session_payload(fetch_handler, store):
    session_id = store.store_session_payload("partner", "job", {"result": "session-ok"})
    async_uuid = store.register_async_request("partner", "job", session_id=session_id)

    response = await fetch_handler(_request_with_id(async_uuid, session_id=session_id))
    assert response.status_code == 200
    assert json.loads(response.body) == {"result": "session-ok"}


@pytest.mark.asyncio
async def test_fetch_no_payload_returns_404(fetch_handler, store):
    async_uuid = store.register_async_request("partner", "job", session_id=None)
    response = await fetch_handler(_request_with_id(async_uuid))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_fetch_session_header_but_no_session_payload_returns_404(fetch_handler, store):
    store.store_global_payload("partner", "job", {"source": "global"})
    async_uuid = store.register_async_request("partner", "job", session_id=None)

    response = await fetch_handler(_request_with_id(async_uuid, session_id="ghost-session"))
    assert response.status_code == 404
