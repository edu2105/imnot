"""
Dynamic router: registers FastAPI routes at startup from partner definitions.

Responsibilities:
- Accept a list of PartnerDef objects and a SessionStore instance.
- For each datapoint in each partner, delegate to the matching pattern factory
  to obtain route handlers, then register them on the FastAPI app.
- Register admin payload endpoints dynamically per datapoint (payload-patterns only):
    POST /imnot/admin/{partner}/{datapoint}/payload         (global)
    POST /imnot/admin/{partner}/{datapoint}/payload/session (session-scoped)
- Register fixed infra endpoints:
    GET  /imnot/admin/sessions
    GET  /imnot/admin/partners
    POST /imnot/admin/reload
"""

from __future__ import annotations

import hmac
import logging
from importlib.metadata import version as _pkg_version
from importlib.resources import files as _res_files
from pathlib import Path
from typing import Any

import yaml
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from imnot.config import UIConfig
from imnot.engine.patterns.async_ import make_async_handlers
from imnot.engine.patterns.fetch import make_fetch_handler
from imnot.engine.patterns.oauth import make_oauth_handler
from imnot.engine.patterns.paginated import make_paginated_handler
from imnot.engine.patterns.push import fire_callback, make_push_handler
from imnot.engine.patterns.static import make_static_handler
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef, PartnerDef, load_partners
from imnot.partners import register_partner
from imnot.postman import build_postman_collection

_cli_logger = logging.getLogger("imnot.cli")
_http_logger = logging.getLogger("imnot.http")
logger = _cli_logger  # startup / registration events go to the CLI stream

_IMNOT_VERSION = _pkg_version("imnot")

# Patterns that store payload in the session store and therefore need admin
# payload endpoints (GET/POST global + session).  oauth and static are fully
# defined by the YAML and never consult the store, so they get no admin routes.
_PAYLOAD_PATTERNS = {"fetch", "polling", "callback", "paginated"}


def register_routes(
    app: FastAPI,
    partners: list[PartnerDef],
    store: SessionStore,
    admin_key: str | None = None,
    partners_dir: Path | None = None,
    base_url: str = "http://localhost:8000",
    default_limit: int = 50,
    ui_config: UIConfig | None = None,
) -> None:
    """Register all routes on *app* derived from *partners*, plus fixed infra routes.

    If *admin_key* is provided, all ``/imnot/admin/*`` requests must include
    ``Authorization: Bearer <admin_key>`` or receive a 401 response.

    *partners_dir* is stored on ``app.state`` so the reload endpoint can re-read
    YAML files without needing the original path passed again.
    """
    # Mutable config dict shared with all static handlers.  The reload endpoint
    # overwrites entries here so running handlers immediately serve fresh config.
    configs: dict[tuple, dict[str, Any]] = {}

    # Maps (METHOD, path) → "partner/datapoint" for every registered consumer route.
    # Used both for duplicate-prevention at startup (raises ValueError on collision)
    # and for the reload endpoint (skips already-claimed routes).
    registered_routes: dict[tuple[str, str], str] = {}
    registered_admin_dps: set[tuple[str, str]] = set()

    effective_ui_config = ui_config if ui_config is not None else UIConfig()

    app.state.configs = configs
    app.state.store = store
    app.state.partners = partners
    app.state.partners_dir = partners_dir
    app.state.base_url = base_url
    app.state.registered_routes = registered_routes
    app.state.registered_admin_dps = registered_admin_dps
    app.state.default_limit = default_limit

    if admin_key:
        _register_admin_auth_middleware(app, admin_key)
    _register_docs_routes(app, partners_dir)
    _register_infra_routes(app, partners, store)
    if effective_ui_config.enabled:
        _register_ui_routes(app, effective_ui_config)
    for partner in partners:
        for datapoint in partner.datapoints:
            _register_consumer_routes(app, partner, datapoint, store, configs, registered_routes, default_limit)
            if datapoint.pattern in _PAYLOAD_PATTERNS:
                _register_admin_routes(app, partner, datapoint, store)
                registered_admin_dps.add((partner.partner, datapoint.name))
    logger.info(
        "Registered routes for %d partner(s): %s",
        len(partners),
        [p.partner for p in partners],
    )


# ---------------------------------------------------------------------------
# Admin auth middleware
# ---------------------------------------------------------------------------


def _register_admin_auth_middleware(app: FastAPI, admin_key: str) -> None:
    """Add middleware that enforces Bearer token auth on all /imnot/admin/* paths."""

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class AdminAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            if request.url.path.startswith("/imnot/admin/"):
                auth = request.headers.get("Authorization", "")
                if not hmac.compare_digest(auth, f"Bearer {admin_key}"):
                    _http_logger.warning(
                        "Admin auth failure: %s %s from %s",
                        request.method,
                        request.url.path,
                        request.client.host if request.client else "unknown",
                    )
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


