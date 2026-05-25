"""Tests for the static pattern handler."""

import json

import pytest
from fastapi import Request

from imnot.engine.patterns.static import make_static_handler
from imnot.loader.yaml_loader import EndpointDef


def _make_handler(method: str, path: str, response: dict, validate: dict | None = None):
    """Convenience wrapper — creates a fresh configs dict per call."""
    ep = EndpointDef(method=method, path=path, step=None, response=response, validate=validate)
    return make_static_handler("testpartner", "testdp", ep, {})


def _request(
    body: bytes = b"",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "query_string": query_string,
        "headers": headers or [],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive=receive)


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


def _empty_request() -> Request:
    return _request()


@pytest.mark.asyncio
async def test_returns_body_from_yaml():
    handler = _make_handler(
        "POST",
        "/leanpms/token",
        {"status": 200, "body": {"token": "2893e0a65fcfffcbb86e16fb1bc1c612fcd3eb78"}},
    )
    response = await handler(_empty_request())

    body = json.loads(response.body)
    assert response.status_code == 200
    assert body == {"token": "2893e0a65fcfffcbb86e16fb1bc1c612fcd3eb78"}


@pytest.mark.asyncio
async def test_respects_custom_status_code():
    handler = _make_handler("GET", "/health", {"status": 204, "body": {}})
    response = await handler(_empty_request())
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_defaults_to_200_when_status_absent():
    handler = _make_handler("POST", "/token", {"body": {"token": "abc"}})
    response = await handler(_empty_request())
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_empty_body_when_body_absent():
    handler = _make_handler("POST", "/token", {"status": 200})
    response = await handler(_empty_request())
    body = json.loads(response.body)
    assert body == {}


@pytest.mark.asyncio
async def test_arbitrary_body_shape():
    handler = _make_handler(
        "POST",
        "/auth/session",
        {"status": 201, "body": {"sessionId": "xyz", "expiresIn": 86400, "roles": ["admin"]}},
    )
    response = await handler(_empty_request())
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

    r1 = await handler(_empty_request())
    assert json.loads(r1.body) == {"items": []}

    # Simulate a YAML edit picked up by the reload endpoint
    key = ("p", "dp", "GET", "/v1/items")
    configs[key] = {"status": 200, "body": {"items": [{"id": 1}]}}

    r2 = await handler(_empty_request())
    assert json.loads(r2.body) == {"items": [{"id": 1}]}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_body_passes_validation():
    handler = _make_handler(
        "POST",
        "/bookingco/auth",
        {"status": 200, "body": {"token": "abc"}},
        validate={"body": {"client_id": {"required": True}}},
    )
    req = _request(body=b'{"client_id": "my-client"}')
    response = await handler(req)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_invalid_body_returns_422():
    handler = _make_handler(
        "POST",
        "/bookingco/auth",
        {"status": 200, "body": {"token": "abc"}},
        validate={"body": {"client_id": {"required": True}}},
    )
    req = _request(body=b"{}")
    response = await handler(req)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert "detail" in body
    assert any("client_id" in e for e in body["detail"])


@pytest.mark.asyncio
async def test_missing_required_query_param_returns_422():
    handler = _make_handler(
        "GET",
        "/bookingco/items",
        {"status": 200, "body": {"items": []}},
        validate={"query": {"format": {"required": True}}},
    )
    req = _request(query_string=b"")
    response = await handler(req)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert any("query.format" in e for e in body["detail"])


@pytest.mark.asyncio
async def test_malformed_json_body_treated_as_none_fires_required_error():
    handler = _make_handler(
        "POST",
        "/bookingco/auth",
        {"status": 200, "body": {"token": "abc"}},
        validate={"body": {"client_id": {"required": True}}},
    )
    req = _request(body=b"not-valid-json{{{", headers=[(b"content-type", b"application/json")])
    response = await handler(req)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert any("client_id" in e for e in body["detail"])


@pytest.mark.asyncio
async def test_body_as_json_string_is_parsed_and_returned():
    raw_body = '{"key": "value", "count": 42}'
    handler = _make_handler(
        "GET",
        "/bookingco/caps",
        {"status": 200, "body": raw_body},
    )
    response = await handler(_empty_request())
    body = json.loads(response.body)
    assert body == {"key": "value", "count": 42}


@pytest.mark.asyncio
async def test_invalid_json_string_body_returned_as_raw_string():
    handler = _make_handler(
        "GET",
        "/bookingco/caps",
        {"status": 200, "body": "not json"},
    )
    response = await handler(_empty_request())
    body = json.loads(response.body)
    assert body == "not json"
