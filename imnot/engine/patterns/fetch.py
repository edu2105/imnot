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

from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


def make_fetch_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    """Return a FastAPI route handler for the given fetch EndpointDef."""

    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 200)

    async def handler(request: Request) -> Response:
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
