"""Tests for the push pattern handler."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mirage.engine.patterns.push import make_push_handler
from mirage.engine.router import register_routes
from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import DatapointDef, EndpointDef, load_partners

CALLBACK_URL = "http://consumer/webhook"

_BODY_FIELD_YAML = """\
partner: pushpartner
description: Push test partner
datapoints:
  - name: notification
    description: Webhook notification
    pattern: push
    endpoints:
      - method: POST
        path: /pushpartner/notify
        response:
          status: 202
          callback_url_field: callbackUrl
"""

_HEADER_YAML = """\
partner: pushpartner
description: Push test partner (header source)
datapoints:
  - name: notification
    description: Webhook notification
    pattern: push
    endpoints:
      - method: POST
        path: /pushpartner/notify
        response:
          status: 202
          callback_url_header: X-Callback-URL
"""

_DELAY_YAML = """\
partner: pushpartner
description: Push test partner with delay
datapoints:
  - name: notification
    description: Webhook notification
    pattern: push
    endpoints:
      - method: POST
        path: /pushpartner/notify
        response:
          status: 202
          callback_url_field: callbackUrl
          callback_delay_seconds: 0.01
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


def _build_client(yaml_text: str, store: SessionStore, tmp_path: Path) -> TestClient:
    partner_dir = tmp_path / "pushpartner"
    partner_dir.mkdir(exist_ok=True)
    (partner_dir / "partner.yaml").write_text(yaml_text)
    app = FastAPI()
    partners = load_partners(tmp_path)
    register_routes(app, partners, store)
    return TestClient(app, raise_server_exceptions=True)


def _mock_httpx(success: bool = True):
    """Patch httpx.AsyncClient to record calls without making real HTTP requests."""
    mock_response = MagicMock()
    mock_response.is_success = success
    mock_response.status_code = 200 if success else 500

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = AsyncMock(return_value=mock_response)

    return patch("mirage.engine.patterns.push.httpx.AsyncClient", return_value=mock_client), mock_client


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------


def test_both_callback_sources_raises_at_startup(store):
    """Specifying both callback_url_field and callback_url_header is a config error."""
    ep = EndpointDef(
        method="POST", path="/partner/notify", step=None,
        response={
            "status": 202,
            "callback_url_field": "callbackUrl",
            "callback_url_header": "X-Callback-URL",
        },
    )
    dp = DatapointDef(name="notification", description="", pattern="push", endpoints=[ep])
    with pytest.raises(ValueError, match="only one of"):
        make_push_handler("partner", dp, ep, store)


def test_no_callback_source_raises_at_startup(store):
    """Omitting both callback_url_field and callback_url_header is a config error."""
    ep = EndpointDef(
        method="POST", path="/partner/notify", step=None,
        response={"status": 202},
    )
    dp = DatapointDef(name="notification", description="", pattern="push", endpoints=[ep])
    with pytest.raises(ValueError, match="one of 'callback_url_field' or 'callback_url_header'"):
        make_push_handler("partner", dp, ep, store)


# ---------------------------------------------------------------------------
# Submit — callback URL from body field
# ---------------------------------------------------------------------------


