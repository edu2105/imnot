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

import asyncio
import hmac
import logging
import math
import re
import shutil
import time
from importlib.metadata import version as _pkg_version
from importlib.resources import files as _res_files
from pathlib import Path
from typing import Any

import yaml
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from imnot.config import UIConfig
from imnot.engine.faults import with_faults
from imnot.engine.patterns.async_ import make_async_handlers
from imnot.engine.patterns.fetch import make_fetch_handler
from imnot.engine.patterns.oauth import make_oauth_handler
from imnot.engine.patterns.paginated import make_paginated_handler
from imnot.engine.patterns.push import delivery_config, fire_callback, make_push_handler
from imnot.engine.patterns.static import make_static_handler
from imnot.engine.rate_limiter import RateLimiter
from imnot.engine.session_store import SessionStore
from imnot.engine.stress_router import register_stress_routes
from imnot.loader.yaml_loader import (
    PAYLOAD_PATTERNS,
    DatapointDef,
    EndpointDef,
    PartnerDef,
    load_partners,
    payload_shape_error,
)
from imnot.partners import (
    EXAMPLE_PARTNERS,
    dropped_fields,
    is_safe_partner_name,
    load_example_partner,
    merge_unmanaged_fields,
    register_partner,
    validate_partner_yaml,
    write_example_partner,
)
from imnot.postman import build_postman_collection

_cli_logger = logging.getLogger("imnot.cli")
_SESSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_http_logger = logging.getLogger("imnot.http")
logger = _cli_logger  # startup / registration events go to the CLI stream

_IMNOT_VERSION = _pkg_version("imnot")


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
    paginated_config_refs: dict[tuple, list] = {}

    # Maps (METHOD, path) → "partner/datapoint" for every registered consumer route.
    # Used both for duplicate-prevention at startup (raises ValueError on collision)
    # and for the reload endpoint (skips already-claimed routes).
    registered_routes: dict[tuple[str, str], str] = {}
    registered_admin_dps: set[tuple[str, str]] = set()

    effective_ui_config = ui_config if ui_config is not None else UIConfig()

    app.state.configs = configs
    app.state.paginated_config_refs = paginated_config_refs
    app.state.store = store
    app.state.partners = partners
    app.state.partners_dir = partners_dir
    app.state.base_url = base_url
    app.state.registered_routes = registered_routes
    # Stateless mode only: partner.yaml texts created or edited through the admin API, by partner name
    # (None = deleted). They win over the files in partners_dir until a reload or a restart.
    app.state.memory_partners = {}
    app.state.auth_required = bool(admin_key)  # reported by /healthz so the UI knows whether to ask for a key
    app.state.fault_counters = {}  # fail.first_n call counts, see engine/faults.py
    app.state.registered_admin_dps = registered_admin_dps
    app.state.default_limit = default_limit
    app.state.rate_limiter = RateLimiter()

    if admin_key:
        _register_admin_auth_middleware(app, admin_key)
    _register_docs_routes(app)
    _register_infra_routes(app, partners, store)
    stress_store = getattr(app.state, "stress_store", None)
    if stress_store is not None:
        register_stress_routes(app, store, stress_store)
    if effective_ui_config.enabled:
        _register_ui_routes(app, effective_ui_config)
    for partner in partners:
        for datapoint in partner.datapoints:
            _register_consumer_routes(
                app,
                partner,
                datapoint,
                store,
                configs,
                paginated_config_refs,
                registered_routes,
                app.state.rate_limiter,
                default_limit,
            )
            if datapoint.pattern in PAYLOAD_PATTERNS:
                _register_admin_routes(app, partner, datapoint, store)
                registered_admin_dps.add((partner.partner, datapoint.name))
    logger.info(
        "Registered routes for %d partner(s): %s",
        len(partners),
        [p.partner for p in partners],
    )


def seed_payloads(store: SessionStore, partners: list[PartnerDef]) -> None:
    """Store payloads from ``partners/<partner>/payloads/*.json`` as global payloads.

    The files are the source of truth: they overwrite any global payload uploaded earlier for the
    same datapoint (sessions are untouched). Called from the app lifespan once the store is
    initialised (``create_app``), and on every reload.
    """
    for partner in partners:
        for dp_name, payload in partner.seed_payloads.items():
            store.store_global_payload(partner.partner, dp_name, payload)
            _cli_logger.info("Seeded global payload for %s/%s from payloads/%s.json", partner.partner, dp_name, dp_name)


# ---------------------------------------------------------------------------
# Admin auth middleware
# ---------------------------------------------------------------------------


