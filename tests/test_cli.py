"""Tests for the CLI."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from mirage.cli import cli, _resolve_partners_dir
from mirage.engine.session_store import SessionStore

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# mirage start
# ---------------------------------------------------------------------------


def test_start_invokes_uvicorn(runner, tmp_path):
    with patch("mirage.cli.uvicorn.run") as mock_run:
        result = runner.invoke(cli, [
            "start",
            "--partners-dir", str(PARTNERS_DIR),
            "--db", str(tmp_path / "test.db"),
            "--host", "127.0.0.1",
            "--port", "8000",
        ])
    assert result.exit_code == 0, result.output
    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    # Non-reload mode must NOT pass reload=True or factory=True
    assert not kwargs.get("reload")
    assert not kwargs.get("factory")


def test_start_reload_uses_factory_and_yaml_watching(runner, tmp_path):
    with patch("mirage.cli.uvicorn.run") as mock_run:
        result = runner.invoke(cli, [
            "start",
            "--partners-dir", str(PARTNERS_DIR),
            "--db", str(tmp_path / "test.db"),
            "--reload",
        ])
    assert result.exit_code == 0, result.output
    assert mock_run.called
    args, kwargs = mock_run.call_args
    # Factory string, not an app object
    assert args[0] == "mirage.api.server:create_app_from_env"
    assert kwargs.get("reload") is True
    assert kwargs.get("factory") is True
    assert "*.yaml" in kwargs.get("reload_includes", [])


def test_start_prints_address(runner, tmp_path):
    with patch("mirage.cli.uvicorn.run"):
        result = runner.invoke(cli, [
            "start",
            "--partners-dir", str(PARTNERS_DIR),
            "--db", str(tmp_path / "test.db"),
        ])
    assert "127.0.0.1:8000" in result.output


def test_start_missing_partners_dir_exits(runner, tmp_path):
    result = runner.invoke(cli, [
        "start",
        "--partners-dir", str(tmp_path / "nonexistent"),
        "--db", str(tmp_path / "test.db"),
    ])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# mirage status
# ---------------------------------------------------------------------------


def test_status_no_db(runner, tmp_path):
    result = runner.invoke(cli, ["status", "--db", str(tmp_path / "missing.db")])
    assert result.exit_code == 1
    assert "No database found" in result.output


def test_status_empty(runner, tmp_path):
    db = tmp_path / "test.db"
    store = SessionStore(db_path=db)
    store.init()
    store.close()

    result = runner.invoke(cli, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "No active sessions" in result.output


def test_status_shows_sessions(runner, tmp_path):
    db = tmp_path / "test.db"
    store = SessionStore(db_path=db)
    store.init()
    store.store_session_payload("staylink", "reservation", {"reservationId": "X"})
    store.close()

    result = runner.invoke(cli, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "staylink" in result.output
    assert "reservation" in result.output


# ---------------------------------------------------------------------------
# Partners dir auto-discovery
# ---------------------------------------------------------------------------


def test_resolve_partners_dir_finds_in_parent(tmp_path):
    """Walking up from a subdirectory should locate partners/."""
    partners = tmp_path / "partners"
    partners.mkdir()
    subdir = tmp_path / "some" / "nested" / "dir"
    subdir.mkdir(parents=True)

    original = os.getcwd()
    try:
        os.chdir(subdir)
        resolved = _resolve_partners_dir("partners")
        assert resolved == partners
    finally:
        os.chdir(original)


def test_resolve_partners_dir_uses_cwd_first(tmp_path):
    """If partners/ exists in CWD it should be preferred over a parent."""
    outer = tmp_path / "partners"
    outer.mkdir()
    inner_dir = tmp_path / "child"
    inner_dir.mkdir()
    inner_partners = inner_dir / "partners"
    inner_partners.mkdir()

    original = os.getcwd()
    try:
        os.chdir(inner_dir)
        resolved = _resolve_partners_dir("partners")
        assert resolved == inner_partners
    finally:
        os.chdir(original)


def test_resolve_partners_dir_raises_when_not_found(tmp_path):
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            _resolve_partners_dir("partners")
    finally:
        os.chdir(original)


def test_routes_works_from_subdirectory(runner):
    """mirage routes should succeed when run from a subdirectory of the project."""
    project_root = Path(__file__).parent.parent
    subdir = project_root / "partners"  # run from inside partners/

    original = os.getcwd()
    try:
        os.chdir(subdir)
        result = runner.invoke(cli, ["routes"])
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    assert "staylink" in result.output
