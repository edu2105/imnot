"""
Fault injection: per-endpoint ``delay_ms`` and ``fail:`` blocks.

Applied as a wrapper around every consumer handler at registration time (``with_faults``), so all
six patterns get it the same way. Order on each request: delay, then the simulated failure, then
the normal handler (which runs ``rate_limit:`` and ``validate:`` itself).

``fail.first_n`` counts calls per ``(method, path, session)`` in memory (``app.state.fault_counters``);
``DELETE /imnot/admin/faults`` or a restart resets it. Like ``validate:`` and ``rate_limit:``, the
config is captured when the route is registered: editing it needs a restart.
"""

from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable

from fastapi.responses import JSONResponse

from imnot.loader.yaml_loader import EndpointDef

DEFAULT_FAIL_BODY = {"detail": "Simulated failure (imnot fail: block)"}


def with_faults(handler: Callable, endpoint: EndpointDef, counters: dict[tuple, int]) -> Callable:
    """Return *handler* wrapped with the endpoint's delay/fail behaviour, or *handler* unchanged."""
    delay_ms: int = endpoint.delay_ms or 0
    fail: dict[str, Any] | None = endpoint.fail
    if not delay_ms and not fail:
        return handler

    @functools.wraps(handler)  # keeps the signature FastAPI inspects (request, background_tasks, …)
    async def wrapped(**kwargs: Any) -> Any:
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
        if fail:
            request = kwargs["request"]
            first_n = fail.get("first_n")
            key = (endpoint.method, endpoint.path, request.headers.get("X-Imnot-Session"))
            calls = counters.get(key, 0)
            counters[key] = calls + 1
            if first_n is None or calls < first_n:
                headers = {str(k): str(v) for k, v in (fail.get("headers") or {}).items()}
                body = fail["body"] if "body" in fail else DEFAULT_FAIL_BODY
                return JSONResponse(status_code=fail["status"], content=body, headers=headers)
        return await handler(**kwargs)

    return wrapped