def _check_route_collision(
    method: str,
    path: str,
    partner: str,
    datapoint: str,
    registered_routes: dict[tuple[str, str], str],
) -> None:
    """Raise ValueError if (method, path) is already claimed by another partner/datapoint."""
    key = (method.upper(), path)
    owner = registered_routes.get(key)
    if owner is not None and owner != f"{partner}/{datapoint}":
        raise ValueError(
            f"Route conflict: {method.upper()} {path} is already registered by "
            f"'{owner}'. Cannot register it for '{partner}/{datapoint}'."
        )


def _register_consumer_routes(
    app: FastAPI,
    partner: PartnerDef,
    datapoint: DatapointDef,
    store: SessionStore,
    configs: dict[tuple, dict[str, Any]],
    registered_routes: dict[tuple[str, str], str],
    default_limit: int = 50,
) -> None:
    owner = f"{partner.partner}/{datapoint.name}"

    def _add(path: str, handler: Any, method: str) -> None:
        """Register canonical path + trailing-slash alias (hidden from schema)."""
        app.add_api_route(path, handler, methods=[method])
        if path != "/":
            app.add_api_route(path + "/", handler, methods=[method], include_in_schema=False)

    if datapoint.pattern == "oauth":
        for endpoint in datapoint.endpoints:
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_oauth_handler(endpoint)
            _add(endpoint.path, handler, endpoint.method)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered oauth route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "static":
        for endpoint in datapoint.endpoints:
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_static_handler(partner.partner, datapoint.name, endpoint, configs)
            _add(endpoint.path, handler, endpoint.method)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered static route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "fetch":
        for endpoint in datapoint.endpoints:
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_fetch_handler(partner.partner, datapoint, endpoint, store)
            _add(endpoint.path, handler, endpoint.method)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered fetch route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "polling":
        step_map: dict[int, EndpointDef] = {ep.step: ep for ep in datapoint.endpoints}
        handlers = make_async_handlers(
            partner=partner.partner,
            datapoint=datapoint,
            store=store,
        )
        for step_num, handler in handlers.items():
            endpoint = step_map[step_num]
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            _add(endpoint.path, handler, endpoint.method)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug(
                "Registered polling step %d route %s %s",
                step_num,
                endpoint.method,
                endpoint.path,
            )

    elif datapoint.pattern == "callback":
        for endpoint in datapoint.endpoints:
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_push_handler(partner.partner, datapoint, endpoint, store)
            _add(endpoint.path, handler, endpoint.method)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered callback route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "paginated":
        for endpoint in datapoint.endpoints:
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_paginated_handler(partner.partner, datapoint, endpoint, store, default_limit)
            _add(endpoint.path, handler, endpoint.method)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered paginated route %s %s", endpoint.method, endpoint.path)


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

    global_path = f"/imnot/admin/{partner_name}/{dp_name}/payload"
    session_path = f"/imnot/admin/{partner_name}/{dp_name}/payload/session"

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
    session_get_path = f"/imnot/admin/{partner_name}/{dp_name}/payload/session/{{session_id}}"
    app.add_api_route(session_get_path, get_session, methods=["GET"])

    if datapoint.pattern == "callback":
        retrigger_path = f"/imnot/admin/{partner_name}/{dp_name}/callback/{{request_id}}/retrigger"

        async def retrigger(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
            request_id: str = request.path_params["request_id"]
            row = store.get_push_request(request_id)
            if row is None:
                return JSONResponse(
                    status_code=404,
                    content={"detail": f"Unknown request_id: {request_id}"},
                )
            background_tasks.add_task(
                fire_callback,
                store=store,
                partner=partner_name,
                datapoint=dp_name,
                session_id=row["session_id"],
                callback_url=row["callback_url"],
                callback_method=row["callback_method"],
            )
            return JSONResponse({"status": "dispatched", "request_id": request_id})

        retrigger.__name__ = f"admin_retrigger_{partner_name}_{dp_name}"
        app.add_api_route(retrigger_path, retrigger, methods=["POST"])

    logger.debug("Registered admin routes for %s/%s", partner_name, dp_name)


# ---------------------------------------------------------------------------
# Docs routes
# ---------------------------------------------------------------------------


def _register_docs_routes(app: FastAPI, partners_dir: Path | None) -> None:
    """Register public read-only endpoints that serve README files as plain text.

    Path resolution: prefer ``partners_dir.parent`` (reliable in Docker where the
    package is installed into site-packages but files live under ``/app/``).
    Falls back to a package-relative path for editable installs and local dev.
    """
    if partners_dir is not None:
        project_root = partners_dir.parent
    else:
        project_root = Path(__file__).parents[2]

    readme_path = project_root / "README.md"
    partners_readme_path = project_root / "partners" / "README.md"

    async def serve_readme() -> PlainTextResponse:
        if not readme_path.exists():
            return PlainTextResponse("README.md not found.", status_code=404)
        return PlainTextResponse(readme_path.read_text(encoding="utf-8"))

    async def serve_partners_readme() -> PlainTextResponse:
        if not partners_readme_path.exists():
            return PlainTextResponse("partners/README.md not found.", status_code=404)
        return PlainTextResponse(partners_readme_path.read_text(encoding="utf-8"))

    app.add_api_route("/imnot/docs", serve_readme, methods=["GET"])
    app.add_api_route("/imnot/docs/partners", serve_partners_readme, methods=["GET"])
    logger.debug("Registered docs routes")


# ---------------------------------------------------------------------------
# Admin UI route
# ---------------------------------------------------------------------------


def _register_ui_routes(app: FastAPI, ui_config: UIConfig) -> None:
    html_bytes = _res_files("imnot.ui").joinpath("index.html").read_bytes()
    themed = html_bytes.replace(
        b'data-theme="__IMNOT_THEME__"',
        f'data-theme="{ui_config.default_theme}"'.encode(),
    )

    async def serve_ui() -> HTMLResponse:
        return HTMLResponse(content=themed.decode("utf-8"))

    app.add_api_route("/imnot/admin/ui", serve_ui, methods=["GET"], include_in_schema=False)
    logger.debug("Registered admin UI route")


# ---------------------------------------------------------------------------
# Fixed infra routes
# ---------------------------------------------------------------------------


def _register_infra_routes(
    app: FastAPI,
    partners: list[PartnerDef],
    store: SessionStore,
) -> None:
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": _IMNOT_VERSION})

    async def list_sessions() -> JSONResponse:
        return JSONResponse(store.list_sessions())

    async def list_partners() -> JSONResponse:
        return JSONResponse(
            [
                {
                    "partner": p.partner,
                    "description": p.description,
                    "datapoints": [dp.name for dp in p.datapoints],
                }
                for p in partners
            ]
        )

    async def reload_partners(request: Request) -> JSONResponse:
        """Re-read all partner YAML files and hot-swap config for existing routes.

        - For ``static`` pattern datapoints: the response config (status + body)
          is updated in place so the very next request serves the new YAML body.
        - For entirely new partners or datapoints: consumer routes (and admin routes
          for payload patterns) are registered dynamically on the running app.
        - Removed partners/datapoints are NOT unregistered (existing routes stay
          active but serve their last-known config).  Restart the server to
          fully purge removed definitions.
        """
        partners_dir: Path | None = request.app.state.partners_dir
        if partners_dir is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "No partners_dir configured — server was not started via `imnot start`."},
            )

        try:
            new_partners = load_partners(partners_dir)
        except Exception as exc:
            _http_logger.exception("Reload failed: %s", exc)
            return JSONResponse(status_code=500, content={"detail": "Reload failed. Check server logs for details."})

        configs: dict = request.app.state.configs
        store_: SessionStore = request.app.state.store
        registered: dict[tuple[str, str], str] = request.app.state.registered_routes
        registered_admin: set[tuple[str, str]] = request.app.state.registered_admin_dps

        updated: list[str] = []
        added: list[str] = []
        conflicts: list[str] = []

        for partner in new_partners:
            for dp in partner.datapoints:
                # Hot-swap static response configs for already-registered routes
                if dp.pattern == "static":
                    for ep in dp.endpoints:
                        key = (partner.partner, dp.name, ep.method.upper(), ep.path)
                        if key in configs:
                            configs[key] = ep.response
                            updated.append(f"{ep.method.upper()} {ep.path}")

                # Register brand-new consumer routes (new partners or new datapoints)
                new_eps = [ep for ep in dp.endpoints if (ep.method.upper(), ep.path) not in registered]
                if new_eps:
                    try:
                        _register_consumer_routes(
                            request.app,
                            partner,
                            dp,
                            store_,
                            configs,
                            registered,
                            request.app.state.default_limit,
                        )
                        for ep in new_eps:
                            added.append(f"{ep.method.upper()} {ep.path}")
                    except ValueError as exc:
                        conflicts.append(str(exc))

                # Register admin routes for new payload-pattern datapoints
                if dp.pattern in _PAYLOAD_PATTERNS and (partner.partner, dp.name) not in registered_admin:
                    _register_admin_routes(request.app, partner, dp, store_)
                    registered_admin.add((partner.partner, dp.name))
                    added.append(f"admin routes for {partner.partner}/{dp.name}")

        # Sync partners list in-place so list_partners() closure sees the change.
        existing_names = {p.partner for p in partners}
        for new_partner in new_partners:
            if new_partner.partner not in existing_names:
                partners.append(new_partner)
            else:
                for i, p in enumerate(partners):
                    if p.partner == new_partner.partner:
                        partners[i] = new_partner
                        break

        _http_logger.info("Reload: updated=%s added=%s conflicts=%s", updated, added, conflicts)
        status = "ok" if not conflicts else "partial"
        return JSONResponse({"status": status, "updated": updated, "added": added, "conflicts": conflicts})

    async def create_partner_handler(request: Request) -> JSONResponse:
        """Validate raw YAML body, write it to disk, and hot-load its routes.

        Query params:
            force (bool, default false) — overwrite if partner already exists.

        Returns 201 on create, 200 on overwrite, 409 on conflict, 422 on bad YAML.
        """
        partners_dir: Path | None = request.app.state.partners_dir
        if partners_dir is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "No partners_dir configured — server was not started via `imnot start`."},
            )

        force = request.query_params.get("force", "false").lower() == "true"
        yaml_text = (await request.body()).decode()

        try:
            result = register_partner(yaml_text, partners_dir, force=force)
        except (yaml.YAMLError, ValueError) as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})
        except FileExistsError as exc:
            return JSONResponse(status_code=409, content={"status": "error", "detail": str(exc)})

        partner = result.partner
        configs_: dict = request.app.state.configs
        store_: SessionStore = request.app.state.store
        registered_: dict[tuple[str, str], str] = request.app.state.registered_routes
        registered_admin_: set[tuple[str, str]] = request.app.state.registered_admin_dps

        added: list[str] = []
        conflicts: list[str] = []

        for dp in partner.datapoints:
            # Hot-swap static response configs for already-registered routes
            if dp.pattern == "static":
                for ep in dp.endpoints:
                    key = (partner.partner, dp.name, ep.method.upper(), ep.path)
                    if key in configs_:
                        configs_[key] = ep.response

            # Register brand-new consumer routes
            new_eps = [ep for ep in dp.endpoints if (ep.method.upper(), ep.path) not in registered_]
            if new_eps:
                try:
                    _register_consumer_routes(
                        request.app,
                        partner,
                        dp,
                        store_,
                        configs_,
                        registered_,
                        request.app.state.default_limit,
                    )
                    for ep in new_eps:
                        added.append(f"{ep.method.upper()} {ep.path}")
                except ValueError as exc:
                    conflicts.append(str(exc))

            # Register admin routes for new payload-pattern datapoints
            if dp.pattern in _PAYLOAD_PATTERNS and (partner.partner, dp.name) not in registered_admin_:
                _register_admin_routes(request.app, partner, dp, store_)
                registered_admin_.add((partner.partner, dp.name))
                added.append(f"admin routes for {partner.partner}/{dp.name}")

        # Keep partners list in-place so list_partners() closure sees the change.
        existing_names = {p.partner for p in partners}
        if partner.partner not in existing_names:
            partners.append(partner)
        else:
            for i, p in enumerate(partners):
                if p.partner == partner.partner:
                    partners[i] = partner
                    break

        payload_dp_names = {dp.name for dp in partner.datapoints if dp.pattern in _PAYLOAD_PATTERNS}
        status_code = 201 if result.created else 200
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok",
                "partner": partner.partner,
                "description": partner.description,
                "directory": f"partners/{partner.partner}",
                "file": f"partners/{partner.partner}/partner.yaml",
                "created": result.created,
                "datapoints": [
                    {
                        "name": dp.name,
                        "pattern": dp.pattern,
                        "endpoints": [{"method": ep.method, "path": ep.path} for ep in dp.endpoints],
                        "admin_routes": dp.name in payload_dp_names,
                    }
                    for dp in partner.datapoints
                ],
                "routes_added": added,
                "routes_conflicts": conflicts,
            },
        )

    async def postman_collection(request: Request) -> JSONResponse:
        return JSONResponse(
            build_postman_collection(
                request.app.state.partners,
                base_url=request.app.state.base_url,
            )
        )

    reload_partners.__name__ = "admin_reload_partners"
    create_partner_handler.__name__ = "admin_create_partner"

    app.add_api_route("/healthz", healthz, methods=["GET"])
    app.add_api_route("/imnot/admin/sessions", list_sessions, methods=["GET"])
    app.add_api_route("/imnot/admin/partners", list_partners, methods=["GET"])
    app.add_api_route("/imnot/admin/partners", create_partner_handler, methods=["POST"])
    app.add_api_route("/imnot/admin/reload", reload_partners, methods=["POST"])
    app.add_api_route("/imnot/admin/postman", postman_collection, methods=["GET"])
    logger.debug("Registered infra routes")
