"""Tests for the CLI."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from mirage.cli import cli
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
