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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI

from imnot.engine.router import register_routes
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import load_partners

logger = logging.getLogger(__name__)

DEFAULT_PARTNERS_DIR = Path("partners")
DEFAULT_DB_PATH = Path("imnot.db")


def create_app(
    partners_dir: Path = DEFAULT_PARTNERS_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    admin_key: str | None = None,
) -> FastAPI:
    """Build and return a fully configured FastAPI application.

    A fresh SessionStore and partner list are created on every call, so tests
    can call this multiple times without shared state.

    If *admin_key* is provided, all ``/imnot/admin/*`` endpoints require
    ``Authorization: Bearer <admin_key>``.
    """
    store = SessionStore(db_path=db_path)
    partners = load_partners(partners_dir)

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

    register_routes(app, partners, store, admin_key=admin_key, partners_dir=partners_dir)
    return app


def create_app_from_env() -> FastAPI:
    """Uvicorn factory used when ``imnot start --reload`` is active.

    Configuration is read from environment variables set by the CLI before
    handing control to uvicorn:

    - ``IMNOT_PARTNERS_DIR``  (default: ``partners``)
    - ``IMNOT_DB_PATH``       (default: ``imnot.db``)
    - ``IMNOT_ADMIN_KEY``     (default: none)
    """
    partners_dir = Path(os.environ.get("IMNOT_PARTNERS_DIR", str(DEFAULT_PARTNERS_DIR)))
    db_path = Path(os.environ.get("IMNOT_DB_PATH", str(DEFAULT_DB_PATH)))
    admin_key = os.environ.get("IMNOT_ADMIN_KEY") or None
    return create_app(partners_dir=partners_dir, db_path=db_path, admin_key=admin_key)
