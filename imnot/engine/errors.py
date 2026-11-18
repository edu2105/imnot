"""
Error responses for ``validate:`` and ``rate_limit:``, with an optional partner-shaped ``error:`` block.

Without ``error:`` the responses keep imnot's shape (422 ``{"detail": [...]}``, 429
``{"detail": "Rate limit exceeded: …"}`` + ``Retry-After``). With it, the YAML decides status,
body and headers, so a mock can answer exactly like the real partner::

    validate:
      body: {id: {required: true}}
      error:
        status: 400
        body: {code: INVALID_REQUEST, message: "{{message}}", details: "{{errors}}"}

Placeholders (in string values of ``body`` and ``headers``):
- ``{{errors}}``: the list of validation errors (whole string → the JSON list itself)
- ``{{message}}``: the same errors joined with "; "
- ``{{retry_after}}`` / ``{{limit}}``: seconds until the next token / requests per minute (rate limit)
"""

from __future__ import annotations

import re
from typing import Any

from fastapi.responses import JSONResponse

_PLACEHOLDER = re.compile(r"\{\{\s*(errors|message|retry_after|limit)\s*\}\}")


def _render(value: Any, values: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _render(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, values) for v in value]
    if not isinstance(value, str):
        return value
    whole = _PLACEHOLDER.fullmatch(value.strip())
    if whole is not None and whole.group(1) in values:
        return values[whole.group(1)]
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), value)


def _from_spec(spec: dict[str, Any], values: dict[str, Any], base_headers: dict[str, str]) -> JSONResponse:
    headers = dict(base_headers)
    headers.update({str(k): str(v) for k, v in _render(spec.get("headers") or {}, values).items()})
    return JSONResponse(status_code=spec["status"], content=_render(spec.get("body"), values), headers=headers)


def validation_error_response(validate: dict[str, Any] | None, errors: list[str]) -> JSONResponse:
    spec = (validate or {}).get("error")
    if not spec:
        return JSONResponse(status_code=422, content={"detail": errors})
    return _from_spec(spec, {"errors": errors, "message": "; ".join(errors)}, {})


def rate_limit_response(rate_limit: dict[str, Any], capacity: int, retry_after: int) -> JSONResponse:
    base_headers = {"Retry-After": str(retry_after)}
    spec = rate_limit.get("error")
    if not spec:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit exceeded: {capacity} requests per minute"},
            headers=base_headers,
        )
    values = {"retry_after": retry_after, "limit": capacity}
    return _from_spec(spec, values, base_headers)
