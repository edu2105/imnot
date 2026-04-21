"""Shared pytest fixtures."""

from __future__ import annotations

import logging

import pytest


@pytest.fixture(autouse=True)
def reset_imnot_loggers():
    """Clear handlers and re-enable propagation on imnot loggers after each test."""
    yield
    for name in ("imnot.cli", "imnot.http"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True
