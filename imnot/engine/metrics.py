"""
Prometheus metrics at ``GET /imnot/metrics`` (off by default: ``[metrics] enabled`` / ``IMNOT_METRICS_ENABLED``).

Text exposition format 0.0.4, written by hand: imnot adds no dependency for it. Counters live in this
process only (one replica per instance, see docs/deployment.md) and restart from zero with it.

Labels are bounded on purpose: partner and datapoint come from the route that answered (unmatched
paths count as ``partner=""``), never from the raw path; unusual HTTP methods count as ``OTHER``.
Nothing from payloads, bodies or headers is ever a label.

Metrics:
- ``imnot_http_requests_total{partner,datapoint,method,status}``: requests to mock routes.
- ``imnot_http_request_duration_seconds{partner,datapoint}``: histogram of their durations.
- ``imnot_callback_deliveries_total{partner,datapoint,result}``: ``delivered``, ``failed`` (after the
  last retry), ``refused`` (blocked by the callback policy) or ``skipped`` (no payload to send).
- ``imnot_admin_auth_failures_total``: requests to ``/imnot/admin/*`` with a wrong or missing key.
- ``imnot_partners_loaded``: partners with registered routes.
- ``imnot_info{version}``: always 1.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from imnot.engine.journal import is_mock_path, route_owner

METRICS_PATH = "/imnot/metrics"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(**labels: str) -> str:
    return "{" + ",".join(f'{k}="{_escape(v)}"' for k, v in labels.items()) + "}"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(value)


class Metrics:
    """In-memory counters. Every update is synchronous, so it is atomic within the event loop."""

    def __init__(self, version: str) -> None:
        self.version = version
        self.requests: dict[tuple[str, str, str, str], int] = defaultdict(int)
        self.duration_buckets: dict[tuple[str, str], list[int]] = {}
        self.duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self.duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.callbacks: dict[tuple[str, str, str], int] = defaultdict(int)
        self.admin_auth_failures = 0

    def observe_request(
        self, partner: str | None, datapoint: str | None, method: str, status: int, seconds: float
    ) -> None:
        p, d = partner or "", datapoint or ""
        m = method if method in _METHODS else "OTHER"
        self.requests[(p, d, m, str(status))] += 1
        buckets = self.duration_buckets.setdefault((p, d), [0] * len(DURATION_BUCKETS))
        for i, bound in enumerate(DURATION_BUCKETS):
            if seconds <= bound:
                buckets[i] += 1
        self.duration_sum[(p, d)] += seconds
        self.duration_count[(p, d)] += 1

    def observe_callback(self, partner: str, datapoint: str, result: str) -> None:
        self.callbacks[(partner, datapoint, result)] += 1

    def render(self, partners_loaded: int) -> str:
        out: list[str] = []

        def header(name: str, kind: str, help_text: str) -> None:
            out.append(f"# HELP {name} {help_text}")
            out.append(f"# TYPE {name} {kind}")

        header("imnot_info", "gauge", "imnot version.")
        out.append(f"imnot_info{_labels(version=self.version)} 1")

        header("imnot_partners_loaded", "gauge", "Partners with registered routes.")
        out.append(f"imnot_partners_loaded {partners_loaded}")

        header("imnot_http_requests_total", "counter", "Requests to mock routes.")
        for (p, d, m, s), n in sorted(self.requests.items()):
            out.append(f"imnot_http_requests_total{_labels(partner=p, datapoint=d, method=m, status=s)} {n}")

        name = "imnot_http_request_duration_seconds"
        header(name, "histogram", "Time to answer a request to a mock route.")
        for key in sorted(self.duration_count):
            p, d = key
            for bound, n in zip(DURATION_BUCKETS, self.duration_buckets[key]):
                out.append(f"{name}_bucket{_labels(partner=p, datapoint=d, le=_number(bound))} {n}")
            out.append(f"{name}_bucket{_labels(partner=p, datapoint=d, le='+Inf')} {self.duration_count[key]}")
            out.append(f"{name}_sum{_labels(partner=p, datapoint=d)} {self.duration_sum[key]!r}")
            out.append(f"{name}_count{_labels(partner=p, datapoint=d)} {self.duration_count[key]}")

        header("imnot_callback_deliveries_total", "counter", "Callback deliveries by result.")
        for (p, d, r), n in sorted(self.callbacks.items()):
            out.append(f"imnot_callback_deliveries_total{_labels(partner=p, datapoint=d, result=r)} {n}")

        header("imnot_admin_auth_failures_total", "counter", "Admin requests with a wrong or missing key.")
        out.append(f"imnot_admin_auth_failures_total {self.admin_auth_failures}")
        return "\n".join(out) + "\n"


def get_metrics(app: Any) -> Metrics | None:
    """The app's Metrics, or None when metrics are off."""
    return getattr(getattr(app, "state", None), "metrics", None)


class MetricsMiddleware:
    """Pure ASGI: counts and times every request to a mock route (same set as the request journal)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_mock_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        status: dict[str, int] = {}
        recorded = False
        start = time.perf_counter()

        def record() -> None:
            nonlocal recorded
            if recorded:
                return
            recorded = True
            metrics = get_metrics(scope.get("app"))
            if metrics is not None:
                partner, datapoint = route_owner(scope)
                metrics.observe_request(
                    partner, datapoint, scope.get("method", ""), status.get("code", 500), time.perf_counter() - start
                )

        async def send_and_watch(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)
            # Recorded when the last body chunk is sent, not when the app returns: background tasks
            # (a callback delivery and its retries) run inside the same ASGI call, after the response.
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                record()

        try:
            await self.app(scope, receive, send_and_watch)
        finally:
            record()  # no-op if already recorded; an unhandled error never answered here and becomes a 500 outside


def register_metrics(app: FastAPI, version: str) -> None:
    """Turn metrics on for *app*: the counters, the middleware and ``GET /imnot/metrics`` (no auth, like /healthz)."""
    app.state.metrics = Metrics(version)
    app.add_middleware(MetricsMiddleware)

    async def metrics_endpoint() -> PlainTextResponse:
        partners = {owner.split("/", 1)[0] for owner in getattr(app.state, "registered_routes", {}).values()}
        return PlainTextResponse(app.state.metrics.render(len(partners)), media_type=CONTENT_TYPE)

    app.add_api_route(METRICS_PATH, metrics_endpoint, methods=["GET"], include_in_schema=False)
