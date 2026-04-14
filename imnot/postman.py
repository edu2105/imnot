"""
Postman collection generator.

Responsibilities:
- Build a Postman collection v2.1 dict from a list of PartnerDef objects.
- Exported as `build_postman_collection(partners)` — called by both the CLI
  (`imnot export postman`) and the admin endpoint (`GET /imnot/admin/postman`).

Collection structure:
    imnot                           ← top-level collection
    └── {partner}                   ← one folder per partner
        └── {datapoint}             ← one sub-folder per datapoint
            ├── consumer requests   ← one per EndpointDef
            └── Admin               ← payload-pattern datapoints only
                ├── POST .../payload
                ├── GET  .../payload
                ├── POST .../payload/session
                ├── GET  .../payload/session/:session_id
                └── POST .../push/:request_id/retrigger  (push only)
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from imnot.loader.yaml_loader import DatapointDef, EndpointDef, PartnerDef

_PAYLOAD_PATTERNS = {"fetch", "async", "push"}
_BODY_METHODS = {"POST", "PUT", "PATCH"}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_postman_collection(partners: list[PartnerDef]) -> dict[str, Any]:
    """Return a Postman collection v2.1 dict for *partners*."""
    return {
        "info": {
            "_postman_id": str(uuid.uuid4()),
            "name": "imnot",
            "description": "Auto-generated collection for imnot mock server endpoints.",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {
                "key": "baseUrl",
                "value": "http://localhost:8000",
                "type": "string",
                "description": "Base URL of the imnot server",
            }
        ],
        "item": [_partner_folder(p) for p in partners],
    }


def collection_stats(partners: list[PartnerDef]) -> dict[str, Any]:
    """Return summary counts for CLI output."""
    consumer = sum(len(dp.endpoints) for p in partners for dp in p.datapoints)
    admin = sum(
        (5 if dp.pattern == "push" else 4)
        for p in partners
        for dp in p.datapoints
        if dp.pattern in _PAYLOAD_PATTERNS
    )
    return {
        "partners": len(partners),
        "partner_names": [p.partner for p in partners],
        "consumer_requests": consumer,
        "admin_requests": admin,
        "total_requests": consumer + admin,
    }


# ---------------------------------------------------------------------------
# Folder builders
# ---------------------------------------------------------------------------


def _partner_folder(partner: PartnerDef) -> dict[str, Any]:
    return {
        "name": partner.partner,
        "description": partner.description or "",
        "item": [_datapoint_folder(partner.partner, dp) for dp in partner.datapoints],
    }


def _datapoint_folder(partner_name: str, dp: DatapointDef) -> dict[str, Any]:
    items: list[dict[str, Any]] = [_consumer_request(dp, ep) for ep in dp.endpoints]
    if dp.pattern in _PAYLOAD_PATTERNS:
        items.append(_admin_folder(partner_name, dp))
    return {
        "name": dp.name,
        "description": dp.description or "",
        "item": items,
    }


# ---------------------------------------------------------------------------
# Consumer request builder
# ---------------------------------------------------------------------------


def _consumer_request(dp: DatapointDef, ep: EndpointDef) -> dict[str, Any]:
    headers: list[dict[str, Any]] = []
    body: dict[str, Any] | None = None

    if ep.method in _BODY_METHODS:
        body_content = _consumer_body(dp, ep)
        if body_content is not None:
            headers.append(_header("Content-Type", "application/json"))
            body = _raw_body(body_content)

    # push with callback_url_header: add the header pre-filled with a placeholder
    if dp.pattern == "push":
        header_name: str | None = ep.response.get("callback_url_header")
        if header_name:
            headers.append({
                "key": header_name,
                "value": "http://your-service/webhook",
                "description": "Callback URL — Mirage will POST the stored payload here",
            })

    # X-Imnot-Session — present but disabled for payload-pattern endpoints
    if dp.pattern in _PAYLOAD_PATTERNS:
        headers.append({
            "key": "X-Imnot-Session",
            "value": "",
            "description": "Optional: set to isolate payloads per test session",
            "disabled": True,
        })

    request: dict[str, Any] = {
        "method": ep.method,
        "header": headers,
        "url": _build_url(ep.path),
    }
    if body:
        request["body"] = body

    return {"name": f"{ep.method} {ep.path}", "request": request}


def _consumer_body(dp: DatapointDef, ep: EndpointDef) -> dict[str, Any] | None:
    """Return a pre-filled body for consumer endpoints where Mirage knows the shape."""
    if dp.pattern == "push":
        field: str | None = ep.response.get("callback_url_field")
        if field:
            return {field: "http://your-service/webhook"}
    return None


# ---------------------------------------------------------------------------
# Admin folder builder
# ---------------------------------------------------------------------------


def _admin_folder(partner_name: str, dp: DatapointDef) -> dict[str, Any]:
    base = f"/imnot/admin/{partner_name}/{dp.name}/payload"
    placeholder = _raw_body({"example": "replace with your payload"})
    ct = _header("Content-Type", "application/json")

    items: list[dict[str, Any]] = [
        {
            "name": f"POST {base}",
            "request": {
                "method": "POST",
                "header": [ct],
                "body": placeholder,
                "url": _build_url(base),
            },
        },
        {
            "name": f"GET {base}",
            "request": {"method": "GET", "header": [], "url": _build_url(base)},
        },
        {
            "name": f"POST {base}/session",
            "request": {
                "method": "POST",
                "header": [ct],
                "body": placeholder,
                "url": _build_url(f"{base}/session"),
            },
        },
        {
            "name": f"GET {base}/session/:session_id",
            "request": {
                "method": "GET",
                "header": [],
                "url": _build_url(f"{base}/session/:session_id"),
            },
        },
    ]

    if dp.pattern == "push":
        retrigger = f"/imnot/admin/{partner_name}/{dp.name}/push/:request_id/retrigger"
        items.append({
            "name": f"POST {retrigger}",
            "request": {"method": "POST", "header": [], "url": _build_url(retrigger)},
        })

    return {
        "name": "Admin",
        "description": f"Payload management for {partner_name}/{dp.name}",
        "item": items,
    }


# ---------------------------------------------------------------------------
# URL / header / body helpers
# ---------------------------------------------------------------------------


def _build_url(path: str) -> dict[str, Any]:
    """Build a Postman URL object from a path string.

    Converts ``{param}`` placeholders to ``:param`` (Postman path variable style).
    Colon-prefixed segments are recorded in the ``variable`` array.
    """
    postman_path = path.replace("{", ":").replace("}", "")
    raw = f"{{{{baseUrl}}}}{postman_path}"
    segments = [s for s in postman_path.split("/") if s]
    variables = [
        {"key": seg[1:], "value": "", "description": ""}
        for seg in segments
        if seg.startswith(":")
    ]
    url: dict[str, Any] = {"raw": raw, "host": ["{{baseUrl}}"], "path": segments}
    if variables:
        url["variable"] = variables
    return url


def _header(key: str, value: str) -> dict[str, str]:
    return {"key": key, "value": value}


def _raw_body(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "raw",
        "raw": json.dumps(content, indent=2),
        "options": {"raw": {"language": "json"}},
    }
