"""
Static pattern handler.

Responsibilities:
- Expose a factory function `make_static_handler` that accepts partner/datapoint
  names, an EndpointDef, and a mutable *configs* dict.
- The handler responds with exactly the JSON body defined under `response.body`
  in the YAML. No payload storage, no session state.
- The configs dict is shared with the reload machinery: when a YAML file is
  updated and the reload endpoint is called, the entry for this handler's key
  is overwritten and subsequent requests immediately serve the new body.
- Use this pattern for any endpoint whose response is fully known at YAML
  authoring time (e.g. non-standard token endpoints, health checks, fixed
  capability documents). For a standard OAuth JWT response use the `oauth`
  pattern instead.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Response
from fastapi.responses import JSONResponse

from imnot.loader.yaml_loader import EndpointDef


def make_static_handler(
    partner_name: str,
    dp_name: str,
    endpoint: EndpointDef,
    configs: dict[tuple, dict[str, Any]],
) -> Callable[[], Response]:
    """Return a FastAPI route handler for the given static EndpointDef.

    *configs* is a mutable dict shared with the router's reload machinery.
    The handler reads its response config from *configs* on every request so
    that a YAML edit followed by ``POST /imnot/admin/reload`` takes effect
    immediately without restarting the server.
    """
    key = (partner_name, dp_name, endpoint.method.upper(), endpoint.path)
    configs[key] = endpoint.response

    async def handler() -> JSONResponse:
        cfg = configs[key]
        return JSONResponse(
            status_code=cfg.get("status", 200),
            content=cfg.get("body") or {},
        )

    handler.__name__ = f"static_{endpoint.method}_{endpoint.path.replace('/', '_').strip('_')}"

    return handler