# Failed admin logins share one queue: each takes a slot of AUTH_FAILURE_DELAY_SECONDS before its 401,
# so guessing the key runs at ~2 tries per second however many clients or IPs try at once (behind an
# ingress every client has the same IP, so a per-IP lockout would lock the whole team out instead).
# Requests with the right key never wait. Past AUTH_FAILURE_MAX_WAIT_SECONDS of queue, 429 at once.
AUTH_FAILURE_DELAY_SECONDS = 0.5
AUTH_FAILURE_MAX_WAIT_SECONDS = 10.0


def _register_admin_auth_middleware(app: FastAPI, admin_key: str) -> None:
    """Add middleware that enforces Bearer token auth on all /imnot/admin/* paths."""

    from starlette.middleware.base import BaseHTTPMiddleware

    failures = {"next_slot": 0.0}  # monotonic time when the next failed attempt may be answered

    class AdminAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):  # type: ignore[override]
            if request.url.path.startswith("/imnot/admin/") and request.url.path != "/imnot/admin/ui":
                auth = request.headers.get("Authorization", "")
                if not hmac.compare_digest(auth, f"Bearer {admin_key}"):
                    _http_logger.warning(
                        "Admin auth failure: %s %s from %s",
                        request.method,
                        request.url.path,
                        request.client.host if request.client else "unknown",
                    )
                    now = time.monotonic()
                    slot = max(now, failures["next_slot"])
                    if slot - now > AUTH_FAILURE_MAX_WAIT_SECONDS:
                        return Response(
                            content='{"detail":"Too many failed admin key attempts, retry later"}',
                            status_code=429,
                            media_type="application/json",
                            headers={"Retry-After": str(math.ceil(slot - now))},
                        )
                    # Claimed before the await, so concurrent failures queue up instead of all waiting once.
                    answer_at = failures["next_slot"] = slot + AUTH_FAILURE_DELAY_SECONDS
                    await asyncio.sleep(answer_at - now)
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
    paginated_config_refs: dict[tuple, list],
    registered_routes: dict[tuple[str, str], str],
    limiter: RateLimiter,
    default_limit: int = 50,
) -> None:
    owner = f"{partner.partner}/{datapoint.name}"
    # Called again for a datapoint that gained endpoints (reload, POST /partners): register only
    # the new ones. Re-adding a live route would leave two routes (the old one still wins) and,
    # for paginated, point its config ref at a list the live handler no longer reads.
    known = {key for key, who in registered_routes.items() if who == owner}

    def _add(endpoint: EndpointDef, handler: Any) -> None:
        """Register canonical path + trailing-slash alias (hidden from schema), with delay_ms/fail applied."""
        path, method = endpoint.path, endpoint.method
        handler = with_faults(handler, endpoint, app.state.fault_counters)
        app.add_api_route(path, handler, methods=[method])
        if path != "/":
            app.add_api_route(path + "/", handler, methods=[method], include_in_schema=False)

    if datapoint.pattern == "oauth":
        for endpoint in datapoint.endpoints:
            if (endpoint.method.upper(), endpoint.path) in known:
                continue
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_oauth_handler(endpoint)
            _add(endpoint, handler)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered oauth route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "static":
        for endpoint in datapoint.endpoints:
            if (endpoint.method.upper(), endpoint.path) in known:
                continue
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_static_handler(partner.partner, datapoint.name, endpoint, configs)
            _add(endpoint, handler)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered static route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "fetch":
        for endpoint in datapoint.endpoints:
            if (endpoint.method.upper(), endpoint.path) in known:
                continue
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_fetch_handler(partner.partner, datapoint, endpoint, store, limiter)
            _add(endpoint, handler)
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
            if (endpoint.method.upper(), endpoint.path) in known:
                continue
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            _add(endpoint, handler)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug(
                "Registered polling step %d route %s %s",
                step_num,
                endpoint.method,
                endpoint.path,
            )

    elif datapoint.pattern == "callback":
        for endpoint in datapoint.endpoints:
            if (endpoint.method.upper(), endpoint.path) in known:
                continue
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            handler = make_push_handler(partner.partner, datapoint, endpoint, store)
            _add(endpoint, handler)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered callback route %s %s", endpoint.method, endpoint.path)

    elif datapoint.pattern == "paginated":
        for endpoint in datapoint.endpoints:
            if (endpoint.method.upper(), endpoint.path) in known:
                continue
            _check_route_collision(endpoint.method, endpoint.path, partner.partner, datapoint.name, registered_routes)
            ref_key = (partner.partner, datapoint.name, endpoint.method.upper(), endpoint.path)
            pagination_ref: list[dict] = [datapoint.pagination or {}]
            paginated_config_refs[ref_key] = pagination_ref
            handler = make_paginated_handler(
                partner.partner, datapoint, endpoint, store, default_limit, pagination_ref, limiter
            )
            _add(endpoint, handler)
            registered_routes[(endpoint.method.upper(), endpoint.path)] = owner
            logger.debug("Registered paginated route %s %s", endpoint.method, endpoint.path)


