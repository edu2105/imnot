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
    payload = {"reportId": "RPT-abc123", "status": "DONE"}
    store.store_global_payload("staylink", "report", payload)

    result = store.resolve_payload("staylink", "report", session_id=None)
    assert result == payload


def test_global_payload_last_write_wins(store):
    store.store_global_payload("staylink", "report", {"v": 1})
    store.store_global_payload("staylink", "report", {"v": 2})

    result = store.resolve_payload("staylink", "report", session_id=None)
    assert result == {"v": 2}


def test_global_payload_not_found_returns_none(store):
    result = store.resolve_payload("staylink", "report", session_id=None)
    assert result is None


# ---------------------------------------------------------------------------
# Session payloads
# ---------------------------------------------------------------------------


def test_store_and_resolve_session_payload(store):
    payload = {"reportId": "RPT-xyz", "status": "PENDING"}
    session_id = store.store_session_payload("staylink", "report", payload)

    assert isinstance(session_id, str) and len(session_id) == 36  # UUID

    result = store.resolve_payload("staylink", "report", session_id=session_id)
    assert result == payload


def test_session_payload_not_found_returns_none(store):
    result = store.resolve_payload("staylink", "report", session_id="nonexistent")
    assert result is None


def test_sessions_are_isolated(store):
    s1 = store.store_session_payload("staylink", "report", {"user": "alice"})
    s2 = store.store_session_payload("staylink", "report", {"user": "bob"})

    assert store.resolve_payload("staylink", "report", s1) == {"user": "alice"}
    assert store.resolve_payload("staylink", "report", s2) == {"user": "bob"}


def test_session_takes_priority_over_global(store):
    store.store_global_payload("staylink", "report", {"source": "global"})
    session_id = store.store_session_payload("staylink", "report", {"source": "session"})

    result = store.resolve_payload("staylink", "report", session_id=session_id)
    assert result == {"source": "session"}


# ---------------------------------------------------------------------------
# Async request tracking
# ---------------------------------------------------------------------------


def test_register_and_get_async_request(store):
    async_uuid = store.register_async_request("staylink", "report", session_id=None)

    assert isinstance(async_uuid, str) and len(async_uuid) == 36

    row = store.get_async_request(async_uuid)
    assert row is not None
    assert row["partner"] == "staylink"
    assert row["datapoint"] == "report"
    assert row["session_id"] is None


def test_async_request_with_session(store):
    session_id = store.store_session_payload("staylink", "report", {"x": 1})
    async_uuid = store.register_async_request("staylink", "report", session_id=session_id)

    row = store.get_async_request(async_uuid)
    assert row["session_id"] == session_id


def test_async_request_not_found(store):
    assert store.get_async_request("nonexistent-uuid") is None


# ---------------------------------------------------------------------------
# Admin: get global payload
# ---------------------------------------------------------------------------


def test_get_global_payload(store):
    store.store_global_payload("staylink", "report", {"reportId": "RPT-R1"})
    result = store.get_global_payload("staylink", "report")
    assert result is not None
    assert result["payload"] == {"reportId": "RPT-R1"}
    assert "updated_at" in result


def test_get_global_payload_not_found(store):
    assert store.get_global_payload("staylink", "report") is None


def test_get_global_payload_reflects_latest_write(store):
    store.store_global_payload("staylink", "report", {"v": 1})
    store.store_global_payload("staylink", "report", {"v": 2})
    result = store.get_global_payload("staylink", "report")
    assert result["payload"] == {"v": 2}


# ---------------------------------------------------------------------------
# Admin: get session payload
# ---------------------------------------------------------------------------


def test_get_session_payload(store):
    session_id = store.store_session_payload("staylink", "report", {"reportId": "RPT-S1"})
    result = store.get_session_payload(session_id)
    assert result is not None
    assert result["payload"] == {"reportId": "RPT-S1"}
    assert result["session_id"] == session_id
    assert result["partner"] == "staylink"
    assert result["datapoint"] == "report"
    assert "created_at" in result


def test_get_session_payload_not_found(store):
    assert store.get_session_payload("nonexistent-id") is None


# ---------------------------------------------------------------------------
# Admin: list sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty(store):
    assert store.list_sessions() == []


def test_list_sessions(store):
    store.store_session_payload("staylink", "report", {"a": 1})
    store.store_session_payload("staylink", "report", {"b": 2})

    sessions = store.list_sessions()
    assert len(sessions) == 2
    assert all("session_id" in s for s in sessions)
    assert all("created_at" in s for s in sessions)


# ---------------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------------


