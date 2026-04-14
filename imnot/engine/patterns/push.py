"""
Push pattern handler.

Responsibilities:
- Handle the `push` pattern where imnot receives a submit request from a consumer,
  stores the callback URL, returns the configured status immediately, then fires an
  outbound HTTP call to the callback URL with the stored payload.
- Expose `make_push_handler` (called by the router at startup) and `fire_callback`
  (shared with the retrigger admin route in router.py).

Config fields (all under `response:` in the endpoint YAML):
    callback_url_field    — body JSON field that contains the callback URL (mutually exclusive with header)
    callback_url_header   — request header that contains the callback URL (mutually exclusive with field)
    callback_method       — HTTP method for the outbound call (default: POST)
    callback_delay_seconds — seconds to wait before firing (default: 0)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import httpx
from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, Response

from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef

logger = logging.getLogger(__name__)


def make_push_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    """Return a route handler for a push submit endpoint.

    Validates YAML config at startup — raises ValueError if callback URL source
    is missing or ambiguous.
    """
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 202)
    callback_url_field: str | None = endpoint.response.get("callback_url_field")
    callback_url_header: str | None = endpoint.response.get("callback_url_header")
    callback_method: str = endpoint.response.get("callback_method", "POST").upper()
    callback_delay: float = float(endpoint.response.get("callback_delay_seconds", 0))

    if callback_url_field and callback_url_header:
        raise ValueError(
            f"Push endpoint {endpoint.method} {endpoint.path}: "
            "only one of 'callback_url_field' or 'callback_url_header' may be set, not both."
        )
    if not callback_url_field and not callback_url_header:
        raise ValueError(
            f"Push endpoint {endpoint.method} {endpoint.path}: "
            "one of 'callback_url_field' or 'callback_url_header' is required."
        )

    async def handler(request: Request, background_tasks: BackgroundTasks) -> Response:
        # Extract callback URL from body or header
        if callback_url_field:
            try:
                body: dict[str, Any] = await request.json()
            except Exception:
                return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
            callback_url: str | None = body.get(callback_url_field)
            if not callback_url:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Missing required field '{callback_url_field}' in request body"},
                )
        else:
            callback_url = request.headers.get(callback_url_header)  # type: ignore[arg-type]
            if not callback_url:
                return JSONResponse(
                    status_code=400,
                    content={"detail": f"Missing required header '{callback_url_header}'"},
                )

        session_id: str | None = request.headers.get("X-Imnot-Session")
        push_uuid = store.store_push_request(
            partner=partner,
            datapoint=dp_name,
            session_id=session_id,
            callback_url=callback_url,
            callback_method=callback_method,
        )

        background_tasks.add_task(
            fire_callback,
            store=store,
            partner=partner,
            datapoint=dp_name,
            session_id=session_id,
            callback_url=callback_url,
            callback_method=callback_method,
            delay=callback_delay,
        )

        return JSONResponse(status_code=status_code, content={"request_id": push_uuid})

    handler.__name__ = f"push_submit_{partner}_{dp_name}"
    return handler


async def fire_callback(
    store: SessionStore,
    partner: str,
    datapoint: str,
    session_id: str | None,
    callback_url: str,
    callback_method: str,
    delay: float = 0,
) -> None:
    """Resolve the stored payload and deliver it to the callback URL.

    Exported so the retrigger admin route can call it directly.
    """
    if delay > 0:
        await asyncio.sleep(delay)

    payload = store.resolve_payload(partner, datapoint, session_id)
    if payload is None:
        logger.warning(
            "Push: no payload found for %s/%s (session=%s) — callback to %s skipped",
            partner,
            datapoint,
            session_id,
            callback_url,
        )
        return

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(callback_method, callback_url, json=payload)
        if resp.is_success:
            logger.info(
                "Push: callback delivered to %s — HTTP %d",
                callback_url,
                resp.status_code,
            )
        else:
            logger.error(
                "Push: callback to %s returned non-2xx status %d",
                callback_url,
                resp.status_code,
            )
    except Exception as exc:
        logger.error("Push: callback to %s failed: %s", callback_url, exc)