def _unregister_partner_routes(app: FastAPI, partner_name: str) -> None:
    """Remove every consumer and admin route that *partner_name* registered, and its bookkeeping."""
    registered: dict[tuple[str, str], str] = app.state.registered_routes
    owned = {key for key, owner in registered.items() if owner.split("/", 1)[0] == partner_name}
    admin_dps = {k for k in app.state.registered_admin_dps if k[0] == partner_name}
    _unregister_routes(app, owned, admin_dps)


def _unregister_routes(app: FastAPI, route_keys: set[tuple[str, str]], admin_dps: set[tuple[str, str]]) -> None:
    """Remove the given consumer routes ``(METHOD, path)`` and the admin routes of ``(partner, datapoint)``.

    Also drops their bookkeeping (registered_routes, registered_admin_dps, static/pagination configs).
    Infra routes (``/imnot/admin/partners``, ``/imnot/admin/reload``…) are never touched: admin
    routes are matched by the exact paths ``_register_admin_routes`` builds, not by prefix.
    """
    registered: dict[tuple[str, str], str] = app.state.registered_routes
    # Static/pagination configs are keyed (partner, datapoint, METHOD, path): drop those whose route
    # is going away under that same owner (computed before registered_routes is updated).
    config_keys = {
        (store_dict_name, key)
        for store_dict_name, store_dict in (("configs", app.state.configs), ("refs", app.state.paginated_config_refs))
        for key in store_dict
        if (key[2], key[3]) in route_keys and registered.get((key[2], key[3])) == f"{key[0]}/{key[1]}"
    }
    admin_suffixes = ("payload", "payload/session", "payload/session/{session_id}", "callback/{request_id}/retrigger")
    admin_paths = {f"/imnot/admin/{p}/{dp}/{suffix}" for (p, dp) in admin_dps for suffix in admin_suffixes}

    def _belongs(route: Any) -> bool:
        path: str | None = getattr(route, "path", None)
        methods: set[str] = getattr(route, "methods", None) or set()
        if path is None:
            return False
        if path in admin_paths:
            return True
        canonical = path[:-1] if path.endswith("/") and path != "/" else path
        return any((m, path) in route_keys or (m, canonical) in route_keys for m in methods)

    app.router.routes[:] = [r for r in app.router.routes if not _belongs(r)]
    for key in route_keys:
        registered.pop(key, None)
    app.state.registered_admin_dps.difference_update(admin_dps)
    stores = {"configs": app.state.configs, "refs": app.state.paginated_config_refs}
    for store_dict_name, key in config_keys:
        stores[store_dict_name].pop(key, None)
    app.openapi_schema = None  # rebuild /openapi.json without the removed routes


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

    def _shape_error(payload: Any) -> JSONResponse | None:
        """Reject a payload the routes could never serve, at upload time instead of on every GET."""
        problem = payload_shape_error(datapoint, payload)
        if problem is None:
            return None
        return JSONResponse(status_code=422, content={"detail": problem[0].upper() + problem[1:]})

    async def upload_global(request: Request) -> JSONResponse:
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
        if (error := _shape_error(payload)) is not None:
            return error
        store.store_global_payload(partner_name, dp_name, payload)
        return JSONResponse({"status": "ok", "partner": partner_name, "datapoint": dp_name})

    async def upload_session(request: Request) -> JSONResponse:
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
        if (error := _shape_error(payload)) is not None:
            return error
        # Reuse a session (header or ?session=) to put several datapoints under one X-Imnot-Session.
        wanted = request.headers.get("X-Imnot-Session") or request.query_params.get("session")
        if wanted is not None and not _SESSION_ID.match(wanted):
            return JSONResponse(
                status_code=400,
                content={"detail": "Session id must be 1-128 letters, digits, '.', '_', ':' or '-'"},
            )
        session_id = store.store_session_payload(partner_name, dp_name, payload, session_id=wanted)
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
        result = store.get_session_payload(session_id, partner_name, dp_name)
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
                context={"request_id": request_id},  # the submit request itself is not stored
                delivery=delivery_config(datapoint.endpoints[0].response),
                policy=getattr(request.app.state, "callback_policy", None),
            )
            return JSONResponse({"status": "dispatched", "request_id": request_id})

        retrigger.__name__ = f"admin_retrigger_{partner_name}_{dp_name}"
        app.add_api_route(retrigger_path, retrigger, methods=["POST"])

    logger.debug("Registered admin routes for %s/%s", partner_name, dp_name)


