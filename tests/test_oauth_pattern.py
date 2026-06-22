"""Tests for the OAuth pattern handler."""

import json

import pytest
from fastapi import Request

from imnot.engine.patterns.oauth import make_oauth_handler
from imnot.loader.yaml_loader import EndpointDef


def _make_endpoint(response: dict, validate: dict | None = None) -> EndpointDef:
    return EndpointDef(method="POST", path="/oauth/token", step=None, response=response, validate=validate)


def _request(body: bytes = b"") -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/oauth/token",
        "query_string": b"",
        "headers": [],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive=receive)


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


def _empty_request() -> Request:
    return _request()


@pytest.mark.asyncio
async def test_oauth_response_shape():
    ep = _make_endpoint({"status": 200, "token_type": "Bearer", "expires_in": 3600})
    handler = make_oauth_handler(ep)
    response = await handler(_empty_request())

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
    response = await handler(_empty_request())

    body = json.loads(response.body)

    assert body["token_type"] == "MAC"
    assert body["expires_in"] == 7200


@pytest.mark.asyncio
async def test_oauth_defaults_when_fields_missing():
    """Handler should not crash if optional YAML fields are absent."""
    ep = _make_endpoint({"status": 200})
    handler = make_oauth_handler(ep)
    response = await handler(_empty_request())

    body = json.loads(response.body)

    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_body_passes_oauth_validation():
    ep = _make_endpoint(
        {"status": 200},
        validate={"body": {"client_id": {"required": True}}},
    )
    handler = make_oauth_handler(ep)
    req = _request(body=b'{"client_id": "ratesync-app"}')
    response = await handler(req)
    assert response.status_code == 200
    body = json.loads(response.body)
    assert "access_token" in body


@pytest.mark.asyncio
async def test_missing_required_field_returns_422():
    ep = _make_endpoint(
        {"status": 200},
        validate={"body": {"client_id": {"required": True}}},
    )
    handler = make_oauth_handler(ep)
    req = _request(body=b"{}")
    response = await handler(req)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert "detail" in body
    assert any("client_id" in e for e in body["detail"])


@pytest.mark.asyncio
async def test_malformed_json_body_treated_as_none_fires_required_error():
    ep = _make_endpoint(
        {"status": 200},
        validate={"body": {"client_id": {"required": True}}},
    )
    handler = make_oauth_handler(ep)
    req = _request(body=b"not-valid-json{{{")
    response = await handler(req)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert any("client_id" in e for e in body["detail"])
