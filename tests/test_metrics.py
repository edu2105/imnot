"""Prometheus metrics at GET /imnot/metrics (imnot.engine.metrics)."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import pytest
from fastapi import BackgroundTasks, FastAPI
from fastapi.testclient import TestClient

import imnot.engine.patterns.push as push
from imnot.api.server import create_app
from imnot.config import load_config
from imnot.engine.egress import CallbackPolicy
from imnot.engine.metrics import Metrics, MetricsMiddleware
from tests.test_callback_delivery import _Recorder, _Store

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


def _samples(text: str) -> dict[str, float]:
    return {
        line.rsplit(" ", 1)[0]: float(line.rsplit(" ", 1)[1]) for line in text.splitlines() if not line.startswith("#")
    }


@pytest.fixture
def client(tmp_path):
    app = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "t.db", metrics_enabled=True, admin_key="k" * 20)
    with TestClient(app) as c:
        yield c


def test_off_by_default(tmp_path):
    app = create_app(partners_dir=PARTNERS_DIR, db_path=tmp_path / "t.db")
    with TestClient(app) as c:
        assert c.get("/imnot/metrics").status_code == 404
    assert not hasattr(app.state, "metrics")


def test_enabled_from_the_environment():
    assert load_config(None, {"IMNOT_METRICS_ENABLED": "1"}).metrics.enabled is True
    assert load_config(None, {}).metrics.enabled is False


def test_requests_are_counted_by_route_owner_not_raw_path(client):
    client.post("/oauth/token")
    client.post("/oauth/token")
    client.get("/nowhere/123")
    client.request("FOO", "/nowhere/456")
    client.get("/healthz")  # imnot's own routes are not counted
    client.get("/imnot/admin/partners", headers={"Authorization": "Bearer " + "k" * 20})
    r = client.get("/imnot/metrics")  # no key needed, like /healthz
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    s = _samples(r.text)
    token = [k for k in s if k.startswith("imnot_http_requests_total{") and 'method="POST"' in k and "/oauth" not in k]
    assert len(token) == 1 and s[token[0]] == 2
    assert 'datapoint="token"' in token[0] and 'status="200"' in token[0]
    assert s['imnot_http_requests_total{partner="",datapoint="",method="GET",status="404"}'] == 1
    assert s['imnot_http_requests_total{partner="",datapoint="",method="OTHER",status="404"}'] == 1
    assert sum(v for k, v in s.items() if k.startswith("imnot_http_requests_total")) == 4
    assert "nowhere" not in r.text  # raw paths never become labels
    assert s['imnot_info{version="' + r.text.split('version="')[1].split('"')[0] + '"}'] == 1
    assert s["imnot_partners_loaded"] >= 1


def test_an_unhandled_error_counts_as_500():
    # ServerErrorMiddleware turns it into a 500 outside this middleware, which never sees a response start.
    app = FastAPI()
    app.state.metrics = Metrics("x")
    app.add_middleware(MetricsMiddleware)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/boom").status_code == 500
    assert dict(app.state.metrics.requests) == {("", "", "GET", "500"): 1}


def test_histogram_buckets_are_cumulative(client):
    for _ in range(3):
        client.get("/nowhere")
    s = _samples(client.get("/imnot/metrics").text)
    base = 'imnot_http_request_duration_seconds_bucket{partner="",datapoint="",le='
    buckets = [v for k, v in s.items() if k.startswith(base)]
    assert buckets == sorted(buckets) and buckets[-1] == 3
    assert s[base + '"+Inf"}'] == 3
    assert s['imnot_http_request_duration_seconds_count{partner="",datapoint=""}'] == 3


def test_admin_auth_failures_are_counted(client):
    client.get("/imnot/admin/partners", headers={"Authorization": "Bearer wrong"})
    client.get("/imnot/admin/partners")
    assert _samples(client.get("/imnot/metrics").text)["imnot_admin_auth_failures_total"] == 2


def test_scrapes_are_not_in_the_http_log(client, caplog):
    with caplog.at_level(logging.INFO, logger="imnot.http"):
        client.get("/imnot/metrics")
    assert not [r for r in caplog.records if r.name == "imnot.http"]


def test_duration_stops_when_the_response_is_sent_not_after_background_tasks():
    # A callback delivery (and its retries) runs as a background task inside the same ASGI call.
    app = FastAPI()
    app.state.metrics = Metrics("x")
    app.add_middleware(MetricsMiddleware)

    async def slow_background():
        await asyncio.sleep(0.3)

    @app.post("/submit")
    async def submit(background_tasks: BackgroundTasks):
        background_tasks.add_task(slow_background)
        return {"ok": True}

    with TestClient(app) as c:
        start = time.perf_counter()
        c.post("/submit")
        assert time.perf_counter() - start >= 0.3  # the background task did run inside the call
    assert app.state.metrics.duration_count[("", "")] == 1
    assert app.state.metrics.duration_sum[("", "")] < 0.2


def test_label_values_are_escaped():
    m = Metrics('1"\\\n')
    assert 'imnot_info{version="1\\"\\\\\\n"} 1' in m.render(0)


# ---------------------------------------------------------------------------
# Callback deliveries
# ---------------------------------------------------------------------------


async def _fire(monkeypatch, outcomes, url="http://127.0.0.1:9/cb", store=None, policy=None):
    monkeypatch.setattr(push.httpx, "AsyncClient", _Recorder(outcomes))

    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(push.asyncio, "sleep", no_sleep)
    metrics = Metrics("x")
    await push.fire_callback(
        store or _Store(),
        "p",
        "d",
        None,
        url,
        "POST",
        delivery={"retries": {"attempts": 2, "backoff_seconds": 0}},
        policy=policy,
        metrics=metrics,
    )
    return dict(metrics.callbacks)


@pytest.mark.asyncio
async def test_callback_delivered_after_a_retry_counts_once(monkeypatch):
    assert await _fire(monkeypatch, [500, 200]) == {("p", "d", "delivered"): 1}


@pytest.mark.asyncio
async def test_callback_failed_after_the_last_attempt(monkeypatch):
    assert await _fire(monkeypatch, [500, RuntimeError("down")]) == {("p", "d", "failed"): 1}


@pytest.mark.asyncio
async def test_callback_refused_by_the_policy(monkeypatch):
    got = await _fire(monkeypatch, [], url="http://10.0.0.1/cb", policy=CallbackPolicy.parse("127.0.0.0/8"))
    assert got == {("p", "d", "refused"): 1}


@pytest.mark.asyncio
async def test_callback_without_payload_is_skipped(monkeypatch):
    class NoPayload:
        def resolve_payload(self, *a):
            return None

    assert await _fire(monkeypatch, [], store=NoPayload()) == {("p", "d", "skipped"): 1}
