"""
OAuth pattern handler.

Responsibilities:
- Expose a factory function `make_oauth_handler` that accepts an EndpointDef
  and returns a FastAPI route coroutine.
- The handler responds with a JWT-shaped JSON body (access_token, token_type,
  expires_in). token_type and expires_in come from the YAML response config;
  access_token is a static hardcoded value suitable for POC / integration testing.
- No payload storage is involved; the response is fully defined by the YAML config.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Response
from fastapi.responses import JSONResponse

from imnot.loader.yaml_loader import EndpointDef

# A static JWT-shaped token returned for every token request.
# Integration test systems only care that a non-empty Bearer token is present.
_STATIC_ACCESS_TOKEN = (  # nosec B105 — intentional placeholder token for mock use
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiJpbW5vdCIsImlhdCI6MH0"
    ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)


def make_oauth_handler(endpoint: EndpointDef) -> Callable[[], Response]:
    """Return a FastAPI route handler for the given oauth EndpointDef."""

    response_cfg: dict[str, Any] = endpoint.response
    status_code: int = response_cfg.get("status", 200)
    token_type: str = response_cfg.get("token_type", "Bearer")
    expires_in: int = response_cfg.get("expires_in", 3600)

    async def handler() -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "access_token": _STATIC_ACCESS_TOKEN,
                "token_type": token_type,
                "expires_in": expires_in,
            },
        )

    # Give the handler a unique name so FastAPI doesn't complain about
    # duplicate route function names when multiple partners are loaded.
    handler.__name__ = f"oauth_{endpoint.path.replace('/', '_').strip('_')}"

    return handler
