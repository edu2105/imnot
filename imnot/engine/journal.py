"""
Request journal: records what consumers send to the mock routes.

A pure ASGI middleware (not BaseHTTPMiddleware): it reads the request body once, replays it to the
app unchanged, and sees the final response status. Entries are stored by
``SessionStore.log_request`` and served by ``GET /imnot/admin/requests``.

Not recorded: imnot's own routes (``/imnot/*``), ``/healthz`` and FastAPI's docs.
Requests that match no mock route are recorded with ``partner = None``: that is usually the
answer to "why is my integration getting 404s?".
"""

from __future__ import annotations

import logging
import re
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 64 * 1024
_SKIP_PREFIXES = ("/imnot/", "/healthz", "/docs", "/redoc", "/openapi.json")
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key"}
_SECRET_WORDS = re.compile(r"token|secret|password|api-key|apikey", re.IGNORECASE)
REDACTED = "[redacted]"


def redact_headers(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw_name, raw_value in headers:
        name = raw_name.decode("latin-1").lower()
        value = raw_value.decode("latin-1")
        out[name] = REDACTED if name in _SECRET_HEADERS or _SECRET_WORDS.search(name) else value
    return out


class JournalMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] != "http" or path.startswith(_SKIP_PREFIXES) or path == "/imnot":
            await self.app(scope, receive, send)
            return

        # Read the whole request body up front (handlers that ignore it, and unmatched routes, never
        # call receive), then replay it to the app unchanged.
        chunks: list[bytes] = []
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        full_body = b"".join(chunks)
        replayed = False

        async def replay_receive() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            return await receive()

        status: dict[str, int] = {}

        async def send_and_watch(message: Message) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, replay_receive, send_and_watch)
        finally:
            truncated = len(full_body) > MAX_BODY_BYTES
            self._record(scope, full_body[:MAX_BODY_BYTES], truncated, status.get("code"))

    @staticmethod
    def _record(scope: Scope, body: bytes, truncated: bool, status: int | None) -> None:
        app: Any = scope.get("app")
        store = getattr(getattr(app, "state", None), "store", None)
        if store is None or getattr(store, "_conn", None) is None:  # app built but not started (tests)
            return
        method: str = scope.get("method", "")
        partner = datapoint = None
        route = scope.get("route")
        route_path: str | None = getattr(route, "path", None)
        if route_path is not None:
            canonical = route_path[:-1] if route_path.endswith("/") and route_path != "/" else route_path
            owner = app.state.registered_routes.get((method, canonical))
            if owner:
                partner, datapoint = owner.split("/", 1)
        headers = redact_headers(scope.get("headers", []))
        try:
            store.log_request(
                {
                    "partner": partner,
                    "datapoint": datapoint,
                    "session_id": headers.get("x-imnot-session"),
                    "method": method,
                    "path": scope.get("path", ""),
                    "query": scope.get("query_string", b"").decode("latin-1"),
                    "headers": headers,
                    "body": body.decode("utf-8", errors="replace"),
                    "body_truncated": truncated,
                    "status": status,
                }
            )
        except Exception:  # the journal must never break a mock response
            logger.exception("Request journal: failed to record %s %s", method, scope.get("path"))
