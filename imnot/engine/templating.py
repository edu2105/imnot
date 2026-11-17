"""
Response templating: ``{{path.x}}``, ``{{query.x}}``, ``{{headers.x}}``, ``{{body.a.b}}`` and
``{{request_id}}`` inside string values of a response body or callback payload.

Rules:
- Only string values are rendered, recursively through dicts and lists. Keys are not.
- A string that is exactly one placeholder keeps the value's JSON type (``"{{body.qty}}"`` → ``3``);
  inside a longer string the value is inserted as text.
- A placeholder whose value is missing renders as ``""`` (or ``null`` when it is the whole string).
- Unknown roots (``{{vary}}``, ``{{anything}}``) are left untouched, so existing bodies that happen
  to contain braces don't change.
"""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request

_PLACEHOLDER = re.compile(r"\{\{\s*(request_id|(?:path|query|headers|body)(?:\.[^\s{}.]+)+)\s*\}\}")
_MISSING = object()


def has_placeholders(value: Any) -> bool:
    """True if any string inside *value* contains a recognised placeholder (cheap pre-check)."""
    if isinstance(value, str):
        return _PLACEHOLDER.search(value) is not None
    if isinstance(value, dict):
        return any(has_placeholders(v) for v in value.values())
    if isinstance(value, list):
        return any(has_placeholders(v) for v in value)
    return False


_BODY_PLACEHOLDER = re.compile(r"\{\{\s*body\.")


def uses_body(value: Any) -> bool:
    """True if a placeholder reads from the request body (so the handler must parse it)."""
    return _BODY_PLACEHOLDER.search(json.dumps(value)) is not None


def request_context(request: Request, body: Any = None, request_id: str | None = None) -> dict[str, Any]:
    return {
        "path": dict(request.path_params),
        "query": dict(request.query_params),
        "headers": {k.lower(): v for k, v in request.headers.items()},
        "body": body,
        "request_id": request_id,
    }


def _lookup(context: dict[str, Any], expr: str) -> Any:
    if expr == "request_id":
        value = context.get("request_id")
        return _MISSING if value is None else value
    root, *parts = expr.split(".")
    value: Any = context.get(root)
    if root == "headers":
        parts = [p.lower() for p in parts]
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return _MISSING
    return value


def render(value: Any, context: dict[str, Any]) -> Any:
    """Return a copy of *value* with placeholders replaced from *context*."""
    if isinstance(value, dict):
        return {k: render(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, context) for v in value]
    if not isinstance(value, str):
        return value

    whole = _PLACEHOLDER.fullmatch(value.strip())
    if whole is not None:
        found = _lookup(context, whole.group(1))
        return None if found is _MISSING else found

    def _sub(match: re.Match[str]) -> str:
        found = _lookup(context, match.group(1))
        if found is _MISSING or found is None:
            return ""
        return found if isinstance(found, str) else json.dumps(found)

    return _PLACEHOLDER.sub(_sub, value)
