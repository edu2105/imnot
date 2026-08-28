"""
Fetch pattern handler.

Responsibilities:
- Expose a factory function `make_fetch_handler` that accepts a partner name,
  a DatapointDef, a single EndpointDef, and a SessionStore instance, and returns
  a FastAPI route coroutine.
- The handler resolves and returns the stored payload for the datapoint, respecting
  the X-Imnot-Session header (same session logic as async step 3).
- Use this pattern for synchronous GET endpoints that return a stored payload
  with no async polling sequence (no UUID, no Location header).

Session behaviour:
  - X-Imnot-Session header present → resolve session payload → 404 if not found
  - No header → resolve global payload → 404 if not found
"""

from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from imnot.engine.rate_limiter import RateLimiter
from imnot.engine.session_store import SessionStore
from imnot.engine.validator import validate_request
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


def make_fetch_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
    limiter: RateLimiter,
) -> Callable:
    """Return a FastAPI route handler for the given fetch EndpointDef."""

    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 200)
    validate_rules = endpoint.validate
    rate_limit = endpoint.rate_limit
    capacity = rate_limit["requests_per_minute"] if rate_limit is not None else None
    refill_per_second = capacity / 60 if rate_limit is not None else None

    async def handler(request: Request) -> Response:
        if rate_limit is not None:
            key = (partner, dp_name, endpoint.method, endpoint.path)
            allowed, retry_after = limiter.check(key, capacity, refill_per_second, time.time())
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"Rate limit exceeded: {capacity} requests per minute"},
                    headers={"Retry-After": str(retry_after)},
                )

        if validate_rules is not None:
            body: Any = None
            if validate_rules.get("body"):
                try:
                    body = await request.json()
                except Exception:
                    body = None
            errors = validate_request(validate_rules, body, request.query_params, request.headers)
            if errors:
                return JSONResponse(status_code=422, content={"detail": errors})

        session_id: str | None = request.headers.get("X-Imnot-Session")
        payload: dict[str, Any] | None = store.resolve_payload(
            partner=partner,
            datapoint=dp_name,
            session_id=session_id,
        )

        if payload is None:
            detail = (
                f"No session payload found for session '{session_id}'"
                if session_id
                else f"No global payload found for {partner}/{dp_name}"
            )
            return JSONResponse(status_code=404, content={"detail": detail})

        return JSONResponse(status_code=status_code, content=payload)

    handler.__name__ = f"fetch_{partner}_{dp_name}"
    return handler