# ---------------------------------------------------------------------------
# Docs routes
# ---------------------------------------------------------------------------


# Where imnot's own docs live: inside the wheel (pip/Docker installs, see force-include in
# pyproject.toml) or at the repo root (editable installs and local dev).
_PACKAGED_DOCS_DIR = Path(__file__).parents[1] / "_docs"
_REPO_ROOT = Path(__file__).parents[2]
_DOC_FILES = {
    "readme": (_PACKAGED_DOCS_DIR / "README.md", _REPO_ROOT / "README.md"),
    "partners": (_PACKAGED_DOCS_DIR / "partners-README.md", _REPO_ROOT / "partners" / "README.md"),
}


def _find_doc(name: str) -> Path | None:
    return next((p for p in _DOC_FILES[name] if p.is_file()), None)


def _register_docs_routes(app: FastAPI) -> None:
    """Register public read-only endpoints that serve imnot's README files as plain text.

    They always serve imnot's own docs (see ``_DOC_FILES``), never the user's project files.
    """

    async def serve_readme() -> PlainTextResponse:
        path = _find_doc("readme")
        if path is None:
            return PlainTextResponse("README.md not found.", status_code=404)
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    async def serve_partners_readme() -> PlainTextResponse:
        path = _find_doc("partners")
        if path is None:
            return PlainTextResponse("partners/README.md not found.", status_code=404)
        return PlainTextResponse(path.read_text(encoding="utf-8"))

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
        return HTMLResponse(
            content=themed.decode("utf-8"),
            headers={
                "X-Frame-Options": "DENY",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'"
                ),
            },
        )

    app.add_api_route("/imnot/admin/ui", serve_ui, methods=["GET"], include_in_schema=False)
    logger.debug("Registered admin UI route")


# ---------------------------------------------------------------------------
# Fixed infra routes
# ---------------------------------------------------------------------------


def _partners_read_only_response(exc: OSError) -> JSONResponse:
    """403 for POST/DELETE /imnot/admin/partners when the partners directory cannot be written."""
    return JSONResponse(
        status_code=403,
        content={
            "status": "error",
            "detail": "Partners cannot be changed through the admin API: the partners directory is not writable "
            f"({exc.strerror or exc}). Change partner.yaml where the partners come from and restart, "
            "or start with --stateless to keep changes in memory.",
        },
    )


def _partner_yaml_text(app: FastAPI, partner_name: str) -> str | None:
    """The current partner.yaml text of *partner_name*: the in-memory one (stateless mode) or the file."""
    memory: dict[str, str | None] = app.state.memory_partners
    if partner_name in memory:
        return memory[partner_name]
    partners_dir: Path | None = app.state.partners_dir
    if partners_dir is None:
        return None
    path = partners_dir / partner_name / "partner.yaml"
    return path.read_text() if path.is_file() else None


