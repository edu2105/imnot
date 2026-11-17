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
def client_missing_files(store, tmp_path, monkeypatch):
    """Client where neither the packaged docs nor the repo-root docs exist."""
    import imnot.engine.router as router_mod

    missing = (tmp_path / "nope.md", tmp_path / "nope2.md")
    monkeypatch.setattr(router_mod, "_DOC_FILES", {"readme": missing, "partners": missing})
    app = FastAPI()
    register_routes(app, [], store, partners_dir=tmp_path)
    return TestClient(app)


def test_docs_serve_imnot_readme_not_the_users_project_readme(store, tmp_path):
    """A pip-installed imnot must not serve the user's own README.md from the project root."""
    (tmp_path / "README.md").write_text("MY PROJECT")
    partners_subdir = tmp_path / "partners"
    partners_subdir.mkdir()
    app = FastAPI()
    register_routes(app, [], store, partners_dir=partners_subdir)
    body = TestClient(app).get("/imnot/docs").text
    assert "MY PROJECT" not in body and "imnot" in body


def test_wheel_ships_both_readmes():
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    included = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert included == {"README.md": "imnot/_docs/README.md", "partners/README.md": "imnot/_docs/partners-README.md"}


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
    assert "imnot" in resp.text


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
