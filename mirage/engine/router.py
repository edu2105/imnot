"""
Dynamic router: registers FastAPI routes at startup from partner definitions.

Responsibilities:
- Accept a list of PartnerDef objects and a SessionStore instance.
- For each datapoint in each partner, delegate to the matching pattern factory
  to obtain route handlers, then register them on the FastAPI app.
- Register admin payload endpoints dynamically per datapoint:
    POST /mirage/admin/{partner}/{datapoint}/payload         (global)
    POST /mirage/admin/{partner}/{datapoint}/payload/session (session-scoped)
- Register fixed infra endpoints:
    GET /mirage/admin/sessions
    GET /mirage/admin/partners
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mirage.engine.patterns.async_ import make_async_handlers
from mirage.engine.patterns.fetch import make_fetch_handler
from mirage.engine.patterns.oauth import make_oauth_handler
from mirage.engine.patterns.static import make_static_handler
from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import DatapointDef, EndpointDef, PartnerDef

logger = logging.getLogger(__name__)


def register_routes(
    app: FastAPI,
    partners: list[PartnerDef],
    store: SessionStore,
    admin_key: str | None = None,
) -> None:
    """Register all routes on *app* derived from *partners*, plus fixed infra routes.

    If *admin_key* is provided, all ``/mirage/admin/*`` requests must include
    ``Authorization: Bearer <admin_key>`` or receive a 401 response.
    """
    if admin_key:
        _register_admin_auth_middleware(app, admin_key)
    _register_infra_routes(app, partners, store)
    for partner in partners:
        for datapoint in partner.datapoints:
            _register_consumer_routes(app, partner, datapoint, store)
            _register_admin_routes(app, partner, datapoint, store)
    logger.info(
        "Registered routes for %d partner(s): %s",
        len(partners),
        [p.partner for p in partners],
    )


# ---------------------------------------------------------------------------
# Admin auth middleware
# ---------------------------------------------------------------------------


def _register_admin_auth_middleware(app: FastAPI, admin_key: str) -> None:
    """Add middleware that enforces Bearer token auth on all /mirage/admin/* paths."""

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class AdminAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            if request.url.path.startswith("/mirage/admin/"):
                auth = request.headers.get("Authorization", "")
                if auth != f"Bearer {admin_key}":
                    return Response(
                        content='{"detail":"Unauthorized"}',
                        status_code=401,
                        media_type="application/json",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            return await call_next(request)

    app.add_middleware(AdminAuthMiddleware)


# ---------------------------------------------------------------------------
# Consumer routes (the mock endpoints themselves)
# ---------------------------------------------------------------------------


def _register_consumer_routes(
    app: FastAPI,
    partner: PartnerDef,
    datapoint: DatapointDef,
    store: SessionStore,
) -> None:
    if datapoint.pattern == "oauth":
        for endpoint in datapoint.endpoints:
            handler = make_oauth_handler(endpoint)
            app.add_api_route(endpoint.path, handler, methods=[endpoint.method])
            logger.debug("Registered oauth route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "static":
        for endpoint in datapoint.endpoints:
            handler = make_static_handler(endpoint)
            app.add_api_route(endpoint.path, handler, methods=[endpoint.method])
            logger.debug("Registered static route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "fetch":
        for endpoint in datapoint.endpoints:
            handler = make_fetch_handler(partner.partner, datapoint, endpoint, store)
            app.add_api_route(endpoint.path, handler, methods=[endpoint.method])
            logger.debug("Registered fetch route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "async":
        step_map: dict[int, EndpointDef] = {ep.step: ep for ep in datapoint.endpoints}
        handlers = make_async_handlers(
            partner=partner.partner,
            datapoint=datapoint,
            store=store,
        )
        for step_num, handler in handlers.items():
            endpoint = step_map[step_num]
            app.add_api_route(endpoint.path, handler, methods=[endpoint.method])
            logger.debug(
                "Registered async step %d route %s %s",
                step_num, endpoint.method, endpoint.path,
            )


# ---------------------------------------------------------------------------
# Admin payload routes (dynamic per datapoint)
# ---------------------------------------------------------------------------


def _register_admin_routes(
    app: FastAPI,
    partner: PartnerDef,
    datapoint: DatapointDef,
    store: SessionStore,
) -> None:
    partner_name = partner.partner
    dp_name = datapoint.name

    global_path = f"/mirage/admin/{partner_name}/{dp_name}/payload"
    session_path = f"/mirage/admin/{partner_name}/{dp_name}/payload/session"

    async def upload_global(request: Request) -> JSONResponse:
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
        store.store_global_payload(partner_name, dp_name, payload)
        return JSONResponse({"status": "ok", "partner": partner_name, "datapoint": dp_name})

    async def upload_session(request: Request) -> JSONResponse:
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
        session_id = store.store_session_payload(partner_name, dp_name, payload)
        return JSONResponse({"session_id": session_id})

    async def get_global(request: Request) -> JSONResponse:
        result = store.get_global_payload(partner_name, dp_name)
        if result is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"No global payload set for {partner_name}/{dp_name}"},
            )
        return JSONResponse(result)

    async def get_session(session_id: str) -> JSONResponse:
        result = store.get_session_payload(session_id)
        if result is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Session '{session_id}' not found"},
            )
        return JSONResponse(result)

    upload_global.__name__ = f"admin_upload_global_{partner_name}_{dp_name}"
    upload_session.__name__ = f"admin_upload_session_{partner_name}_{dp_name}"
    get_global.__name__ = f"admin_get_global_{partner_name}_{dp_name}"
    get_session.__name__ = f"admin_get_session_{partner_name}_{dp_name}"

    app.add_api_route(global_path, upload_global, methods=["POST"])
    app.add_api_route(session_path, upload_session, methods=["POST"])
    app.add_api_route(global_path, get_global, methods=["GET"])
    app.add_api_route(f"/mirage/admin/{partner_name}/{dp_name}/payload/session/{{session_id}}", get_session, methods=["GET"])
    logger.debug("Registered admin routes for %s/%s", partner_name, dp_name)


# ---------------------------------------------------------------------------
# Fixed infra routes
# ---------------------------------------------------------------------------


def _register_infra_routes(
    app: FastAPI,
    partners: list[PartnerDef],
    store: SessionStore,
) -> None:
    async def list_sessions() -> JSONResponse:
        return JSONResponse(store.list_sessions())

    async def list_partners() -> JSONResponse:
        return JSONResponse([
            {
                "partner": p.partner,
                "description": p.description,
                "datapoints": [dp.name for dp in p.datapoints],
            }
            for p in partners
        ])

    app.add_api_route("/mirage/admin/sessions", list_sessions, methods=["GET"])
    app.add_api_route("/mirage/admin/partners", list_partners, methods=["GET"])
    logger.debug("Registered infra routes")