def _register_infra_routes(
    app: FastAPI,
    partners: list[PartnerDef],
    store: SessionStore,
) -> None:
    async def healthz(request: Request) -> JSONResponse:
        auth_required = bool(getattr(request.app.state, "auth_required", False))
        stateless = bool(getattr(request.app.state, "stateless", False))
        return JSONResponse(
            {
                "status": "ok",
                "version": _IMNOT_VERSION,
                "auth_required": auth_required,
                "stateless": stateless,
                "instance": getattr(request.app.state, "instance_name", None),  # --instance-name, or null
            }
        )

    async def list_sessions() -> JSONResponse:
        return JSONResponse(store.list_sessions())

    async def reset_faults(request: Request) -> JSONResponse:
        """Reset fail.first_n counters, so failing endpoints fail again from the first call."""
        counters: dict = request.app.state.fault_counters
        cleared = len(counters)
        counters.clear()
        return JSONResponse({"status": "ok", "cleared": cleared})

    async def list_requests(request: Request) -> JSONResponse:
        """Request journal, newest first. Filters: partner, datapoint, session, method; limit (1-1000, default 50)."""
        q = request.query_params
        try:
            limit = int(q.get("limit", "50"))
        except ValueError:
            return JSONResponse(status_code=422, content={"detail": "'limit' must be an integer"})
        if not 1 <= limit <= 1000:
            return JSONResponse(status_code=422, content={"detail": "'limit' must be between 1 and 1000"})
        entries = store.list_requests(
            partner=q.get("partner"),
            datapoint=q.get("datapoint"),
            session_id=q.get("session"),
            method=q.get("method"),
            limit=limit,
        )
        return JSONResponse(entries)

    async def clear_requests(request: Request) -> JSONResponse:
        """Clear the request journal, or only one session's entries with ?session=<id>."""
        deleted = store.clear_requests(session_id=request.query_params.get("session"))
        return JSONResponse({"status": "ok", "deleted": deleted})

    async def delete_session(session_id: str) -> JSONResponse:
        deleted = store.delete_session(session_id)
        if not deleted:
            return JSONResponse(status_code=404, content={"detail": "Session not found"})
        return JSONResponse({"status": "ok", "session_id": session_id})

    async def delete_partner(partner_name: str, request: Request) -> JSONResponse:
        if getattr(request.app.state, "stateless", False):
            # In memory only: the file (if any) stays, and a reload or restart brings the partner back.
            if not any(p.partner == partner_name for p in partners):
                return JSONResponse(status_code=404, content={"detail": f"Partner '{partner_name}' not found."})
            _unregister_partner_routes(request.app, partner_name)
            partners[:] = [p for p in partners if p.partner != partner_name]
            request.app.state.memory_partners[partner_name] = None
            return JSONResponse({"status": "ok", "partner": partner_name})
        partners_dir: Path | None = request.app.state.partners_dir
        if partners_dir is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "No partners_dir configured — server was not started via `imnot start`."},
            )
        if not is_safe_partner_name(partner_name):
            return JSONResponse(status_code=400, content={"detail": "Invalid partner name."})
        partner_dir = partners_dir / partner_name
        try:
            partner_dir.resolve().relative_to(partners_dir.resolve())
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid partner name."})
        if not partner_dir.exists():
            return JSONResponse(status_code=404, content={"detail": f"Partner '{partner_name}' not found."})
        symlinks = [str(p) for p in partner_dir.rglob("*") if p.is_symlink()]
        if symlinks:
            return JSONResponse(
                status_code=400,
                content={"detail": "Partner directory contains symlinks; refusing to delete.", "symlinks": symlinks},
            )
        try:
            shutil.rmtree(partner_dir)
        except OSError as exc:
            return _partners_read_only_response(exc)
        _unregister_partner_routes(request.app, partner_name)
        for i, p in enumerate(partners):
            if p.partner == partner_name:
                partners.pop(i)
                break
        return JSONResponse({"status": "ok", "partner": partner_name})

    async def get_partner(partner_name: str, request: Request) -> Response:
        """The partner's full partner.yaml as JSON, so the Builder can pre-fill every field it edits.

        With ``?format=yaml`` the text itself, as a download (to commit it to the partners repo).
        """
        text = _partner_yaml_text(request.app, partner_name) if is_safe_partner_name(partner_name) else None
        if text is None:
            return JSONResponse(status_code=404, content={"detail": f"Partner '{partner_name}' not found."})
        if request.query_params.get("format") == "yaml":
            headers = {"Content-Disposition": f'attachment; filename="{partner_name}.partner.yaml"'}
            return Response(text, media_type="application/yaml", headers=headers)
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return JSONResponse(status_code=422, content={"detail": f"partner.yaml is not valid YAML: {exc}"})
        return JSONResponse(raw)

    async def list_partners() -> JSONResponse:
        def _serialize_dp(dp: DatapointDef) -> dict:
            callback_delay: int | None = None
            callback_url_field: str | None = None
            callback_url_header: str | None = None
            if dp.pattern == "callback" and dp.endpoints:
                resp = dp.endpoints[0].response
                callback_delay = int(resp.get("callback_delay_seconds", 0))
                callback_url_field = resp.get("callback_url_field")
                callback_url_header = resp.get("callback_url_header")
            return {
                "name": dp.name,
                "pattern": dp.pattern,
                "endpoints": [
                    {
                        "method": ep.method,
                        "path": ep.path,
                        "step": ep.step,
                        "requests_per_minute": ep.rate_limit.get("requests_per_minute") if ep.rate_limit else None,
                    }
                    for ep in dp.endpoints
                ],
                "callback_delay_seconds": callback_delay,
                "callback_url_field": callback_url_field,
                "callback_url_header": callback_url_header,
                "pagination": dp.pagination,
            }

        return JSONResponse(
            [
                {
                    "partner": p.partner,
                    "description": p.description,
                    "datapoints": [_serialize_dp(dp) for dp in p.datapoints],
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
        - Routes whose endpoint, datapoint or partner is no longer in the YAML (or moved to
          another datapoint) are unregistered, with their admin routes; they are listed in
          ``removed``. Changed validate:/rate_limit:/fail: on an existing route still need a restart.
        """
        partners_dir: Path | None = request.app.state.partners_dir
        if partners_dir is None:
            return JSONResponse(
                status_code=400,
                content={"detail": "No partners_dir configured — server was not started via `imnot start`."},
            )

        # Stateless mode: a reload goes back to what partners_dir holds. Drop every partner changed
        # through the admin API first, so the files register again from scratch below.
        memory: dict[str, str | None] = request.app.state.memory_partners
        for name in memory:
            _unregister_partner_routes(request.app, name)
        partners[:] = [p for p in partners if p.partner not in memory]
        memory.clear()

        try:
            new_partners = load_partners(partners_dir)
        except Exception as exc:
            _http_logger.exception("Reload failed: %s", exc)
            return JSONResponse(status_code=500, content={"detail": "Reload failed. Check server logs for details."})

        configs: dict = request.app.state.configs
        paginated_config_refs: dict = request.app.state.paginated_config_refs
        store_: SessionStore = request.app.state.store
        registered: dict[tuple[str, str], str] = request.app.state.registered_routes
        registered_admin: set[tuple[str, str]] = request.app.state.registered_admin_dps

        updated: list[str] = []
        added: list[str] = []
        conflicts: list[str] = []
        removed: list[str] = []

        # A partner whose partner.yaml still exists but no longer loads (a typo mid-edit) keeps its
        # current routes; only definitions that are really gone are unregistered.
        on_disk = {f.resolve() for f in partners_dir.glob("*/partner.yaml")}
        loaded_files = {p.source_path.resolve() for p in new_partners}
        failing_files = on_disk - loaded_files
        kept_names = {p.partner for p in partners if p.source_path.resolve() in failing_files}
        skipped = sorted(f.parent.name for f in failing_files)  # kept partners and broken new ones

        # Unregister what the YAML no longer defines, so a deleted fixture stops answering.
        wanted = {
            (ep.method.upper(), ep.path): f"{p.partner}/{dp.name}"
            for p in new_partners
            for dp in p.datapoints
            for ep in dp.endpoints
        }
        stale = {
            key
            for key, owner in registered.items()
            if wanted.get(key) != owner and owner.split("/", 1)[0] not in kept_names
        }
        wanted_admin = {
            (p.partner, dp.name) for p in new_partners for dp in p.datapoints if dp.pattern in PAYLOAD_PATTERNS
        }
        stale_admin = {k for k in registered_admin if k not in wanted_admin and k[0] not in kept_names}
        if stale or stale_admin:
            removed = sorted(f"{method} {path}" for method, path in stale)
            removed += sorted(f"admin routes for {p}/{dp}" for p, dp in stale_admin)
            _unregister_routes(request.app, stale, stale_admin)

        for partner in new_partners:
            for dp in partner.datapoints:
                # Hot-swap static response configs for already-registered routes
                if dp.pattern == "static":
                    for ep in dp.endpoints:
                        key = (partner.partner, dp.name, ep.method.upper(), ep.path)
                        if key in configs:
                            configs[key] = ep.response
                            updated.append(f"{ep.method.upper()} {ep.path}")

                # Hot-swap paginated pagination config for already-registered routes
                if dp.pattern == "paginated":
                    for ep in dp.endpoints:
                        ref_key = (partner.partner, dp.name, ep.method.upper(), ep.path)
                        if ref_key in paginated_config_refs:
                            paginated_config_refs[ref_key][0] = dp.pagination or {}
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
                            paginated_config_refs,
                            registered,
                            request.app.state.rate_limiter,
                            request.app.state.default_limit,
                        )
                        for ep in new_eps:
                            added.append(f"{ep.method.upper()} {ep.path}")
                    except ValueError as exc:
                        conflicts.append(str(exc))

                # Register admin routes for new payload-pattern datapoints
                if dp.pattern in PAYLOAD_PATTERNS and (partner.partner, dp.name) not in registered_admin:
                    _register_admin_routes(request.app, partner, dp, store_)
                    registered_admin.add((partner.partner, dp.name))
                    added.append(f"admin routes for {partner.partner}/{dp.name}")

        seed_payloads(store_, new_partners)

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

        keep_names = {p.partner for p in new_partners} | kept_names
        partners[:] = [p for p in partners if p.partner in keep_names]

        _http_logger.info("Reload: updated=%s added=%s removed=%s conflicts=%s", updated, added, removed, conflicts)
        status = "ok" if not conflicts and not skipped else "partial"
        return JSONResponse(
            {
                "status": status,
                "updated": updated,
                "added": added,
                "removed": removed,
                "skipped": skipped,
                "conflicts": conflicts,
            }
        )

    def _hot_load_partner(app_: FastAPI, partner: PartnerDef) -> tuple[list[str], list[str]]:
        """Register *partner* on the running app and put it in the partners list.

        Returns ``(routes added, route conflicts)``.
        """
        configs_: dict = app_.state.configs
        paginated_config_refs_: dict = app_.state.paginated_config_refs
        store_: SessionStore = app_.state.store
        registered_: dict[tuple[str, str], str] = app_.state.registered_routes
        registered_admin_: set[tuple[str, str]] = app_.state.registered_admin_dps

        added: list[str] = []
        conflicts: list[str] = []

        for dp in partner.datapoints:
            # Hot-swap static response configs for already-registered routes
            if dp.pattern == "static":
                for ep in dp.endpoints:
                    key = (partner.partner, dp.name, ep.method.upper(), ep.path)
                    if key in configs_:
                        configs_[key] = ep.response

            # Hot-swap paginated pagination config for already-registered routes
            if dp.pattern == "paginated":
                for ep in dp.endpoints:
                    ref_key = (partner.partner, dp.name, ep.method.upper(), ep.path)
                    if ref_key in paginated_config_refs_:
                        paginated_config_refs_[ref_key][0] = dp.pagination or {}

            # Register brand-new consumer routes
            new_eps = [ep for ep in dp.endpoints if (ep.method.upper(), ep.path) not in registered_]
            if new_eps:
                try:
                    _register_consumer_routes(
                        app_,
                        partner,
                        dp,
                        store_,
                        configs_,
                        paginated_config_refs_,
                        registered_,
                        app_.state.rate_limiter,
                        app_.state.default_limit,
                    )
                    for ep in new_eps:
                        added.append(f"{ep.method.upper()} {ep.path}")
                except ValueError as exc:
                    conflicts.append(str(exc))

            # Register admin routes for new payload-pattern datapoints
            if dp.pattern in PAYLOAD_PATTERNS and (partner.partner, dp.name) not in registered_admin_:
                _register_admin_routes(app_, partner, dp, store_)
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
        return added, conflicts

    async def load_examples_handler(request: Request) -> JSONResponse:
        """Load the example partners of `imnot init` (staylink, bookingco, ratesync) with their payloads.

        Classic mode writes them to the partners directory, like `imnot init`. Stateless mode keeps
        them in memory, so a reload or a restart drops them. All or nothing: 409 if any of them
        already exists, 403 when the partners directory cannot be written.
        """
        stateless: bool = getattr(request.app.state, "stateless", False)
        partners_dir: Path | None = request.app.state.partners_dir
        if partners_dir is None and not stateless:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "detail": "This server has no partners directory to write the examples to. "
                    "Stop it, run `imnot init` (or create a partners/ directory) and start it again.",
                },
            )

        names = [name for name, _ in EXAMPLE_PARTNERS]
        loaded = {p.partner for p in partners}
        existing = [
            name
            for name in names
            if name in loaded or (not stateless and partners_dir is not None and (partners_dir / name).exists())
        ]
        if existing:
            return JSONResponse(
                status_code=409,
                content={
                    "status": "error",
                    "detail": f"Already there: {', '.join(existing)}. Nothing was loaded; "
                    "delete them first to load the examples again.",
                    "existing": existing,
                },
            )

        examples = [load_example_partner(name) for name in names]
        if not stateless and partners_dir is not None:
            try:
                for example, _ in examples:
                    example.source_path = write_example_partner(example.partner, partners_dir)[0]
            except OSError as exc:
                return _partners_read_only_response(exc)

        added: list[str] = []
        conflicts: list[str] = []
        for example, yaml_text in examples:
            if stateless:
                request.app.state.memory_partners[example.partner] = yaml_text
            example_added, example_conflicts = _hot_load_partner(request.app, example)
            added += example_added
            conflicts += example_conflicts
        seed_payloads(request.app.state.store, [example for example, _ in examples])
        _http_logger.info("Loaded example partners %s (%s)", names, "in memory" if stateless else "as files")

        return JSONResponse(
            status_code=201,
            content={
                "status": "ok",
                "partners": names,
                "persisted": not stateless,
                "routes_added": added,
                "routes_conflicts": conflicts,
            },
        )

    async def create_partner_handler(request: Request) -> JSONResponse:
        """Validate raw YAML body, write it to disk, and hot-load its routes.

        Query params:
            force (bool, default false) — overwrite if partner already exists.
            merge_from (partner name, optional) — first copy over the fields of that partner's current
                partner.yaml that the Builder form never writes (validate:, fail:, headers, …).
            compare_to (partner name, optional) — before writing, compare against that partner's
                current partner.yaml and return 409 with ``dropped`` if fields would be lost. Used by
                the Builder's edit mode, which does not round-trip every field.

        Returns 201 on create, 200 on overwrite, 409 on conflict or dropped fields, 422 on bad YAML,
        403 when the partners directory cannot be written.

        In stateless mode nothing is written: the partner lives in memory (and replaces any partner of
        the same name loaded from disk) until a reload or a restart.
        """
        stateless: bool = getattr(request.app.state, "stateless", False)
        partners_dir: Path | None = request.app.state.partners_dir
        if partners_dir is None and not stateless:
            return JSONResponse(
                status_code=400,
                content={"detail": "No partners_dir configured — server was not started via `imnot start`."},
            )

        force = request.query_params.get("force", "false").lower() == "true"
        yaml_text = (await request.body()).decode()

        merge_from = request.query_params.get("merge_from")
        if merge_from:
            if not is_safe_partner_name(merge_from):
                return JSONResponse(status_code=400, content={"detail": "Invalid merge_from partner name."})
            merge_text = _partner_yaml_text(request.app, merge_from)
            if merge_text is not None:
                try:
                    yaml_text = merge_unmanaged_fields(merge_text, yaml_text)
                except yaml.YAMLError:
                    pass  # invalid new YAML: register_partner below returns the 422

        compare_to = request.query_params.get("compare_to")
        if compare_to:
            if not is_safe_partner_name(compare_to):
                return JSONResponse(status_code=400, content={"detail": "Invalid compare_to partner name."})
            current_text = _partner_yaml_text(request.app, compare_to)
            if current_text is not None:
                try:
                    dropped = dropped_fields(current_text, yaml_text)
                except yaml.YAMLError:
                    dropped = []  # invalid new YAML: register_partner below returns the 422
                if dropped:
                    return JSONResponse(
                        status_code=409,
                        content={
                            "status": "error",
                            "detail": "Saving would drop fields from the current partner.yaml.",
                            "dropped": dropped,
                        },
                    )

        try:
            if stateless:
                partner = validate_partner_yaml(yaml_text)
                created = not any(p.partner == partner.partner for p in partners)
                if not created and not force:
                    raise FileExistsError(f"Partner '{partner.partner}' already exists. Use ?force=true to replace it.")
            else:
                result = register_partner(yaml_text, partners_dir, force=force)
                partner, created = result.partner, result.created
        except (yaml.YAMLError, ValueError) as exc:
            return JSONResponse(status_code=422, content={"status": "error", "detail": str(exc)})
        except FileExistsError as exc:
            return JSONResponse(status_code=409, content={"status": "error", "detail": str(exc)})
        except OSError as exc:
            return _partners_read_only_response(exc)

        if stateless:
            # Replace the partner whole: its old routes go away and every endpoint registers again
            # below, so the edit applies completely (validate:, fail:, removed endpoints…) with no reload.
            _unregister_partner_routes(request.app, partner.partner)
            request.app.state.memory_partners[partner.partner] = yaml_text
        added, conflicts = _hot_load_partner(request.app, partner)

        payload_dp_names = {dp.name for dp in partner.datapoints if dp.pattern in PAYLOAD_PATTERNS}
        status_code = 201 if created else 200
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok",
                "partner": partner.partner,
                "description": partner.description,
                # Stateless mode writes no file: both are null there.
                "directory": None if stateless else f"partners/{partner.partner}",
                "file": None if stateless else f"partners/{partner.partner}/partner.yaml",
                "created": created,
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
    app.add_api_route("/imnot/admin/sessions/{session_id}", delete_session, methods=["DELETE"])
    app.add_api_route("/imnot/admin/faults", reset_faults, methods=["DELETE"])
    app.add_api_route("/imnot/admin/requests", list_requests, methods=["GET"])
    app.add_api_route("/imnot/admin/requests", clear_requests, methods=["DELETE"])
    app.add_api_route("/imnot/admin/partners", list_partners, methods=["GET"])
    app.add_api_route("/imnot/admin/partners", create_partner_handler, methods=["POST"])
    app.add_api_route("/imnot/admin/partners/examples", load_examples_handler, methods=["POST"])
    app.add_api_route("/imnot/admin/partners/{partner_name}", get_partner, methods=["GET"])
    app.add_api_route("/imnot/admin/partners/{partner_name}", delete_partner, methods=["DELETE"])
    app.add_api_route("/imnot/admin/reload", reload_partners, methods=["POST"])
    app.add_api_route("/imnot/admin/postman", postman_collection, methods=["GET"])
    logger.debug("Registered infra routes")
