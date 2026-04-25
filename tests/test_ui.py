"""Tests for the admin UI route."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imnot.config import UIConfig
from imnot.engine.router import register_routes
from imnot.engine.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


@pytest.fixture
def ui_client(store):
    app = FastAPI()
    register_routes(app, [], store, ui_config=UIConfig(enabled=True, default_theme="light"))
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def ui_disabled_client(store):
    app = FastAPI()
    register_routes(app, [], store, ui_config=UIConfig(enabled=False))
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def auth_ui_client(store):
    app = FastAPI()
    register_routes(app, [], store, admin_key="secret", ui_config=UIConfig(enabled=True))
    return TestClient(app, raise_server_exceptions=True)


def test_ui_returns_200(ui_client):
    r = ui_client.get("/imnot/admin/ui")
    assert r.status_code == 200


def test_ui_content_type_is_html(ui_client):
    r = ui_client.get("/imnot/admin/ui")
    assert "text/html" in r.headers["content-type"]


def test_ui_contains_imnot_branding(ui_client):
    r = ui_client.get("/imnot/admin/ui")
    assert b"imnot" in r.content


def test_ui_theme_embedded_in_html(ui_client):
    r = ui_client.get("/imnot/admin/ui")
    assert b'data-theme="light"' in r.content


def test_ui_dark_theme_embedded(store):
    app = FastAPI()
    register_routes(app, [], store, ui_config=UIConfig(enabled=True, default_theme="dark"))
    client = TestClient(app)
    r = client.get("/imnot/admin/ui")
    assert r.status_code == 200
    assert b'data-theme="dark"' in r.content


def test_ui_system_theme_embedded(store):
    app = FastAPI()
    register_routes(app, [], store, ui_config=UIConfig(enabled=True, default_theme="system"))
    client = TestClient(app)
    r = client.get("/imnot/admin/ui")
    assert r.status_code == 200
    assert b'data-theme="system"' in r.content


def test_ui_disabled_returns_404(ui_disabled_client):
    r = ui_disabled_client.get("/imnot/admin/ui")
    assert r.status_code == 404


def test_ui_auth_gated_returns_401_without_token(auth_ui_client):
    r = auth_ui_client.get("/imnot/admin/ui")
    assert r.status_code == 401


def test_ui_auth_gated_returns_200_with_token(auth_ui_client):
    r = auth_ui_client.get("/imnot/admin/ui", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_ui_default_config_when_none_passed(store):
    app = FastAPI()
    register_routes(app, [], store, ui_config=None)
    client = TestClient(app)
    r = client.get("/imnot/admin/ui")
    assert r.status_code == 200


def test_ui_placeholder_replaced(ui_client):
    r = ui_client.get("/imnot/admin/ui")
    assert b"__IMNOT_THEME__" not in r.content