def test_submit_missing_body_field_returns_400(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    r = client.post("/pushpartner/notify", json={"otherField": "value"})
    assert r.status_code == 400
    assert "callbackUrl" in r.json()["detail"]


def test_submit_invalid_json_returns_400(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    r = client.post(
        "/pushpartner/notify",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_submit_body_field_returns_configured_status(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    store.store_global_payload("pushpartner", "notification", {"event": "ready"})
    with patcher:
        r = client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
    assert r.status_code == 202


def test_submit_body_field_returns_request_id(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    store.store_global_payload("pushpartner", "notification", {"event": "ready"})
    with patcher:
        r = client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
    body = r.json()
    assert "request_id" in body
    assert len(body["request_id"]) == 36  # UUID


def test_submit_stores_push_request_in_db(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    store.store_global_payload("pushpartner", "notification", {"event": "ready"})
    with patcher:
        r = client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
    request_id = r.json()["request_id"]
    row = store.get_push_request(request_id)
    assert row is not None
    assert row["callback_url"] == CALLBACK_URL
    assert row["partner"] == "pushpartner"
    assert row["datapoint"] == "notification"


def test_submit_fires_callback_with_global_payload(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    payload = {"event": "confirmed", "id": "ABC"}
    store.store_global_payload("pushpartner", "notification", payload)
    with patcher:
        client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
    mock_client.request.assert_called_once()
    call_kwargs = mock_client.request.call_args
    assert call_kwargs.args[0] == "POST"
    assert call_kwargs.args[1] == CALLBACK_URL
    assert call_kwargs.kwargs["json"] == payload


def test_submit_no_payload_skips_callback(store, tmp_path):
    """When no payload is stored, the submit succeeds but the callback is not fired."""
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    with patcher:
        r = client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
    assert r.status_code == 202
    mock_client.request.assert_not_called()


# ---------------------------------------------------------------------------
# Submit — callback URL from header
# ---------------------------------------------------------------------------


def test_submit_missing_header_returns_400(store, tmp_path):
    client = _build_client(_HEADER_YAML, store, tmp_path)
    r = client.post("/pushpartner/notify", json={"someField": "value"})
    assert r.status_code == 400
    assert "X-Callback-URL" in r.json()["detail"]


def test_submit_header_fires_callback(store, tmp_path):
    client = _build_client(_HEADER_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    payload = {"event": "confirmed"}
    store.store_global_payload("pushpartner", "notification", payload)
    with patcher:
        r = client.post(
            "/pushpartner/notify",
            json={},
            headers={"X-Callback-URL": CALLBACK_URL},
        )
    assert r.status_code == 202
    mock_client.request.assert_called_once()
    assert mock_client.request.call_args.args[1] == CALLBACK_URL


def test_submit_header_stores_callback_url_in_db(store, tmp_path):
    client = _build_client(_HEADER_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    store.store_global_payload("pushpartner", "notification", {"event": "ok"})
    with patcher:
        r = client.post(
            "/pushpartner/notify",
            json={},
            headers={"X-Callback-URL": CALLBACK_URL},
        )
    row = store.get_push_request(r.json()["request_id"])
    assert row["callback_url"] == CALLBACK_URL


# ---------------------------------------------------------------------------
# Session isolation
# ---------------------------------------------------------------------------


def test_submit_uses_session_payload_when_header_present(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    session_id = store.store_session_payload("pushpartner", "notification", {"user": "alice"})
    store.store_global_payload("pushpartner", "notification", {"user": "global"})
    with patcher:
        client.post(
            "/pushpartner/notify",
            json={"callbackUrl": CALLBACK_URL},
            headers={"X-Mirage-Session": session_id},
        )
    delivered = mock_client.request.call_args.kwargs["json"]
    assert delivered == {"user": "alice"}


def test_submit_uses_global_payload_when_no_session(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    store.store_global_payload("pushpartner", "notification", {"user": "global"})
    with patcher:
        client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
    delivered = mock_client.request.call_args.kwargs["json"]
    assert delivered == {"user": "global"}


def test_submit_session_id_stored_in_push_request(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    session_id = store.store_session_payload("pushpartner", "notification", {"x": 1})
    with patcher:
        r = client.post(
            "/pushpartner/notify",
            json={"callbackUrl": CALLBACK_URL},
            headers={"X-Mirage-Session": session_id},
        )
    row = store.get_push_request(r.json()["request_id"])
    assert row["session_id"] == session_id


# ---------------------------------------------------------------------------
# Callback delay
# ---------------------------------------------------------------------------


def test_submit_with_delay_still_fires_callback(store, tmp_path):
    """callback_delay_seconds > 0 still results in the callback being fired."""
    client = _build_client(_DELAY_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    store.store_global_payload("pushpartner", "notification", {"event": "ok"})
    with patcher:
        client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
    mock_client.request.assert_called_once()


# ---------------------------------------------------------------------------
# Retrigger admin route
# ---------------------------------------------------------------------------


def test_retrigger_unknown_request_id_returns_404(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    r = client.post("/mirage/admin/pushpartner/notification/push/nonexistent-id/retrigger")
    assert r.status_code == 404
    assert "nonexistent-id" in r.json()["detail"]


def test_retrigger_fires_callback_again(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    payload = {"event": "confirmed"}
    store.store_global_payload("pushpartner", "notification", payload)

    with patcher:
        # Initial submit
        r = client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
        request_id = r.json()["request_id"]
        assert mock_client.request.call_count == 1

        # Retrigger
        r2 = client.post(
            f"/mirage/admin/pushpartner/notification/push/{request_id}/retrigger"
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "dispatched"
        assert r2.json()["request_id"] == request_id
        assert mock_client.request.call_count == 2


def test_retrigger_uses_updated_payload(store, tmp_path):
    """After updating the payload, retrigger delivers the new version."""
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    store.store_global_payload("pushpartner", "notification", {"version": 1})

    with patcher:
        r = client.post("/pushpartner/notify", json={"callbackUrl": CALLBACK_URL})
        request_id = r.json()["request_id"]

        # Update payload
        store.store_global_payload("pushpartner", "notification", {"version": 2})

        # Retrigger — should deliver version 2
        client.post(
            f"/mirage/admin/pushpartner/notification/push/{request_id}/retrigger"
        )

    deliveries = mock_client.request.call_args_list
    assert len(deliveries) == 2
    assert deliveries[0].kwargs["json"] == {"version": 1}
    assert deliveries[1].kwargs["json"] == {"version": 2}


def test_retrigger_uses_original_session(store, tmp_path):
    """Retrigger resolves payload using the session_id from the original submit."""
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    patcher, mock_client = _mock_httpx()
    session_id = store.store_session_payload("pushpartner", "notification", {"user": "alice"})

    with patcher:
        r = client.post(
            "/pushpartner/notify",
            json={"callbackUrl": CALLBACK_URL},
            headers={"X-Mirage-Session": session_id},
        )
        request_id = r.json()["request_id"]

        # Retrigger — no session header needed, it's stored
        client.post(
            f"/mirage/admin/pushpartner/notification/push/{request_id}/retrigger"
        )

    delivered = mock_client.request.call_args_list[-1].kwargs["json"]
    assert delivered == {"user": "alice"}


# ---------------------------------------------------------------------------
# Admin route presence
# ---------------------------------------------------------------------------


def test_push_has_admin_payload_routes(store, tmp_path):
    """push pattern gets the standard payload upload/inspect admin routes."""
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    r = client.post(
        "/mirage/admin/pushpartner/notification/payload",
        json={"event": "test"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_push_has_admin_session_payload_route(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    r = client.post(
        "/mirage/admin/pushpartner/notification/payload/session",
        json={"event": "test"},
    )
    assert r.status_code == 200
    assert "session_id" in r.json()


def test_push_retrigger_route_exists(store, tmp_path):
    """The retrigger route returns 404 (unknown ID) not 405 (route missing)."""
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    r = client.post(
        "/mirage/admin/pushpartner/notification/push/some-id/retrigger"
    )
    assert r.status_code == 404  # route exists, ID just unknown
