"""
Session store: SQLite-backed persistence for payloads and sessions.

Responsibilities:
- Initialize and migrate the SQLite schema on startup.
- Store and retrieve global payloads keyed by (partner, datapoint).
- Create sessions and store per-session payloads keyed by (session_id, partner, datapoint).
- Look up the correct payload for an incoming request given an optional session_id.
- Map async request UUIDs to their originating session so fetch steps can resolve the right payload.
- List active sessions for the admin API.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("imnot.db")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS global_payloads (
    partner     TEXT NOT NULL,
    datapoint   TEXT NOT NULL,
    payload     TEXT NOT NULL,           -- JSON blob
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (partner, datapoint)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    partner     TEXT NOT NULL,
    datapoint   TEXT NOT NULL,
    payload     TEXT NOT NULL,           -- JSON blob
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS async_requests (
    uuid        TEXT PRIMARY KEY,
    partner     TEXT NOT NULL,
    datapoint   TEXT NOT NULL,
    session_id  TEXT,                    -- NULL for global-mode requests
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_requests (
    uuid            TEXT PRIMARY KEY,
    partner         TEXT NOT NULL,
    datapoint       TEXT NOT NULL,
    session_id      TEXT,               -- NULL for global-mode requests
    callback_url    TEXT NOT NULL,
    callback_method TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class SessionStore:
    """Thin synchronous wrapper around a SQLite database.

    All methods are synchronous and safe to call from FastAPI route handlers
    via `run_in_executor` if async is needed, or directly inside sync routes.
    """

    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Open the database connection and create tables if they don't exist."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Migrate poll_requests → async_requests for existing databases
        try:
            old_table = self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='poll_requests'"
            ).fetchone()
            if old_table:
                self._conn.execute("ALTER TABLE poll_requests RENAME TO async_requests")
                self._conn.commit()
                logger.info("Migrated poll_requests table to async_requests")
        except sqlite3.OperationalError as exc:
            logger.warning("Could not migrate poll_requests table: %s", exc)
        self._conn.executescript(_DDL)
        self._conn.commit()
        logger.info("Session store initialised at %s", self.db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        assert self._conn is not None, "SessionStore.init() must be called before use"  # nosec B101
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    # ------------------------------------------------------------------
    # Global payloads
    # ------------------------------------------------------------------

    def store_global_payload(self, partner: str, datapoint: str, payload: dict[str, Any]) -> None:
        """Upsert a global payload for (partner, datapoint). Last write wins."""
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO global_payloads (partner, datapoint, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (partner, datapoint) DO UPDATE
                    SET payload = excluded.payload,
                        updated_at = excluded.updated_at
                """,
                (partner, datapoint, json.dumps(payload), now),
            )
        logger.debug("Stored global payload for %s/%s", partner, datapoint)

    # ------------------------------------------------------------------
    # Session payloads
    # ------------------------------------------------------------------

    def store_session_payload(
        self, partner: str, datapoint: str, payload: dict[str, Any]
    ) -> str:
        """Create a new session with an isolated payload. Returns the session_id."""
        session_id = _new_id()
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessions (session_id, partner, datapoint, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, partner, datapoint, json.dumps(payload), now),
            )
        logger.debug("Stored session payload for %s/%s → session %s", partner, datapoint, session_id)
        return session_id

    # ------------------------------------------------------------------
    # Async request tracking
    # ------------------------------------------------------------------

    def register_async_request(
        self, partner: str, datapoint: str, session_id: str | None
    ) -> str:
        """Record a new async request (submit step). Returns the generated UUID."""
        async_uuid = _new_id()
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO async_requests (uuid, partner, datapoint, session_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (async_uuid, partner, datapoint, session_id, now),
            )
        logger.debug("Registered async request %s for %s/%s", async_uuid, partner, datapoint)
        return async_uuid

    def get_async_request(self, async_uuid: str) -> sqlite3.Row | None:
        """Return the async_requests row for a UUID, or None if not found."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM async_requests WHERE uuid = ?", (async_uuid,))
            return cur.fetchone()

    # ------------------------------------------------------------------
    # Push request tracking
    # ------------------------------------------------------------------

    def store_push_request(
        self,
        partner: str,
        datapoint: str,
        session_id: str | None,
        callback_url: str,
        callback_method: str,
    ) -> str:
        """Record a new push submit request. Returns the generated UUID."""
        push_uuid = _new_id()
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO push_requests
                    (uuid, partner, datapoint, session_id, callback_url, callback_method, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (push_uuid, partner, datapoint, session_id, callback_url, callback_method, now),
            )
        logger.debug(
            "Stored push request %s for %s/%s → %s",
            push_uuid, partner, datapoint, callback_url,
        )
        return push_uuid

    def get_push_request(self, push_uuid: str) -> sqlite3.Row | None:
        """Return the push_requests row for a UUID, or None if not found."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM push_requests WHERE uuid = ?", (push_uuid,))
            return cur.fetchone()

    # ------------------------------------------------------------------
    # Payload resolution
    # ------------------------------------------------------------------

    def resolve_payload(
        self, partner: str, datapoint: str, session_id: str | None
    ) -> dict[str, Any] | None:
        """Return the payload for the given (partner, datapoint), respecting session priority.

        Resolution order:
        1. If session_id is provided → look up session payload → return None if not found.
        2. If no session_id → look up global payload → return None if not found.
        """
        with self._cursor() as cur:
            if session_id:
                cur.execute(
                    "SELECT payload FROM sessions WHERE session_id = ? AND partner = ? AND datapoint = ?",
                    (session_id, partner, datapoint),
                )
            else:
                cur.execute(
                    "SELECT payload FROM global_payloads WHERE partner = ? AND datapoint = ?",
                    (partner, datapoint),
                )
            row = cur.fetchone()

        if row is None:
            return None
        return json.loads(row["payload"])

    # ------------------------------------------------------------------
    # Admin queries
    # ------------------------------------------------------------------

    def get_global_payload(self, partner: str, datapoint: str) -> dict[str, Any] | None:
        """Return the current global payload for (partner, datapoint), or None if not set."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT payload, updated_at FROM global_payloads WHERE partner = ? AND datapoint = ?",
                (partner, datapoint),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {"payload": json.loads(row["payload"]), "updated_at": row["updated_at"]}

    def get_session_payload(self, session_id: str) -> dict[str, Any] | None:
        """Return the payload and metadata for a session_id, or None if not found."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT session_id, partner, datapoint, payload, created_at FROM sessions WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "session_id": row["session_id"],
            "partner": row["partner"],
            "datapoint": row["datapoint"],
            "payload": json.loads(row["payload"]),
            "created_at": row["created_at"],
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return all sessions ordered by creation time descending."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT session_id, partner, datapoint, created_at FROM sessions ORDER BY created_at DESC"
            )
            return [dict(row) for row in cur.fetchall()]

    def clear_sessions(self) -> int:
        """Delete all sessions. Returns the number of rows deleted."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM sessions")
            return cur.rowcount


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())
