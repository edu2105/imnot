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

from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


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
            handler = _make_static_handler(partner, datapoint, endpoint)
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
        session_id: str | None = request.headers.get("X-Imnot-Session")
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
# Static handler
# ---------------------------------------------------------------------------


def _make_static_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
) -> Callable:
    status_code: int = endpoint.response.get("status", 200)
    extra_headers: dict[str, str] = endpoint.response.get("headers") or {}
    static_body: dict[str, Any] | None = endpoint.response.get("body")

    if static_body is not None:
        async def handler(request: Request) -> Response:
            return JSONResponse(
                status_code=status_code,
                content=static_body,
                headers=extra_headers,
            )
    else:
        async def handler(request: Request) -> Response:
            return Response(status_code=status_code, headers=extra_headers)

    handler.__name__ = f"async_static_{partner}_{datapoint.name}_{endpoint.step}"
    return handler


# ---------------------------------------------------------------------------
# Fetch handler
# ---------------------------------------------------------------------------


def _make_fetch_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 200)

    async def handler(request: Request) -> Response:
        async_uuid: str | None = request.path_params.get("id")
        row = store.get_async_request(async_uuid)
        if row is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Unknown request ID: {async_uuid}"},
            )

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

    handler.__name__ = f"async_fetch_{partner}_{dp_name}"
    return handler
