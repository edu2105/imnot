"""
Callback pattern handler.

Responsibilities:
- Handle the `callback` pattern where imnot receives a submit request from a consumer,
  stores the callback URL, returns the configured status immediately, then fires an
  outbound HTTP call to the callback URL with the stored payload.
- Expose `make_push_handler` (called by the router at startup) and `fire_callback`
  (shared with the retrigger admin route in router.py).

Config fields (all under `response:` in the endpoint YAML):
    callback_url_field    — body JSON field that contains the callback URL (mutually exclusive with header)
    callback_url_header   — request header that contains the callback URL (mutually exclusive with field)
    callback_method       — HTTP method for the outbound call (default: POST)
    callback_delay_seconds — seconds to wait before firing (default: 0)
    callback_headers      — extra headers, templated ({{request_id}}, {{body.x}}); a header whose
                            value renders empty or null is not sent
    callback_signature    — {secret, header, algorithm}: HMAC of the exact JSON bytes sent; with a
                            signature the body goes as compact JSON via content=, without one via json=
    callback_retries      — {attempts, backoff_seconds}: retry on non-2xx / network error, linear backoff

Delivery settings are captured when the route is registered (restart to change them). The retrigger
admin route reads them from the datapoint's first endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Callable

import httpx
from fastapi import BackgroundTasks, Request
from fastapi.responses import JSONResponse, Response

from imnot.engine.egress import CallbackPolicy
from imnot.engine.errors import validation_error_response
from imnot.engine.metrics import Metrics, get_metrics
from imnot.engine.session_store import SessionStore
from imnot.engine.templating import has_placeholders, render, request_context
from imnot.engine.validator import validate_request
from imnot.loader.yaml_loader import DatapointDef, EndpointDef

DEFAULT_SIGNATURE_HEADER = "X-Imnot-Signature"

logger = logging.getLogger(__name__)


def delivery_config(response: dict[str, Any]) -> dict[str, Any]:
    """The callback delivery settings from an endpoint's ``response`` block (see fire_callback)."""
    return {
        "headers": response.get("callback_headers"),
        "signature": response.get("callback_signature"),
        "retries": response.get("callback_retries"),
    }


def make_push_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    """Return a route handler for a push submit endpoint.

    The loader (``_parse_endpoint``) guarantees exactly one callback URL source is set.
    """
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 202)
    callback_url_field: str | None = endpoint.response.get("callback_url_field")
    callback_url_header: str | None = endpoint.response.get("callback_url_header")
    callback_method: str = endpoint.response.get("callback_method", "POST").upper()
    callback_delay: float = float(endpoint.response.get("callback_delay_seconds", 0))
    delivery = delivery_config(endpoint.response)
    validate_rules = endpoint.validate

    async def handler(request: Request, background_tasks: BackgroundTasks) -> Response:
        # Parse body unconditionally for push (always has a body when callback_url_field is set)
        parsed_body: dict[str, Any] | None = None
        if callback_url_field:
            try:
                parsed_body = await request.json()
            except Exception:
                return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})

        # Validate before extracting callback URL
        if validate_rules is not None:
            errors = validate_request(
                validate_rules,
                parsed_body,
                request.query_params,
                request.headers,
            )
            if errors:
                return validation_error_response(validate_rules, errors)

        # Extract callback URL from body or header
        if callback_url_field:
            body: dict[str, Any] = parsed_body or {}
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

        policy: CallbackPolicy = getattr(request.app.state, "callback_policy", None) or CallbackPolicy()
        problem = await policy.problem(callback_url)
        if problem:
            return JSONResponse(status_code=422, content={"detail": f"Callback URL {problem}"})

        if parsed_body is None:
            # Header mode never needed the body; parse it anyway so {{body.x}} works in the callback.
            try:
                parsed_body = await request.json()
            except Exception:
                parsed_body = None

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
            context=request_context(request, parsed_body, request_id=push_uuid),
            delivery=delivery,
            policy=policy,
            metrics=get_metrics(request.app),
        )

        return JSONResponse(status_code=status_code, content={"request_id": push_uuid})

    handler.__name__ = f"callback_submit_{partner}_{dp_name}"
    return handler


async def fire_callback(
    store: SessionStore,
    partner: str,
    datapoint: str,
    session_id: str | None,
    callback_url: str,
    callback_method: str,
    delay: float = 0,
    context: dict[str, Any] | None = None,
    delivery: dict[str, Any] | None = None,
    policy: CallbackPolicy | None = None,
    metrics: Metrics | None = None,
) -> None:
    """Resolve the stored payload, render its placeholders with *context*, and deliver it.

    Exported so the retrigger admin route can call it directly. *context* comes from the submit
    request (``templating.request_context``); a retrigger only knows the ``request_id``.
    *delivery* is ``delivery_config(endpoint.response)``: extra headers, an HMAC signature and retries.
    *policy* (``egress.CallbackPolicy``) is checked again before every attempt, after a fresh DNS lookup.
    *metrics*, when on, counts the outcome: delivered, failed (after the last attempt), refused or skipped.
    """

    def outcome(result: str) -> None:
        if metrics is not None:
            metrics.observe_callback(partner, datapoint, result)

    policy = policy or CallbackPolicy()
    if delay > 0:
        await asyncio.sleep(delay)

    payload = store.resolve_payload(partner, datapoint, session_id)
    if payload is None:
        logger.warning(
            "Callback: no payload found for %s/%s (session=%s) — callback to %s skipped",
            partner,
            datapoint,
            session_id,
            callback_url,
        )
        outcome("skipped")
        return
    if context is not None and has_placeholders(payload):
        payload = render(payload, context)

    delivery = delivery or {}
    rendered_headers = render(delivery.get("headers") or {}, context or {})
    # A header whose placeholder has no value (e.g. {{body.x}} on a retrigger) is left out, not sent as "None".
    headers = {str(k): str(v) for k, v in rendered_headers.items() if v not in (None, "")}
    request_kwargs: dict[str, Any] = {"json": payload}
    signature = delivery.get("signature")
    if signature:
        # Sign the exact bytes sent, so the receiver can verify them like a real partner webhook.
        body = json.dumps(payload, separators=(",", ":")).encode()
        algorithm = signature.get("algorithm", "sha256")
        digest = hmac.new(str(signature["secret"]).encode(), body, getattr(hashlib, algorithm)).hexdigest()
        headers[signature.get("header", DEFAULT_SIGNATURE_HEADER)] = f"{algorithm}={digest}"
        headers.setdefault("Content-Type", "application/json")
        request_kwargs = {"content": body}
    retries = delivery.get("retries") or {}
    attempts = int(retries.get("attempts", 1))
    backoff = float(retries.get("backoff_seconds", 1))

    for attempt in range(1, attempts + 1):
        problem = await policy.problem(callback_url)
        if problem:
            logger.error("Callback: to %s refused: the URL %s", callback_url, problem)
            outcome("refused")
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.request(callback_method, callback_url, headers=headers, **request_kwargs)
            if resp.is_success:
                logger.info("Callback: delivered to %s — HTTP %d (attempt %d)", callback_url, resp.status_code, attempt)
                outcome("delivered")
                return
            logger.error(
                "Callback: to %s returned non-2xx status %d (attempt %d/%d)",
                callback_url,
                resp.status_code,
                attempt,
                attempts,
            )
        except Exception as exc:
            logger.error("Callback: to %s failed: %s (attempt %d/%d)", callback_url, exc, attempt, attempts)
        if attempt < attempts:
            await asyncio.sleep(backoff * attempt)  # linear backoff: 1×, 2×, 3× backoff_seconds
    outcome("failed")
