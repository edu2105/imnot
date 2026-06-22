from __future__ import annotations

import asyncio
import json
import logging
import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

import httpx

from imnot.engine.session_store import SessionStore

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("imnot.db")

_STRESS_DDL = """
CREATE TABLE IF NOT EXISTS stress_runs (
    run_id          TEXT PRIMARY KEY,
    config_json     TEXT NOT NULL,
    results_json    TEXT,
    status          TEXT NOT NULL,
    ran_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stress_templates (
    template_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    config_json     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    import uuid

    return str(uuid.uuid4())


@dataclass
class RunState:
    run_id: str
    status: str
    config: dict
    fired: int = 0
    success_count: int = 0
    error_count: int = 0
    latencies: list[float] = field(default_factory=list)
    error_breakdown: dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


_active_runs: dict[str, RunState] = {}


def compute_total_requests(config: dict) -> int:
    rate = float(config["rate_per_second"])
    if config.get("total_count") is not None:
        return int(config["total_count"])
    return math.ceil(float(config["duration_seconds"]) * rate)


class StressStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def init(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_STRESS_DDL)
        self._conn.commit()
        logger.info("StressStore initialised at %s", self.db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        assert self._conn is not None, "StressStore.init() must be called before use"  # nosec B101
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def create_run(self, run_id: str, config: dict) -> None:
        sql = (
            "INSERT INTO stress_runs (run_id, config_json, results_json, status, ran_at)"
            " VALUES (?, ?, NULL, 'pending', ?)"
        )
        with self._cursor() as cur:
            cur.execute(sql, (run_id, json.dumps(config), _now()))

    def update_run_status(self, run_id: str, status: str) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE stress_runs SET status = ? WHERE run_id = ?", (status, run_id))

    def flush_run(self, run_id: str, status: str, results: dict) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE stress_runs SET status = ?, results_json = ? WHERE run_id = ?",
                (status, json.dumps(results), run_id),
            )

    def get_run(self, run_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM stress_runs WHERE run_id = ?", (run_id,))
            row = cur.fetchone()
        if row is None:
            return None
        result: dict[str, Any] = {
            "run_id": row["run_id"],
            "status": row["status"],
            "config": json.loads(row["config_json"]),
            "ran_at": row["ran_at"],
            "results": json.loads(row["results_json"]) if row["results_json"] else None,
        }
        return result

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM stress_runs ORDER BY ran_at DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        return [
            {
                "run_id": r["run_id"],
                "status": r["status"],
                "config": json.loads(r["config_json"]),
                "ran_at": r["ran_at"],
                "results": json.loads(r["results_json"]) if r["results_json"] else None,
            }
            for r in rows
        ]

    def delete_run(self, run_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM stress_runs WHERE run_id = ?", (run_id,))
            return cur.rowcount > 0

    def create_template(self, template_id: str, name: str, config: dict) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO stress_templates (template_id, name, config_json, created_at) VALUES (?, ?, ?, ?)",
                (template_id, name, json.dumps(config), _now()),
            )

    def get_template(self, template_id: str) -> dict | None:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM stress_templates WHERE template_id = ?", (template_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "template_id": row["template_id"],
            "name": row["name"],
            "config": json.loads(row["config_json"]),
            "created_at": row["created_at"],
        }

    def list_templates(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM stress_templates ORDER BY created_at DESC")
            rows = cur.fetchall()
        return [
            {
                "template_id": r["template_id"],
                "name": r["name"],
                "config": json.loads(r["config_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def delete_template(self, template_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM stress_templates WHERE template_id = ?", (template_id,))
            return cur.rowcount > 0


async def _fire_one(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    state: RunState,
    config: dict,
    body: str,
) -> None:
    method = config.get("method", "POST").upper()
    url = config["target_url"]
    headers: dict[str, str] = {"Content-Type": "application/json"}
    extra = config.get("headers") or {}
    headers.update(extra)

    async with semaphore:
        t0 = time.monotonic()
        try:
            resp = await client.request(method, url, headers=headers, content=body.encode())
            latency_ms = (time.monotonic() - t0) * 1000
            state.fired += 1
            if resp.is_success:
                state.success_count += 1
                state.latencies.append(latency_ms)
            else:
                state.error_count += 1
                key = str(resp.status_code)
                state.error_breakdown[key] = state.error_breakdown.get(key, 0) + 1
        except httpx.TimeoutException:
            state.error_count += 1
            state.error_breakdown["timeout"] = state.error_breakdown.get("timeout", 0) + 1
        except Exception:
            state.error_count += 1
            state.error_breakdown["network_error"] = state.error_breakdown.get("network_error", 0) + 1


def _flush_run(state: RunState, stress_store: StressStore, final_status: str) -> None:
    elapsed = time.monotonic() - state.started_at
    sorted_lat = sorted(state.latencies)
    n = len(sorted_lat)
    p50 = sorted_lat[int(n * 0.50)] if n else None
    p95 = sorted_lat[int(n * 0.95)] if n else None
    p99 = sorted_lat[int(n * 0.99)] if n else None
    actual_rate = state.fired / elapsed if elapsed > 0 else 0.0

    results = {
        "fired": state.fired,
        "success_count": state.success_count,
        "error_count": state.error_count,
        "elapsed_seconds": round(elapsed, 3),
        "p50_ms": round(p50, 3) if p50 is not None else None,
        "p95_ms": round(p95, 3) if p95 is not None else None,
        "p99_ms": round(p99, 3) if p99 is not None else None,
        "actual_rate_per_second": round(actual_rate, 3),
        "duration_seconds": round(elapsed, 3),
        "error_breakdown": state.error_breakdown,
    }
    stress_store.flush_run(state.run_id, final_status, results)


async def run_stress(
    run_id: str,
    config: dict,
    session_store: SessionStore,
    stress_store: StressStore,
) -> None:
    state = RunState(run_id=run_id, status="running", config=config)
    _active_runs[run_id] = state

    try:
        stress_store.update_run_status(run_id, "running")

        mode = config.get("mode", "standalone")
        if mode == "partner":
            partner = config["partner"]
            datapoint = config["datapoint"]
            payload_dict = session_store.resolve_payload(partner, datapoint, None)
            if payload_dict is None:
                body_template = "{}"
            else:
                body_template = json.dumps(payload_dict)
            vary_values: list[str] = []
        else:
            body_template = config.get("payload_template") or ""
            raw_vary = config.get("vary_values") or []
            vary_values = [str(v) for v in raw_vary]

        rate = float(config["rate_per_second"])
        total_requests = compute_total_requests(config)

        interval = 1.0 / rate
        max_concurrent = min(int(rate * 5), 500)
        semaphore = asyncio.Semaphore(max_concurrent)
        task_handles: list[asyncio.Task] = []

        limits = httpx.Limits(max_connections=500, max_keepalive_connections=100)
        async with httpx.AsyncClient(limits=limits, timeout=10.0) as client:
            for i in range(total_requests):
                if state.cancel_event.is_set():
                    break
                if vary_values:
                    body = body_template.replace("{{vary}}", vary_values[i % len(vary_values)])
                else:
                    body = body_template
                h = asyncio.create_task(_fire_one(client, semaphore, state, config, body))
                task_handles.append(h)
                await asyncio.sleep(interval)

            await asyncio.gather(*task_handles, return_exceptions=True)

        final_status = "cancelled" if state.cancel_event.is_set() else "done"
        state.status = final_status
        _flush_run(state, stress_store, final_status)

    except Exception:
        logger.exception("run_stress error for run_id=%s", run_id)
        state.status = "error"
        _flush_run(state, stress_store, "error")
    finally:
        _active_runs.pop(run_id, None)
