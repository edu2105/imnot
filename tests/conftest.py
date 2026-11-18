"""Shared pytest fixtures."""

from __future__ import annotations

import logging
import os

import pytest


@pytest.fixture(autouse=True)
def reset_imnot_loggers():
    """Clear handlers and re-enable propagation on imnot loggers after each test."""
    yield
    for name in ("imnot.cli", "imnot.http"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True


@pytest.fixture(autouse=True)
def isolate_imnot_env():
    """Run each test without IMNOT_* variables, and drop the ones it leaves behind.

    `imnot start` reads its options from them, and `start --reload` writes them to os.environ
    for the uvicorn factory, so one test's server settings would leak into the next.
    """
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("IMNOT_")}
    yield
    for key in [k for k in os.environ if k.startswith("IMNOT_")]:
        del os.environ[key]
    os.environ.update(saved)
