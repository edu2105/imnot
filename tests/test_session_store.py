"""Tests for the session store."""

import pytest

from imnot.engine.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Global payloads
# ---------------------------------------------------------------------------


def test_store_and_resolve_global_payload(store):
    payload = {"reservationId": "abc123", "status": "CONFIRMED"}
    store.store_global_payload("staylink", "reservation", payload)

    result = store.resolve_payload("staylink", "reservation", session_id=None)
    assert result == payload


def test_global_payload_last_write_wins(store):
    store.store_global_payload("staylink", "reservation", {"v": 1})
    store.store_global_payload("staylink", "reservation", {"v": 2})

    result = store.resolve_payload("staylink", "reservation", session_id=None)
    assert result == {"v": 2}


def test_global_payload_not_found_returns_none(store):
    result = store.resolve_payload("staylink", "reservation", session_id=None)
    assert result is None


# ---------------------------------------------------------------------------
# Session payloads
# ---------------------------------------------------------------------------


def test_store_and_resolve_session_payload(store):
    payload = {"reservationId": "xyz", "status": "PENDING"}
    session_id = store.store_session_payload("staylink", "reservation", payload)

    assert isinstance(session_id, str) and len(session_id) == 36  # UUID

    result = store.resolve_payload("staylink", "reservation", session_id=session_id)
    assert result == payload


def test_session_payload_not_found_returns_none(store):
    result = store.resolve_payload("staylink", "reservation", session_id="nonexistent")
    assert result is None


def test_sessions_are_isolated(store):
    s1 = store.store_session_payload("staylink", "reservation", {"user": "alice"})
    s2 = store.store_session_payload("staylink", "reservation", {"user": "bob"})

    assert store.resolve_payload("staylink", "reservation", s1) == {"user": "alice"}
    assert store.resolve_payload("staylink", "reservation", s2) == {"user": "bob"}


def test_session_takes_priority_over_global(store):
    store.store_global_payload("staylink", "reservation", {"source": "global"})
    session_id = store.store_session_payload("staylink", "reservation", {"source": "session"})

    result = store.resolve_payload("staylink", "reservation", session_id=session_id)
    assert result == {"source": "session"}


# ---------------------------------------------------------------------------
# Async request tracking
# ---------------------------------------------------------------------------


def test_register_and_get_async_request(store):
    async_uuid = store.register_async_request("staylink", "reservation", session_id=None)

    assert isinstance(async_uuid, str) and len(async_uuid) == 36

    row = store.get_async_request(async_uuid)
    assert row is not None
    assert row["partner"] == "staylink"
    assert row["datapoint"] == "reservation"
    assert row["session_id"] is None


def test_async_request_with_session(store):
    session_id = store.store_session_payload("staylink", "reservation", {"x": 1})
    async_uuid = store.register_async_request("staylink", "reservation", session_id=session_id)

    row = store.get_async_request(async_uuid)
    assert row["session_id"] == session_id


def test_async_request_not_found(store):
    assert store.get_async_request("nonexistent-uuid") is None


# ---------------------------------------------------------------------------
# Admin: get global payload
# ---------------------------------------------------------------------------


def test_get_global_payload(store):
    store.store_global_payload("staylink", "reservation", {"reservationId": "R1"})
    result = store.get_global_payload("staylink", "reservation")
    assert result is not None
    assert result["payload"] == {"reservationId": "R1"}
    assert "updated_at" in result


def test_get_global_payload_not_found(store):
    assert store.get_global_payload("staylink", "reservation") is None


def test_get_global_payload_reflects_latest_write(store):
    store.store_global_payload("staylink", "reservation", {"v": 1})
    store.store_global_payload("staylink", "reservation", {"v": 2})
    result = store.get_global_payload("staylink", "reservation")
    assert result["payload"] == {"v": 2}


# ---------------------------------------------------------------------------
# Admin: get session payload
# ---------------------------------------------------------------------------


def test_get_session_payload(store):
    session_id = store.store_session_payload("staylink", "reservation", {"reservationId": "S1"})
    result = store.get_session_payload(session_id)
    assert result is not None
    assert result["payload"] == {"reservationId": "S1"}
    assert result["session_id"] == session_id
    assert result["partner"] == "staylink"
    assert result["datapoint"] == "reservation"
    assert "created_at" in result


def test_get_session_payload_not_found(store):
    assert store.get_session_payload("nonexistent-id") is None


# ---------------------------------------------------------------------------
# Admin: list sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty(store):
    assert store.list_sessions() == []


def test_list_sessions(store):
    store.store_session_payload("staylink", "reservation", {"a": 1})
    store.store_session_payload("staylink", "reservation", {"b": 2})

    sessions = store.list_sessions()
    assert len(sessions) == 2
    assert all("session_id" in s for s in sessions)
    assert all("created_at" in s for s in sessions)
