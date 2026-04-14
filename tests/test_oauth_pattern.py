"""Tests for the OAuth pattern handler."""

import pytest

from imnot.engine.patterns.oauth import make_oauth_handler
from imnot.loader.yaml_loader import EndpointDef


def _make_endpoint(response: dict) -> EndpointDef:
    return EndpointDef(method="POST", path="/oauth/token", step=None, response=response)


# ---------------------------------------------------------------------------
# Handler construction
# ---------------------------------------------------------------------------


def test_handler_is_callable():
    ep = _make_endpoint({"status": 200, "token_type": "Bearer", "expires_in": 3600})
    handler = make_oauth_handler(ep)
    assert callable(handler)


def test_handler_has_unique_name():
    ep = _make_endpoint({"status": 200, "token_type": "Bearer", "expires_in": 3600})
    handler = make_oauth_handler(ep)
    assert "oauth" in handler.__name__


# ---------------------------------------------------------------------------
# Response shape (invoke the coroutine directly)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oauth_response_shape():
    ep = _make_endpoint({"status": 200, "token_type": "Bearer", "expires_in": 3600})
    handler = make_oauth_handler(ep)
    response = await handler()

    import json
    body = json.loads(response.body)

    assert response.status_code == 200
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert isinstance(body["access_token"], str)
    assert len(body["access_token"]) > 0


@pytest.mark.asyncio
async def test_oauth_respects_yaml_config():
    ep = _make_endpoint({"status": 200, "token_type": "MAC", "expires_in": 7200})
    handler = make_oauth_handler(ep)
    response = await handler()

    import json
    body = json.loads(response.body)

    assert body["token_type"] == "MAC"
    assert body["expires_in"] == 7200


@pytest.mark.asyncio
async def test_oauth_defaults_when_fields_missing():
    """Handler should not crash if optional YAML fields are absent."""
    ep = _make_endpoint({"status": 200})
    handler = make_oauth_handler(ep)
    response = await handler()

    import json
    body = json.loads(response.body)

    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
