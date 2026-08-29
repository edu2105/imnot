from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from imnot.engine.rate_limiter import RateLimiter
from imnot.engine.session_store import SessionStore, _now
from imnot.engine.validator import validate_request
from imnot.loader.yaml_loader import DatapointDef, EndpointDef


def make_paginated_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
    default_limit: int,
    pagination_ref: list[dict] | None = None,
    limiter: RateLimiter | None = None,
) -> Callable:
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 200)
    if pagination_ref is None:
        pagination_ref = [datapoint.pagination or {}]
    if limiter is None:
        limiter = RateLimiter()
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
            errors = validate_request(validate_rules, None, request.query_params, request.headers)
            if errors:
                return JSONResponse(status_code=422, content={"detail": errors})

        pagination = pagination_ref[0]
        style = pagination.get("style", "offset_limit")

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

        if style == "cursor":
            return _cursor(
                request, payload, pagination, partner, dp_name, store, default_limit, status_code, session_id
            )
        elif style == "page_number":
            return _page_number(request, payload, pagination, default_limit, status_code)
        elif style == "page_number_url":
            return _page_number_url(request, payload, pagination, default_limit, status_code)
        else:
            return _offset_limit(request, payload, pagination, default_limit, status_code)

    handler.__name__ = f"paginated_{partner}_{dp_name}"
    return handler


def _offset_limit(
    request: Request,
    payload: list,
    pagination: dict,
    default_limit: int,
    status_code: int,
) -> Response:
    items_field: str = pagination.get("items_field", "items")
    total_field: str | None = pagination.get("total_field")
    has_more_field: str | None = pagination.get("has_more_field")
    next_offset_field: str | None = pagination.get("next_offset_field")
    offset_echo_field: str | None = pagination.get("offset_echo_field")
    limit_echo_field: str | None = pagination.get("limit_echo_field")

    try:
        offset = int(request.query_params.get("offset", "0"))
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

    body: dict[str, Any] = {items_field: slice_}
    if total_field:
        body[total_field] = total
    if has_more_field:
        body[has_more_field] = has_more
    if next_offset_field:
        body[next_offset_field] = (offset + limit) if has_more else None
    if offset_echo_field:
        body[offset_echo_field] = offset
    if limit_echo_field:
        body[limit_echo_field] = limit

    return JSONResponse(status_code=status_code, content=body)


def _cursor(
    request: Request,
    payload: list,
    pagination: dict,
    partner: str,
    dp_name: str,
    store: SessionStore,
    default_limit: int,
    status_code: int,
    session_id: str | None,
) -> Response:
    items_field: str = pagination.get("items_field", "items")
    cursor_field: str = pagination["cursor_field"]
    cursor_ttl_seconds: int = int(pagination.get("cursor_ttl_seconds", 3600))
    total_field: str | None = pagination.get("total_field")
    has_more_field: str | None = pagination.get("has_more_field")

    try:
        raw_limit = request.query_params.get("limit")
        limit = int(raw_limit) if raw_limit is not None else default_limit
    except (ValueError, TypeError):
        limit = default_limit
    if limit <= 0:
        limit = default_limit

    raw_cursor = request.query_params.get("cursor", "").strip()
    if raw_cursor:
        offset = store.resolve_cursor(raw_cursor)
        if offset is None:
            return JSONResponse(status_code=400, content={"detail": "Cursor expired or not found"})
    else:
        offset = 0

    total = len(payload)
    slice_ = payload[offset : offset + limit]
    has_more = (offset + limit) < total
    next_offset = offset + limit

    if has_more:
        next_cursor: str | None = store.store_cursor(partner, dp_name, session_id, next_offset, cursor_ttl_seconds)
    else:
        next_cursor = None

    store.expire_cursors(_now())

    body: dict[str, Any] = {items_field: slice_, cursor_field: next_cursor}
    if total_field:
        body[total_field] = total
    if has_more_field:
        body[has_more_field] = has_more

    return JSONResponse(status_code=status_code, content=body)


def _slice_by_page(
    request: Request,
    payload: list,
    pagination: dict,
    default_limit: int,
) -> tuple[int, int, int, list, int, bool]:
    page_param: str = pagination.get("page_param", "page")
    size_param: str = pagination.get("size_param", "size")

    try:
        page = int(request.query_params.get(page_param, "1"))
    except (ValueError, TypeError):
        page = 1
    if page < 1:
        page = 1

    try:
        raw_size = request.query_params.get(size_param)
        size = int(raw_size) if raw_size is not None else default_limit
    except (ValueError, TypeError):
        size = default_limit
    if size <= 0:
        size = default_limit

    total = len(payload)
    offset = (page - 1) * size
    slice_ = payload[offset : offset + size]
    has_more = (offset + size) < total
    return page, size, offset, slice_, total, has_more


def _page_number(
    request: Request,
    payload: list,
    pagination: dict,
    default_limit: int,
    status_code: int,
) -> Response:
    items_field: str = pagination.get("items_field", "items")
    total_field: str | None = pagination.get("total_field")
    has_more_field: str | None = pagination.get("has_more_field")

    _page, _size, _offset, slice_, total, has_more = _slice_by_page(request, payload, pagination, default_limit)

    body: dict[str, Any] = {items_field: slice_}
    if total_field:
        body[total_field] = total
    if has_more_field:
        body[has_more_field] = has_more

    return JSONResponse(status_code=status_code, content=body)


def _page_number_url(
    request: Request,
    payload: list,
    pagination: dict,
    default_limit: int,
    status_code: int,
) -> Response:
    items_field: str = pagination.get("items_field", "items")
    total_field: str | None = pagination.get("total_field")
    next_url_field: str = pagination["next_url_field"]
    previous_url_field: str = pagination["previous_url_field"]
    page_param: str = pagination.get("page_param", "page")
    size_param: str = pagination.get("size_param", "size")

    page, size, offset, slice_, total, has_more = _slice_by_page(request, payload, pagination, default_limit)

    def _build_url(target_page: int) -> str:
        base_url = str(request.app.state.base_url).rstrip("/")
        query = dict(request.query_params)
        query[page_param] = str(target_page)
        query.setdefault(size_param, str(size))
        return f"{base_url}{request.url.path}?{urlencode(query)}"

    body: dict[str, Any] = {
        items_field: slice_,
        next_url_field: _build_url(page + 1) if has_more else None,
        previous_url_field: _build_url(page - 1) if page > 1 else None,
    }
    if total_field:
        body[total_field] = total

    return JSONResponse(status_code=status_code, content=body)
