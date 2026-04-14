"""Tests for the static pattern handler."""

import json

import pytest

from imnot.engine.patterns.static import make_static_handler
from imnot.loader.yaml_loader import EndpointDef


def _make_handler(method: str, path: str, response: dict):
    """Convenience wrapper — creates a fresh configs dict per call."""
    ep = EndpointDef(method=method, path=path, step=None, response=response)
    return make_static_handler("testpartner", "testdp", ep, {})


# ---------------------------------------------------------------------------
# Handler construction
# ---------------------------------------------------------------------------


def test_handler_is_callable():
    handler = _make_handler("POST", "/leanpms/token", {"status": 200, "body": {"token": "abc"}})
    assert callable(handler)


def test_handler_has_unique_name():
    handler = _make_handler("POST", "/leanpms/token", {"status": 200, "body": {"token": "abc"}})
    assert "static" in handler.__name__


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_body_from_yaml():
    handler = _make_handler(
        "POST", "/leanpms/token",
        {"status": 200, "body": {"token": "2893e0a65fcfffcbb86e16fb1bc1c612fcd3eb78"}},
    )
    response = await handler()

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body == {"token": "2893e0a65fcfffcbb86e16fb1bc1c612fcd3eb78"}


@pytest.mark.asyncio
async def test_respects_custom_status_code():
    handler = _make_handler("GET", "/health", {"status": 204, "body": {}})
    response = await handler()
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_defaults_to_200_when_status_absent():
    handler = _make_handler("POST", "/token", {"body": {"token": "abc"}})
    response = await handler()
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_empty_body_when_body_absent():
    handler = _make_handler("POST", "/token", {"status": 200})
    response = await handler()
    body = json.loads(response.body)
    assert body == {}


@pytest.mark.asyncio
async def test_arbitrary_body_shape():
    handler = _make_handler(
        "POST", "/auth/session",
        {"status": 201, "body": {"sessionId": "xyz", "expiresIn": 86400, "roles": ["admin"]}},
    )
    response = await handler()
    body = json.loads(response.body)
    assert body["sessionId"] == "xyz"
    assert body["expiresIn"] == 86400
    assert body["roles"] == ["admin"]


# ---------------------------------------------------------------------------
# Hot-reload: config update via shared configs dict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_picks_up_config_update():
    """Mutating the shared configs dict is reflected in the very next request."""
    ep = EndpointDef(method="GET", path="/v1/items", step=None, response={"status": 200, "body": {"items": []}})
    configs: dict = {}
    handler = make_static_handler("p", "dp", ep, configs)

    r1 = await handler()
    assert json.loads(r1.body) == {"items": []}

    # Simulate a YAML edit picked up by the reload endpoint
    key = ("p", "dp", "GET", "/v1/items")
    configs[key] = {"status": 200, "body": {"items": [{"id": 1}]}}

    r2 = await handler()
    assert json.loads(r2.body) == {"items": [{"id": 1}]}
