"""Failed admin logins share one slow queue (router.AUTH_FAILURE_DELAY_SECONDS)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import pytest

from imnot.api.server import create_app
from imnot.engine import router

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


def _client(tmp_path) -> httpx.AsyncClient:
    app = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "t.db", admin_key="secret")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_failed_attempts_queue_one_after_another(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "AUTH_FAILURE_DELAY_SECONDS", 0.2)
    async with _client(tmp_path) as c:
        start = time.monotonic()
        responses = await asyncio.gather(
            *[c.get("/imnot/admin/partners", headers={"Authorization": "Bearer nope"}) for _ in range(3)]
        )
        elapsed = time.monotonic() - start
    assert [r.status_code for r in responses] == [401, 401, 401]
    assert elapsed >= 0.6  # three slots of 0.2 s, not one shared wait


@pytest.mark.asyncio
async def test_right_key_never_waits_behind_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "AUTH_FAILURE_DELAY_SECONDS", 1.0)
    async with _client(tmp_path) as c:
        bad = asyncio.create_task(c.get("/imnot/admin/partners", headers={"Authorization": "Bearer nope"}))
        await asyncio.sleep(0.05)
        start = time.monotonic()
        ok = await c.get("/imnot/admin/partners", headers={"Authorization": "Bearer secret"})
        assert ok.status_code == 200
        assert time.monotonic() - start < 0.5
        assert (await bad).status_code == 401


@pytest.mark.asyncio
async def test_429_when_the_queue_is_too_long(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "AUTH_FAILURE_DELAY_SECONDS", 0.2)
    monkeypatch.setattr(router, "AUTH_FAILURE_MAX_WAIT_SECONDS", 0.3)
    async with _client(tmp_path) as c:
        responses = await asyncio.gather(
            *[c.get("/imnot/admin/partners", headers={"Authorization": "Bearer nope"}) for _ in range(4)]
        )
    codes = sorted(r.status_code for r in responses)
    assert codes == [401, 401, 429, 429]  # slots at 0 and 0.2 s; 0.4 s is past the 0.3 s limit
    too_many = next(r for r in responses if r.status_code == 429)
    assert int(too_many.headers["Retry-After"]) >= 1
