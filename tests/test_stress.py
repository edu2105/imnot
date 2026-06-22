"""Tests for StressStore CRUD, run_stress lifecycle, and stress HTTP endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from imnot.engine.session_store import SessionStore
from imnot.engine.stress import RunState, StressStore, _active_runs, run_stress  # noqa: F401

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture()
def stress_store(tmp_db: Path) -> StressStore:
    store = StressStore(db_path=tmp_db)
    store.init()
    yield store
    store.close()


@pytest.fixture()
def session_store(tmp_db: Path) -> SessionStore:
    store = SessionStore(db_path=tmp_db)
    store.init()
    yield store
    store.close()


@pytest.fixture(autouse=True)
def clear_active_runs():
    _active_runs.clear()
    yield
    _active_runs.clear()


@pytest.fixture()
def app_client(tmp_path: Path):
    from imnot.api.server import create_app

    db = tmp_path / "app.db"
    app = create_app(partners_dir=None, db_path=db, admin_key=None)
    with TestClient(app) as client:
        yield client


# ---------------------------------------------------------------------------
# StressStore CRUD tests
# ---------------------------------------------------------------------------


def test_create_and_get_run(stress_store: StressStore):
    config = {"mode": "standalone", "target_url": "http://example.com", "rate_per_second": 10, "total_count": 100}
    stress_store.create_run("run-1", config)
    row = stress_store.get_run("run-1")
    assert row is not None
    assert row["run_id"] == "run-1"
    assert row["status"] == "pending"
    assert row["config"] == config
    assert row["results"] is None


def test_update_run_status(stress_store: StressStore):
    stress_store.create_run("run-2", {"rate_per_second": 1, "total_count": 10})
    stress_store.update_run_status("run-2", "running")
    row = stress_store.get_run("run-2")
    assert row["status"] == "running"


def test_flush_run(stress_store: StressStore):
    stress_store.create_run("run-3", {"rate_per_second": 1, "total_count": 5})
    results = {"fired": 5, "success_count": 5, "error_count": 0}
    stress_store.flush_run("run-3", "done", results)
    row = stress_store.get_run("run-3")
    assert row["status"] == "done"
    assert row["results"]["fired"] == 5


def test_list_runs(stress_store: StressStore):
    stress_store.create_run("run-a", {"rate_per_second": 1, "total_count": 1})
    stress_store.create_run("run-b", {"rate_per_second": 2, "total_count": 2})
    runs = stress_store.list_runs()
    assert len(runs) == 2


def test_get_run_db_not_found(stress_store: StressStore):
    assert stress_store.get_run("nonexistent") is None


def test_create_list_delete_template(stress_store: StressStore):
    config = {"mode": "standalone", "target_url": "http://example.com", "rate_per_second": 10, "total_count": 100}
    stress_store.create_template("tmpl-1", "My Template", config)
    templates = stress_store.list_templates()
    assert len(templates) == 1
    assert templates[0]["name"] == "My Template"
    assert templates[0]["config"] == config

    tmpl = stress_store.get_template("tmpl-1")
    assert tmpl is not None
    assert tmpl["template_id"] == "tmpl-1"

    deleted = stress_store.delete_template("tmpl-1")
    assert deleted is True
    assert stress_store.list_templates() == []


def test_delete_nonexistent_template(stress_store: StressStore):
    assert stress_store.delete_template("no-such-id") is False


# ---------------------------------------------------------------------------
# run_stress happy-path test (mock httpx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stress_happy_path(stress_store: StressStore, session_store: SessionStore):
    config = {
        "mode": "standalone",
        "target_url": "http://mockhost/webhook",
        "method": "POST",
        "payload_template": '{"id": "{{vary}}"}',
        "vary_values": ["A", "B"],
        "rate_per_second": 100,
        "total_count": 3,
    }
    run_id = "test-run-happy"
    stress_store.create_run(run_id, config)

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row is not None
    assert row["status"] == "done"
    results = row["results"]
    assert results["fired"] == 3
    assert results["success_count"] == 3
    assert results["error_count"] == 0
    assert run_id not in _active_runs


# ---------------------------------------------------------------------------
# Cancellation test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stress_cancellation(stress_store: StressStore, session_store: SessionStore):
    config = {
        "mode": "standalone",
        "target_url": "http://mockhost/cancel",
        "method": "POST",
        "rate_per_second": 1000,
        "total_count": 1000,
    }
    run_id = "test-run-cancel"
    stress_store.create_run(run_id, config)

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200

    cancel_called = False

    async def slow_request(*args, **kwargs):
        nonlocal cancel_called
        if not cancel_called:
            cancel_called = True
            state = _active_runs.get(run_id)
            if state:
                state.cancel_event.set()
        return mock_response

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = slow_request
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row["status"] == "cancelled"
    assert run_id not in _active_runs


# ---------------------------------------------------------------------------
# Partner-bound 422 when payload not uploaded
# ---------------------------------------------------------------------------


def test_partner_bound_422_no_payload(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={
            "mode": "partner",
            "partner": "staylink",
            "datapoint": "reservation",
            "target_url": "http://nifi.internal/webhook",
            "rate_per_second": 10,
            "total_count": 100,
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert "payload" in data["detail"].lower() or "staylink" in data["detail"]


# ---------------------------------------------------------------------------
# HTTP endpoints (integration)
# ---------------------------------------------------------------------------


def test_post_run_standalone(app_client: TestClient):
    with patch("imnot.engine.stress_router.asyncio.create_task") as mock_create_task:
        resp = app_client.post(
            "/imnot/admin/stress/run",
            json={
                "mode": "standalone",
                "target_url": "http://example.com/hook",
                "method": "POST",
                "rate_per_second": 10,
                "total_count": 50,
            },
        )
    assert resp.status_code == 201
    data = resp.json()
    assert "run_id" in data
    assert data["status"] == "pending"
    mock_create_task.assert_called_once()


def test_post_run_missing_total_and_duration(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={
            "mode": "standalone",
            "target_url": "http://example.com/hook",
            "rate_per_second": 10,
        },
    )
    assert resp.status_code == 422


def test_post_run_both_total_and_duration(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={
            "mode": "standalone",
            "target_url": "http://example.com/hook",
            "rate_per_second": 10,
            "total_count": 100,
            "duration_seconds": 30,
        },
    )
    assert resp.status_code == 422


def test_get_run_running(app_client: TestClient):
    run_id = "fake-running-run"
    state = RunState(run_id=run_id, status="running", config={})
    state.fired = 42
    state.success_count = 40
    state.error_count = 2
    _active_runs[run_id] = state

    resp = app_client.get(f"/imnot/admin/stress/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["status"] == "running"
    assert data["fired"] == 42


def test_get_run_done(app_client: TestClient):
    run_id = "fake-done-run"
    stress_store_state: StressStore = app_client.app.state.stress_store
    config = {"rate_per_second": 10, "total_count": 5}
    stress_store_state.create_run(run_id, config)
    stress_store_state.flush_run(run_id, "done", {"fired": 5, "success_count": 5, "error_count": 0})

    resp = app_client.get(f"/imnot/admin/stress/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["fired"] == 5


def test_get_run_not_found(app_client: TestClient):
    resp = app_client.get("/imnot/admin/stress/nonexistent-run")
    assert resp.status_code == 404


def test_delete_run_cancel(app_client: TestClient):
    run_id = "cancel-me"
    state = RunState(run_id=run_id, status="running", config={})
    _active_runs[run_id] = state

    resp = app_client.delete(f"/imnot/admin/stress/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "cancelled"
    assert state.cancel_event.is_set()


def test_delete_run_not_found(app_client: TestClient):
    resp = app_client.delete("/imnot/admin/stress/no-such-run")
    assert resp.status_code == 404


def test_delete_run_already_done(app_client: TestClient):
    run_id = "already-done"
    stress_store_state: StressStore = app_client.app.state.stress_store
    stress_store_state.create_run(run_id, {})
    stress_store_state.flush_run(run_id, "done", {})

    resp = app_client.delete(f"/imnot/admin/stress/{run_id}")
    assert resp.status_code == 409


def test_get_templates_empty(app_client: TestClient):
    resp = app_client.get("/imnot/admin/stress/templates")
    assert resp.status_code == 200
    assert resp.json() == []


def test_post_and_get_template(app_client: TestClient):
    config = {"mode": "standalone", "target_url": "http://example.com", "rate_per_second": 10, "total_count": 100}
    resp = app_client.post(
        "/imnot/admin/stress/templates",
        json={"name": "My Test Template", "config": config},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Test Template"
    assert "template_id" in data

    resp2 = app_client.get("/imnot/admin/stress/templates")
    assert resp2.status_code == 200
    templates = resp2.json()
    assert len(templates) == 1
    assert templates[0]["name"] == "My Test Template"
    assert templates[0]["config"] == config


def test_delete_template(app_client: TestClient):
    config = {"mode": "standalone", "target_url": "http://example.com", "rate_per_second": 5, "total_count": 50}
    create_resp = app_client.post(
        "/imnot/admin/stress/templates",
        json={"name": "To Delete", "config": config},
    )
    tid = create_resp.json()["template_id"]

    del_resp = app_client.delete(f"/imnot/admin/stress/templates/{tid}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"

    list_resp = app_client.get("/imnot/admin/stress/templates")
    assert list_resp.json() == []


def test_delete_template_not_found(app_client: TestClient):
    resp = app_client.delete("/imnot/admin/stress/templates/no-such-template")
    assert resp.status_code == 404


def test_get_runs_list(app_client: TestClient):
    stress_store_state: StressStore = app_client.app.state.stress_store
    stress_store_state.create_run("list-run-1", {"rate_per_second": 1, "total_count": 1})
    stress_store_state.flush_run("list-run-1", "done", {"fired": 1})

    resp = app_client.get("/imnot/admin/stress/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert any(r["run_id"] == "list-run-1" for r in runs)


def test_post_template_missing_name(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/templates",
        json={"config": {"rate_per_second": 1, "total_count": 1}},
    )
    assert resp.status_code == 422


def test_post_template_missing_config(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/templates",
        json={"name": "No Config"},
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# stress_router.py — missing branch coverage
# ---------------------------------------------------------------------------


def test_post_run_invalid_json(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        content=b"not-valid-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid JSON body"


def test_post_run_zero_rate(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 0, "total_count": 10},
    )
    assert resp.status_code == 422
    assert "rate_per_second" in resp.json()["detail"]


def test_post_run_standalone_missing_target_url(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "rate_per_second": 10, "total_count": 5},
    )
    assert resp.status_code == 422
    assert "target_url" in resp.json()["detail"]


def test_post_run_rate_above_ceiling(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 5000, "total_count": 10},
    )
    assert resp.status_code == 422
    assert "rate_per_second" in resp.json()["detail"]


def test_post_run_rate_below_floor(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 0.0001, "total_count": 10},
    )
    assert resp.status_code == 422
    assert "rate_per_second" in resp.json()["detail"]


def test_post_run_total_count_above_ceiling(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 10, "total_count": 200_000},
    )
    assert resp.status_code == 422
    assert "exceeds the maximum" in resp.json()["detail"]


def test_post_run_duration_implied_total_above_ceiling(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 100, "duration_seconds": 2000},
    )
    assert resp.status_code == 422
    assert "exceeds the maximum" in resp.json()["detail"]


def test_post_run_invalid_target_url_scheme(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "file:///etc/passwd", "rate_per_second": 10, "total_count": 5},
    )
    assert resp.status_code == 422
    assert "scheme" in resp.json()["detail"]


def test_post_run_non_numeric_total_count_returns_422(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 10, "total_count": "abc"},
    )
    assert resp.status_code == 422
    assert "numbers" in resp.json()["detail"]


def test_post_run_negative_total_count_returns_422(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 10, "total_count": -5},
    )
    assert resp.status_code == 422
    assert "total_count" in resp.json()["detail"]


def test_post_run_negative_duration_seconds_returns_422(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 10, "duration_seconds": -100},
    )
    assert resp.status_code == 422
    assert "duration_seconds" in resp.json()["detail"]


def test_post_run_logs_audit_line_on_success(app_client: TestClient, caplog: pytest.LogCaptureFixture):
    with patch("imnot.engine.stress_router.asyncio.create_task"):
        with caplog.at_level("INFO", logger="imnot.http"):
            resp = app_client.post(
                "/imnot/admin/stress/run",
                json={
                    "mode": "standalone",
                    "target_url": "http://example.com/hook",
                    "rate_per_second": 10,
                    "total_count": 5,
                },
            )
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    matching = [r for r in caplog.records if r.name == "imnot.http" and run_id in r.getMessage()]
    assert matching, "expected an audit log record on the imnot.http logger for the new run"
    assert "started" in matching[0].getMessage()


def test_post_run_ceiling_exceeded_never_creates_task(app_client: TestClient):
    with patch("imnot.engine.stress_router.asyncio.create_task") as mock_create_task:
        resp = app_client.post(
            "/imnot/admin/stress/run",
            json={"mode": "standalone", "target_url": "http://x.com", "rate_per_second": 5000, "total_count": 10},
        )
    assert resp.status_code == 422
    mock_create_task.assert_not_called()


def test_post_template_invalid_json(app_client: TestClient):
    resp = app_client.post(
        "/imnot/admin/stress/templates",
        content=b"not-valid-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid JSON body"


def test_delete_run_already_done_in_memory(app_client: TestClient):
    """Cancel a run that is in _active_runs but already in terminal state."""
    run_id = "done-in-memory"
    state = RunState(run_id=run_id, status="done", config={})
    _active_runs[run_id] = state

    resp = app_client.delete(f"/imnot/admin/stress/{run_id}")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# stress.py — missing branch coverage: _fire_one error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stress_timeout_error(stress_store: StressStore, session_store: SessionStore):
    import httpx

    config = {
        "mode": "standalone",
        "target_url": "http://mockhost/timeout",
        "method": "POST",
        "rate_per_second": 100,
        "total_count": 1,
    }
    run_id = "test-run-timeout"
    stress_store.create_run(run_id, config)

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row["status"] == "done"
    results = row["results"]
    assert results["error_count"] == 1
    assert results["error_breakdown"].get("timeout") == 1


@pytest.mark.asyncio
async def test_run_stress_network_error(stress_store: StressStore, session_store: SessionStore):
    config = {
        "mode": "standalone",
        "target_url": "http://mockhost/error",
        "method": "POST",
        "rate_per_second": 100,
        "total_count": 1,
    }
    run_id = "test-run-network-error"
    stress_store.create_run(run_id, config)

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(side_effect=ConnectionError("connection refused"))
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row["results"]["error_breakdown"].get("network_error") == 1


@pytest.mark.asyncio
async def test_run_stress_partner_mode(stress_store: StressStore, session_store: SessionStore):
    session_store.store_global_payload("acme", "events", {"type": "checkout"})

    config = {
        "mode": "partner",
        "partner": "acme",
        "datapoint": "events",
        "target_url": "http://mockhost/partner",
        "method": "POST",
        "rate_per_second": 100,
        "total_count": 2,
    }
    run_id = "test-run-partner"
    stress_store.create_run(run_id, config)

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row["status"] == "done"
    assert row["results"]["fired"] == 2


@pytest.mark.asyncio
async def test_run_stress_duration_seconds(stress_store: StressStore, session_store: SessionStore):
    config = {
        "mode": "standalone",
        "target_url": "http://mockhost/duration",
        "method": "POST",
        "rate_per_second": 10,
        "duration_seconds": 0.5,
    }
    run_id = "test-run-duration"
    stress_store.create_run(run_id, config)

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row["status"] == "done"
    assert row["results"]["fired"] == 5  # ceil(0.5 * 10)


@pytest.mark.asyncio
async def test_run_stress_top_level_exception(stress_store: StressStore, session_store: SessionStore):
    """Top-level except block: stress_store.update_run_status raises."""
    config = {
        "mode": "standalone",
        "target_url": "http://mockhost/crash",
        "method": "POST",
        "rate_per_second": 1,
        "total_count": 1,
    }
    run_id = "test-run-crash"
    stress_store.create_run(run_id, config)

    original_update = stress_store.update_run_status

    def boom(rid, status):
        raise RuntimeError("DB exploded")

    stress_store.update_run_status = boom

    await run_stress(run_id, config, session_store, stress_store)

    stress_store.update_run_status = original_update
    row = stress_store.get_run(run_id)
    assert row["status"] == "error"
    assert run_id not in _active_runs


# ---------------------------------------------------------------------------
# stress.py — _cursor rollback and get_template None
# ---------------------------------------------------------------------------


def test_cursor_rollback_on_exception(stress_store: StressStore):
    """_cursor rolls back and re-raises when the caller raises inside the with block."""
    with pytest.raises(ValueError, match="injected error"):
        with stress_store._cursor():
            raise ValueError("injected error")


def test_get_template_not_found(stress_store: StressStore):
    assert stress_store.get_template("no-such-template") is None


# ---------------------------------------------------------------------------
# Remaining branch gaps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stress_non_2xx_response(stress_store: StressStore, session_store: SessionStore):
    """_fire_one else-branch: non-2xx response tallied into error_breakdown by status code."""
    config = {
        "mode": "standalone",
        "target_url": "http://mockhost/fail",
        "method": "POST",
        "rate_per_second": 100,
        "total_count": 1,
    }
    run_id = "test-run-non-2xx"
    stress_store.create_run(run_id, config)

    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 500

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row["results"]["error_count"] == 1
    assert row["results"]["error_breakdown"].get("500") == 1
    assert row["results"]["success_count"] == 0


@pytest.mark.asyncio
async def test_run_stress_partner_mode_no_payload(stress_store: StressStore, session_store: SessionStore):
    """Partner mode with no global payload uploaded → body_template falls back to '{}'."""
    config = {
        "mode": "partner",
        "partner": "ghost",
        "datapoint": "missing",
        "target_url": "http://mockhost/partner-empty",
        "method": "POST",
        "rate_per_second": 100,
        "total_count": 1,
    }
    run_id = "test-run-partner-no-payload"
    stress_store.create_run(run_id, config)

    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.status_code = 200

    with patch("imnot.engine.stress.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.request = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await run_stress(run_id, config, session_store, stress_store)

    row = stress_store.get_run(run_id)
    assert row["status"] == "done"
    assert row["results"]["fired"] == 1


def test_delete_run_from_history(app_client: TestClient):
    """DELETE /imnot/admin/stress/runs/{run_id} removes a completed run from DB."""
    ss: StressStore = app_client.app.state.stress_store
    ss.create_run("hist-del-1", {"rate_per_second": 1, "total_count": 1})
    ss.flush_run("hist-del-1", "done", {"fired": 1})

    resp = app_client.delete("/imnot/admin/stress/runs/hist-del-1")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert ss.get_run("hist-del-1") is None


def test_delete_run_from_history_not_found(app_client: TestClient):
    resp = app_client.delete("/imnot/admin/stress/runs/no-such-run")
    assert resp.status_code == 404


def test_delete_run_from_history_still_active(app_client: TestClient):
    """DELETE /runs/{run_id} returns 409 if the run is still in _active_runs."""
    run_id = "still-active"
    state = RunState(run_id=run_id, status="running", config={})
    _active_runs[run_id] = state

    resp = app_client.delete(f"/imnot/admin/stress/runs/{run_id}")
    assert resp.status_code == 409


def test_post_run_partner_missing_fields(app_client: TestClient):
    """Partner mode without partner/datapoint fields → 422."""
    resp = app_client.post(
        "/imnot/admin/stress/run",
        json={"mode": "partner", "rate_per_second": 10, "total_count": 5},
    )
    assert resp.status_code == 422
    assert "partner" in resp.json()["detail"].lower() or "datapoint" in resp.json()["detail"].lower()
