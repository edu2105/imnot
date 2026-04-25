"""
FastAPI application factory.

Responsibilities:
- Create and configure the FastAPI app instance.
- Initialise the SessionStore and load partner definitions.
- Delegate route registration to the dynamic router.
- Tear down the store cleanly on shutdown via the FastAPI lifespan hook.
- Expose `create_app()` as the single entry point used by both the CLI and tests.
- Expose `create_app_from_env()` as a uvicorn factory for --reload mode.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from imnot.config import UIConfig, load_config
from imnot.engine.router import register_routes
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import load_partners

logger = logging.getLogger(__name__)
_http_logger = logging.getLogger("imnot.http")

DEFAULT_PARTNERS_DIR = Path("partners")
DEFAULT_DB_PATH = Path("imnot.db")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request/response to the imnot.http stream, excluding /healthz."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.url.path == "/healthz":
            return await call_next(request)

        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        session_id = request.headers.get("X-Imnot-Session")
        partner = request.path_params.get("partner") if request.path_params else None
        datapoint = request.path_params.get("datapoint") if request.path_params else None

        _http_logger.info(
            "%s %s %d %dms%s%s%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            f" partner={partner}" if partner else "",
            f" datapoint={datapoint}" if datapoint else "",
            f" session={session_id}" if session_id else "",
        )

        response.headers["X-Request-ID"] = request_id
        return response


def create_app(
    partners_dir: Path | None = DEFAULT_PARTNERS_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    admin_key: str | None = None,
    base_url: str = "http://localhost:8000",
    default_limit: int = 50,
    ui_config: UIConfig | None = None,
) -> FastAPI:
    """Build and return a fully configured FastAPI application.

    A fresh SessionStore and partner list are created on every call, so tests
    can call this multiple times without shared state.

    If *admin_key* is provided, all ``/imnot/admin/*`` endpoints require
    ``Authorization: Bearer <admin_key>``.
    """
    store = SessionStore(db_path=db_path)
    partners = load_partners(partners_dir) if partners_dir is not None else []

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        store.init()
        logger.info("imnot starting — %d partner(s) loaded", len(partners))
        if admin_key:
            logger.info("Admin endpoints protected by Bearer token auth")
        yield
        store.close()
        logger.info("imnot shut down")

    app = FastAPI(
        title="imnot",
        description="Stateful API mock server for integration testing",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(LoggingMiddleware)
    register_routes(
        app,
        partners,
        store,
        admin_key=admin_key,
        partners_dir=partners_dir,
        base_url=base_url,
        default_limit=default_limit,
        ui_config=ui_config,
    )
    return app


def create_app_from_env() -> FastAPI:
    """Uvicorn factory used when ``imnot start --reload`` is active.

    Configuration is read from environment variables set by the CLI before
    handing control to uvicorn:

    - ``IMNOT_PARTNERS_DIR``  (default: ``partners``)
    - ``IMNOT_DB_PATH``       (default: ``imnot.db``)
    - ``IMNOT_ADMIN_KEY``     (default: none)

    ``default_limit`` for the paginated pattern is read from ``imnot.toml`` via ``load_config()``.
    """
    partners_dir_env = os.environ.get("IMNOT_PARTNERS_DIR", str(DEFAULT_PARTNERS_DIR))
    partners_dir = Path(partners_dir_env) if partners_dir_env else None
    db_path = Path(os.environ.get("IMNOT_DB_PATH", str(DEFAULT_DB_PATH)))
    admin_key = os.environ.get("IMNOT_ADMIN_KEY") or None

    config_path: Path | None = None
    config_search = Path(os.environ.get("IMNOT_CONFIG_PATH", "imnot.toml"))
    if config_search.exists():
        config_path = config_search
    config = load_config(config_path)
    default_limit = config.pagination.default_limit

    return create_app(
        partners_dir=partners_dir,
        db_path=db_path,
        admin_key=admin_key,
        default_limit=default_limit,
        ui_config=config.ui,
    )