def test_delete_session_found(store):
    session_id = store.store_session_payload("staylink", "report", {"x": 1})
    result = store.delete_session(session_id)
    assert result is True
    assert store.get_session_payload(session_id) is None


def test_delete_session_not_found(store):
    result = store.delete_session("nonexistent-id")
    assert result is False


# ---------------------------------------------------------------------------
# last_used tracking
# ---------------------------------------------------------------------------


def test_last_used_initially_null(store):
    store.store_session_payload("staylink", "report", {"v": 1})
    sessions = store.list_sessions()
    assert sessions[0]["last_used"] is None


def test_last_used_updated_after_resolve(store):
    session_id = store.store_session_payload("staylink", "report", {"v": 1})
    store.resolve_payload("staylink", "report", session_id=session_id)
    sessions = store.list_sessions()
    assert sessions[0]["last_used"] is not None
    assert sessions[0]["last_used"].startswith("20")


def test_last_used_not_updated_for_global(store):
    store.store_global_payload("staylink", "report", {"global": True})
    session_id = store.store_session_payload("staylink", "report", {"session": True})
    store.resolve_payload("staylink", "report", session_id=None)
    sessions = store.list_sessions()
    assert sessions[0]["last_used"] is None
    assert sessions[0]["session_id"] == session_id


# ---------------------------------------------------------------------------
# Migration guard
# ---------------------------------------------------------------------------


def test_init_migration_guard_idempotent(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    # Calling init() again must not raise even though last_used column already exists
    s.init()
    s.close()


def test_init_migrates_last_used_column(tmp_path):
    """init() adds last_used to an existing sessions table that predates the column."""
    import sqlite3 as _sqlite3

    db_path = tmp_path / "legacy.db"
    conn = _sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            session_id  TEXT PRIMARY KEY,
            partner     TEXT NOT NULL,
            datapoint   TEXT NOT NULL,
            payload     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        """
    )
    conn.close()

    s = SessionStore(db_path=db_path)
    s.init()
    s.store_session_payload("staylink", "report", {"v": 1})
    sessions = s.list_sessions()
    assert sessions[0]["last_used"] is None
    s.close()


# ---------------------------------------------------------------------------
# Cursor store / resolve / expire
# ---------------------------------------------------------------------------


def test_store_cursor_returns_id(store):
    cursor_id = store.store_cursor("ratesync", "listing", None, offset=10)
    assert isinstance(cursor_id, str) and len(cursor_id) == 36


def test_resolve_cursor_returns_offset(store):
    cursor_id = store.store_cursor("ratesync", "listing", None, offset=20)
    result = store.resolve_cursor(cursor_id)
    assert result == 20


def test_resolve_cursor_with_session(store):
    session_id = store.store_session_payload("ratesync", "listing", [])
    cursor_id = store.store_cursor("ratesync", "listing", session_id, offset=5)
    assert store.resolve_cursor(cursor_id) == 5


def test_resolve_cursor_unknown_returns_none(store):
    result = store.resolve_cursor("00000000-0000-0000-0000-000000000000")
    assert result is None


_CURSOR_INSERT_SQL = (
    "INSERT INTO paginated_cursors "
    "(cursor_id, partner, datapoint, session_id, offset_val, created_at, expires_at) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)


def test_resolve_cursor_expired_returns_none(store):
    from datetime import datetime, timedelta, timezone

    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with store._cursor() as cur:
        cur.execute(_CURSOR_INSERT_SQL, ("expired-id", "ratesync", "listing", None, 5, past, past))
    result = store.resolve_cursor("expired-id")
    assert result is None


def test_resolve_cursor_no_ttl_never_expires(store):
    cursor_id = store.store_cursor("ratesync", "listing", None, offset=3, ttl_seconds=0)
    assert store.resolve_cursor(cursor_id) == 3


def test_expire_cursors_deletes_old_rows(store):
    from datetime import datetime, timedelta, timezone

    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(seconds=3600)).isoformat()
    now = datetime.now(timezone.utc).isoformat()

    with store._cursor() as cur:
        cur.execute(_CURSOR_INSERT_SQL, ("old-cursor", "ratesync", "listing", None, 0, past, past))
        cur.execute(_CURSOR_INSERT_SQL, ("new-cursor", "ratesync", "listing", None, 10, now, future))
        cur.execute(_CURSOR_INSERT_SQL, ("no-ttl-cursor", "ratesync", "listing", None, 20, now, None))

    deleted = store.expire_cursors(now)
    assert deleted == 1
    assert store.resolve_cursor("old-cursor") is None
    assert store.resolve_cursor("new-cursor") == 10
    assert store.resolve_cursor("no-ttl-cursor") == 20
