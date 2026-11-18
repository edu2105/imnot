"""
Polling pattern handler.

Responsibilities:
- Expose a factory function `make_async_handlers` that accepts a partner name,
  a DatapointDef, and a SessionStore instance, and returns a dict mapping
  step number → FastAPI route coroutine for each polling step.

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

from imnot.engine.patterns import no_payload_response
from imnot.engine.session_store import SessionStore
from imnot.engine.templating import render_response
from imnot.engine.validator import validate_request
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
            handler = _make_static_handler(partner, datapoint, endpoint, store)
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
    validate_rules = endpoint.validate

    # The loader (``_parse_endpoint``) guarantees an id source when generates_id is true.

    async def handler(request: Request) -> Response:
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

    handler.__name__ = f"polling_submit_{partner}_{dp_name}"
    return handler


# ---------------------------------------------------------------------------
# Pending responses (response.pending: {times, status, body, headers})
# ---------------------------------------------------------------------------


def _make_pending_check(endpoint: EndpointDef) -> Callable[[str], Response | None]:
    """Return ``check(request_id)``: the pending response for the first ``times`` calls per id, else None.

    Counts live in memory per handler and per request id, so every new submit starts from zero.
    """
    pending: dict[str, Any] | None = endpoint.response.get("pending")
    counts: dict[str, int] = {}

    def check(request_id: str) -> Response | None:
        if not pending:
            return None
        seen = counts.get(request_id, 0)
        if seen >= pending["times"]:
            return None
        counts[request_id] = seen + 1
        status = pending.get("status", 202)
        headers = {str(k): str(v) for k, v in (pending.get("headers") or {}).items()}
        if "body" in pending:
            return JSONResponse(status_code=status, content=pending["body"], headers=headers)
        return Response(status_code=status, headers=headers)

    return check


def _unknown_id_response(async_uuid: str | None) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": f"Unknown request ID: {async_uuid}"})


# ---------------------------------------------------------------------------
# Static handler
# ---------------------------------------------------------------------------


def _make_static_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    status_code: int = endpoint.response.get("status", 200)
    extra_headers: dict[str, str] = endpoint.response.get("headers") or {}
    static_body: dict[str, Any] | None = endpoint.response.get("body")
    validate_rules = endpoint.validate
    has_id = "{id}" in endpoint.path
    pending_check = _make_pending_check(endpoint)

    async def handler(request: Request) -> Response:
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
        if has_id:
            # A status step for an id that was never submitted must not report it as done.
            async_uuid: str = request.path_params["id"]
            if store.get_async_request(async_uuid) is None:
                return _unknown_id_response(async_uuid)
            pending = pending_check(async_uuid)
            if pending is not None:
                return pending
        if static_body is not None:
            content = await render_response(static_body, request)
            return JSONResponse(status_code=status_code, content=content, headers=extra_headers)
        return Response(status_code=status_code, headers=extra_headers)

    handler.__name__ = f"polling_static_{partner}_{datapoint.name}_{endpoint.step}"
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
    validate_rules = endpoint.validate
    pending_check = _make_pending_check(endpoint)

    async def handler(request: Request) -> Response:
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

        async_uuid: str | None = request.path_params.get("id")
        row = store.get_async_request(async_uuid)
        if row is None:
            return _unknown_id_response(async_uuid)
        pending = pending_check(async_uuid)
        if pending is not None:
            return pending

        session_id: str | None = request.headers.get("X-Imnot-Session")
        payload: dict[str, Any] | None = store.resolve_payload(
            partner=partner,
            datapoint=dp_name,
            session_id=session_id,
        )

        if payload is None:
            return no_payload_response(partner, dp_name, session_id)

        return JSONResponse(status_code=status_code, content=payload)

    handler.__name__ = f"polling_fetch_{partner}_{dp_name}"
    return handler
