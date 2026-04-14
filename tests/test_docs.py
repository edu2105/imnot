"""Tests for the /imnot/docs endpoints."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imnot.engine.router import register_routes
from imnot.engine.session_store import SessionStore

PARTNERS_DIR = Path(__file__).parent.parent / "partners"
PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


@pytest.fixture
def client(store):
    app = FastAPI()
    partners = []
    register_routes(app, partners, store, partners_dir=PARTNERS_DIR)
    return TestClient(app)


@pytest.fixture
def client_no_partners_dir(store):
    """Client registered without a partners_dir — triggers the fallback path resolution."""
    app = FastAPI()
    register_routes(app, [], store, partners_dir=None)
    return TestClient(app)


@pytest.fixture
def client_missing_files(store, tmp_path):
    """Client whose partners_dir points to a directory with no README files."""
    partners_subdir = tmp_path / "partners"
    partners_subdir.mkdir()
    app = FastAPI()
    register_routes(app, [], store, partners_dir=partners_subdir)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /imnot/docs
# ---------------------------------------------------------------------------


def test_docs_readme_returns_200(client):
    resp = client.get("/imnot/docs")
    assert resp.status_code == 200


def test_docs_readme_content_type_is_plain_text(client):
    resp = client.get("/imnot/docs")
    assert "text/plain" in resp.headers["content-type"]


def test_docs_readme_contains_expected_content(client):
    resp = client.get("/imnot/docs")
    assert "Mirage" in resp.text


def test_docs_readme_missing_returns_404(client_missing_files):
    resp = client_missing_files.get("/imnot/docs")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /imnot/docs/partners
# ---------------------------------------------------------------------------


def test_docs_partners_readme_returns_200(client):
    resp = client.get("/imnot/docs/partners")
    assert resp.status_code == 200


def test_docs_partners_readme_content_type_is_plain_text(client):
    resp = client.get("/imnot/docs/partners")
    assert "text/plain" in resp.headers["content-type"]


def test_docs_partners_readme_contains_expected_content(client):
    resp = client.get("/imnot/docs/partners")
    assert "partner" in resp.text.lower()


def test_docs_partners_readme_missing_returns_404(client_missing_files):
    resp = client_missing_files.get("/imnot/docs/partners")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Fallback path resolution (no partners_dir)
# ---------------------------------------------------------------------------


def test_docs_readme_fallback_returns_200(client_no_partners_dir):
    resp = client_no_partners_dir.get("/imnot/docs")
    assert resp.status_code == 200


def test_docs_partners_readme_fallback_returns_200(client_no_partners_dir):
    resp = client_no_partners_dir.get("/imnot/docs/partners")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Docs endpoints are not protected by admin auth
# ---------------------------------------------------------------------------


def test_docs_not_protected_by_admin_key(store):
    app = FastAPI()
    register_routes(app, [], store, admin_key="secret", partners_dir=PARTNERS_DIR)
    c = TestClient(app)
    # No Authorization header — should still return 200
    resp = c.get("/imnot/docs")
    assert resp.status_code == 200


def test_docs_partners_not_protected_by_admin_key(store):
    app = FastAPI()
    register_routes(app, [], store, admin_key="secret", partners_dir=PARTNERS_DIR)
    c = TestClient(app)
    resp = c.get("/imnot/docs/partners")
    assert resp.status_code == 200
