from __future__ import annotations

from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


def make_paginated_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
    default_limit: int,
) -> Callable:
    dp_name = datapoint.name
    pagination = datapoint.pagination or {}
    items_field: str = pagination.get("items_field", "items")
    total_field: str | None = pagination.get("total_field")
    has_more_field: str | None = pagination.get("has_more_field")
    next_offset_field: str | None = pagination.get("next_offset_field")
    status_code: int = endpoint.response.get("status", 200)

    async def handler(request: Request) -> Response:
        session_id: str | None = request.headers.get("X-Imnot-Session")
        payload: Any = store.resolve_payload(
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

        if not isinstance(payload, list):
            return JSONResponse(
                status_code=422,
                content={"detail": "Payload must be a JSON array for the paginated pattern"},
            )

        try:
            raw_offset = request.query_params.get("offset", "0")
            offset = int(raw_offset)
        except (ValueError, TypeError):
            offset = 0
        if offset < 0:
            offset = 0

        try:
            raw_limit = request.query_params.get("limit")
            limit = int(raw_limit) if raw_limit is not None else default_limit
        except (ValueError, TypeError):
            limit = default_limit
        if limit <= 0:
            limit = default_limit

        total = len(payload)
        slice_ = payload[offset : offset + limit]
        has_more = (offset + limit) < total
        next_offset = offset + limit

        body: dict[str, Any] = {items_field: slice_}
        if total_field:
            body[total_field] = total
        if has_more_field:
            body[has_more_field] = has_more
        if next_offset_field:
            body[next_offset_field] = next_offset if has_more else None

        return JSONResponse(status_code=status_code, content=body)

    handler.__name__ = f"paginated_{partner}_{dp_name}"
    return handler
