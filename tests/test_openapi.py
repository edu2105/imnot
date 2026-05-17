"""Tests for the OpenAPI schema exposed by the app."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
def schema(tmp_path):
    app = create_app(partners_dir=None, db_path=tmp_path / "test.db")
    with TestClient(app) as client:
        r = client.get("/openapi.json")
        assert r.status_code == 200
        return r.json()


# ---------------------------------------------------------------------------
# Schema metadata
# ---------------------------------------------------------------------------


def test_schema_title(schema):
    assert schema["info"]["title"] == "imnot"


def test_schema_version_present(schema):
    assert "version" in schema["info"]


def test_schema_openapi_version(schema):
    assert schema["openapi"].startswith("3.")


# ---------------------------------------------------------------------------
# Expected admin paths are present
# ---------------------------------------------------------------------------


EXPECTED_PATHS = [
    ("/healthz", "get"),
    ("/imnot/docs", "get"),
    ("/imnot/docs/partners", "get"),
    ("/imnot/admin/sessions", "get"),
    ("/imnot/admin/sessions/{session_id}", "delete"),
    ("/imnot/admin/partners", "get"),
    ("/imnot/admin/partners", "post"),
    ("/imnot/admin/partners/{partner_name}", "delete"),
    ("/imnot/admin/reload", "post"),
    ("/imnot/admin/postman", "get"),
]


@pytest.mark.parametrize("path,method", EXPECTED_PATHS)
def test_admin_path_present(schema, path, method):
    assert path in schema["paths"], f"missing path: {path}"
    assert method in schema["paths"][path], f"missing method {method} on {path}"


# ---------------------------------------------------------------------------
# No partner routes leak in when partners_dir=None
# ---------------------------------------------------------------------------


def test_no_partner_routes_when_no_partners_dir(schema):
    partner_paths = [p for p in schema["paths"] if not p.startswith("/imnot") and p != "/healthz"]
    assert partner_paths == [], f"unexpected partner routes: {partner_paths}"


# ---------------------------------------------------------------------------
# export_openapi.py script writes a valid file
# ---------------------------------------------------------------------------


def test_export_script_writes_valid_json(tmp_path, monkeypatch):
    out = tmp_path / "openapi.json"
    script = REPO_ROOT / "scripts" / "export_openapi.py"

    # Patch the output path by running the script and redirecting output
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    # Script writes to repo root, so check there
    generated = REPO_ROOT / "openapi.json"
    assert generated.exists()
    data = json.loads(generated.read_text())
    assert data["info"]["title"] == "imnot"
    assert "paths" in data


def test_export_script_exits_zero(tmp_path):
    script = REPO_ROOT / "scripts" / "export_openapi.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
