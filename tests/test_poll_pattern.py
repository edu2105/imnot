"""Tests for the poll pattern handler."""

from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from mirage.engine.patterns.poll import make_poll_handlers
from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import load_partners


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
def reservation_datapoint():
    partners = load_partners(Path(__file__).parent.parent / "partners")
    staylink = next(p for p in partners if p.partner == "staylink")
    return staylink, next(dp for dp in staylink.datapoints if dp.name == "reservation")


@pytest.fixture
def handlers(reservation_datapoint, store):
    staylink, reservation = reservation_datapoint
    return make_poll_handlers(
        partner=staylink.partner,
        datapoint=reservation,
        store=store,
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_returns_three_handlers(handlers):
    assert set(handlers.keys()) == {1, 2, 3}
    assert all(callable(h) for h in handlers.values())


def test_handler_names_are_unique(handlers):
    names = [h.__name__ for h in handlers.values()]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Step 1 — POST: register poll request, return 202 + Location
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step1_returns_202_and_location(handlers, store):
    scope = {"type": "http", "headers": []}
    request = Request(scope)

    response = await handlers[1](request)

    assert response.status_code == 202
    assert "Location" in response.headers
    assert "/staylink/reservations/" in response.headers["Location"]


@pytest.mark.asyncio
async def test_step1_registers_poll_request(handlers, store):
    scope = {"type": "http", "headers": []}
    request = Request(scope)

    response = await handlers[1](request)

    uuid = response.headers["Location"].split("/")[-1]
    row = store.get_poll_request(uuid)
    assert row is not None
    assert row["partner"] == "staylink"
    assert row["datapoint"] == "reservation"
    assert row["session_id"] is None


@pytest.mark.asyncio
async def test_step1_stores_session_id_from_header(handlers, store):
    headers = [(b"x-mirage-session", b"test-session-123")]
    scope = {"type": "http", "headers": headers}
    request = Request(scope)

    response = await handlers[1](request)

    uuid = response.headers["Location"].split("/")[-1]
    row = store.get_poll_request(uuid)
    assert row["session_id"] == "test-session-123"


# ---------------------------------------------------------------------------
# Step 2 — HEAD: return 201 + Status header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step2_returns_201(handlers):
    response = await handlers[2](uuid="any-uuid")
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_step2_returns_status_header(handlers):
    response = await handlers[2](uuid="any-uuid")
    assert response.headers.get("Status") == "COMPLETED"


# ---------------------------------------------------------------------------
# Step 3 — GET: resolve and return payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step3_unknown_uuid_returns_404(handlers):
    scope = {"type": "http", "headers": []}
    request = Request(scope)

    response = await handlers[3](uuid="nonexistent-uuid", request=request)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_step3_returns_global_payload(handlers, store):
    # Register a poll request first
    scope = {"type": "http", "headers": []}
    step1_response = await handlers[1](Request(scope))
    uuid = step1_response.headers["Location"].split("/")[-1]

    # Upload global payload
    store.store_global_payload("staylink", "reservation", {"reservationId": "RES001"})

    # Fetch via step 3
    response = await handlers[3](uuid=uuid, request=Request(scope))
    assert response.status_code == 200

    import json
    body = json.loads(response.body)
    assert body == {"reservationId": "RES001"}


@pytest.mark.asyncio
async def test_step3_returns_session_payload(handlers, store):
    # Upload session payload and get session_id
    session_id = store.store_session_payload("staylink", "reservation", {"reservationId": "SES001"})

    # Step 1 with session header
    headers = [(b"x-mirage-session", session_id.encode())]
    step1_response = await handlers[1](Request({"type": "http", "headers": headers}))
    uuid = step1_response.headers["Location"].split("/")[-1]

    # Step 3 with session header
    response = await handlers[3](
        uuid=uuid,
        request=Request({"type": "http", "headers": headers}),
    )
    assert response.status_code == 200

    import json
    assert json.loads(response.body) == {"reservationId": "SES001"}


@pytest.mark.asyncio
async def test_step3_no_payload_returns_404(handlers, store):
    scope = {"type": "http", "headers": []}
    step1_response = await handlers[1](Request(scope))
    uuid = step1_response.headers["Location"].split("/")[-1]

    # No payload uploaded
    response = await handlers[3](uuid=uuid, request=Request(scope))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_step3_session_header_but_no_session_payload_returns_404(handlers, store):
    store.store_global_payload("staylink", "reservation", {"source": "global"})

    scope = {"type": "http", "headers": []}
    step1_response = await handlers[1](Request(scope))
    uuid = step1_response.headers["Location"].split("/")[-1]

    # Has session header but no session payload was uploaded
    headers = [(b"x-mirage-session", b"ghost-session")]
    response = await handlers[3](
        uuid=uuid,
        request=Request({"type": "http", "headers": headers}),
    )
    assert response.status_code == 404
