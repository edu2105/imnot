"""
Async pattern handler.

Responsibilities:
- Expose a factory function `make_async_handlers` that accepts a partner name,
  a DatapointDef, and a SessionStore instance, and returns a dict mapping
  step number → FastAPI route coroutine for each async step.

Handler types are determined at startup from response config flags:
  generates_id: true  → submit handler (generates UUID, persists it, returns it)
  returns_payload: true → fetch handler (validates UUID, returns stored payload)
  neither flag         → static handler (returns status/headers/body verbatim)

ID delivery (submit handler):
  id_header + id_header_value  → UUID injected into a response header
  id_body_field                → UUID injected into a JSON response body field
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import DatapointDef, EndpointDef


def make_async_handlers(
    partner: str,
    datapoint: DatapointDef,
    store: SessionStore,
) -> dict[int, Callable]:
    """Return {step: handler} for all async endpoints in *datapoint*."""
    handlers: dict[int, Callable] = {}
    for endpoint in datapoint.endpoints:
        if endpoint.response.get("generates_id"):
            handler = _make_submit_handler(partner, datapoint, endpoint, store)
        elif endpoint.response.get("returns_payload"):
            handler = _make_fetch_handler(partner, datapoint, endpoint, store)
        else:
            handler = _make_static_handler(datapoint, endpoint)
        handlers[endpoint.step] = handler
    return handlers


# ---------------------------------------------------------------------------
# Submit handler
# ---------------------------------------------------------------------------


def _make_submit_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 202)
    id_header: str | None = endpoint.response.get("id_header")
    id_header_value: str | None = endpoint.response.get("id_header_value")
    id_body_field: str | None = endpoint.response.get("id_body_field")
    static_body: dict[str, Any] = endpoint.response.get("body") or {}

    if not (id_header and id_header_value) and not id_body_field:
        raise ValueError(
            f"Endpoint step {endpoint.step} has generates_id=true but neither "
            "'id_header'/'id_header_value' nor 'id_body_field' is set"
        )

    async def handler(request: Request) -> Response:
        session_id: str | None = request.headers.get("X-Mirage-Session")
        async_uuid = store.register_async_request(
            partner=partner,
            datapoint=dp_name,
            session_id=session_id,
        )
        if id_header and id_header_value:
            header_val = id_header_value.replace("{id}", async_uuid)
            return Response(
                status_code=status_code,
                headers={id_header: header_val},
            )
        # id_body_field delivery
        body = {**static_body, id_body_field: async_uuid}
        return JSONResponse(status_code=status_code, content=body)

    handler.__name__ = f"async_submit_{partner}_{dp_name}"
    return handler


# ---------------------------------------------------------------------------
# Static handler  (placeholder — implemented in Task 3)
# ---------------------------------------------------------------------------


def _make_static_handler(
    datapoint: DatapointDef,
    endpoint: EndpointDef,
) -> Callable:
    async def handler(request: Request) -> Response:
        raise NotImplementedError("static handler not yet implemented")

    handler.__name__ = f"async_static_{datapoint.name}_{endpoint.step}"
    return handler


# ---------------------------------------------------------------------------
# Fetch handler  (placeholder — implemented in Task 3)
# ---------------------------------------------------------------------------


def _make_fetch_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    async def handler(request: Request) -> Response:
        raise NotImplementedError("fetch handler not yet implemented")

    handler.__name__ = f"async_fetch_{partner}_{datapoint.name}_{endpoint.step}"
    return handler
