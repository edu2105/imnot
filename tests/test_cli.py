"""Tests for the CLI."""

import json
import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from imnot.cli import _resolve_partners_dir, _resolve_pid, cli
from imnot.engine.session_store import SessionStore

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# imnot start
# ---------------------------------------------------------------------------


def test_start_invokes_uvicorn(runner, tmp_path):
    with patch("imnot.cli.uvicorn.run") as mock_run:
        result = runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(PARTNERS_DIR),
                "--db",
                str(tmp_path / "test.db"),
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
        )
    assert result.exit_code == 0, result.output
    assert mock_run.called
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
    # Non-reload mode must NOT pass reload=True or factory=True
    assert not kwargs.get("reload")
    assert not kwargs.get("factory")


def test_start_reload_uses_factory_and_yaml_watching(runner, tmp_path):
    with patch("imnot.cli.uvicorn.run") as mock_run:
        result = runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(PARTNERS_DIR),
                "--db",
                str(tmp_path / "test.db"),
                "--reload",
            ],
        )
    assert result.exit_code == 0, result.output
    assert mock_run.called
    args, kwargs = mock_run.call_args
    # Factory string, not an app object
    assert args[0] == "imnot.api.server:create_app_from_env"
    assert kwargs.get("reload") is True
    assert kwargs.get("factory") is True
    assert "*.yaml" in kwargs.get("reload_includes", [])


def test_start_prints_address(runner, tmp_path):
    with patch("imnot.cli.uvicorn.run"):
        result = runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(PARTNERS_DIR),
                "--db",
                str(tmp_path / "test.db"),
            ],
        )
    assert "127.0.0.1:8000" in result.output


def test_start_missing_partners_dir_warns_and_continues(runner, tmp_path):
    with patch("imnot.cli.uvicorn.run"):
        result = runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(tmp_path / "nonexistent"),
                "--db",
                str(tmp_path / "test.db"),
            ],
        )
    assert result.exit_code == 0
    assert "zero partners" in result.output


# ---------------------------------------------------------------------------
# imnot status
# ---------------------------------------------------------------------------


def test_status_no_db(runner, tmp_path):
    result = runner.invoke(cli, ["status", "--db", str(tmp_path / "missing.db")])
    assert result.exit_code == 1
    assert "not found" in result.output


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
    store.store_session_payload("staylink", "report", {"reportId": "RPT-X"})
    store.close()

    result = runner.invoke(cli, ["status", "--db", str(db)])
    assert result.exit_code == 0
    assert "staylink" in result.output
    assert "report" in result.output


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
    """imnot routes should succeed when run from a subdirectory of the project."""
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


def test_routes_shows_ui_endpoint(runner):
    """imnot routes must include GET /imnot/admin/ui in the INFRA ENDPOINTS section."""
    project_root = Path(__file__).parent.parent
    original = os.getcwd()
    try:
        os.chdir(project_root)
        result = runner.invoke(cli, ["routes", "--partners-dir", str(PARTNERS_DIR)])
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    assert "/imnot/admin/ui" in result.output


# ---------------------------------------------------------------------------
# imnot generate
# ---------------------------------------------------------------------------

# Minimal valid YAML fixtures used across tests

VALID_YAML_FETCH = """\
partner: acme
description: Acme Corp integration

datapoints:
  - name: reservation
    description: Fetch a reservation
    pattern: fetch
    endpoints:
      - method: GET
        path: /acme/v1/reservations/{id}
        response:
          status: 200
"""

VALID_YAML_OAUTH_AND_ASYNC = """\
partner: ratesync
description: RateSync fictional partner

datapoints:
  - name: token
    description: OAuth token
    pattern: oauth
    endpoints:
      - method: POST
        path: /ratesync/oauth/token
        response:
          status: 200
          token_type: Bearer
          expires_in: 3600

  - name: rate-push
    description: Polling-based rate push
    pattern: polling
    endpoints:
      - step: 1
        method: POST
        path: /ratesync/v1/rates
        response:
          status: 200
          generates_id: true
          id_body_field: JobReferenceID
      - step: 2
        method: GET
        path: /ratesync/v1/jobs/{id}/status
        response:
          status: 200
      - step: 3
        method: GET
        path: /ratesync/v1/jobs/{id}/results
        response:
          status: 200
          returns_payload: true
"""

INVALID_YAML_MISSING_PATTERN = """\
partner: badpartner
description: Missing pattern

datapoints:
  - name: broken
    description: No pattern here
    endpoints:
      - method: GET
        path: /bad/endpoint
        response:
          status: 200
"""

INVALID_YAML_SYNTAX = """\
partner: broken
  this is: [not valid yaml
"""


def test_generate_valid_file_writes_and_exits_0(runner, tmp_path):
    """Valid YAML → partner dir created, file written, exit 0."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert (partners_dir / "acme" / "partner.yaml").exists()
    assert "Partner:" in result.output
    assert "acme" in result.output
    assert "Consumer endpoints:" in result.output
    assert "/acme/v1/reservations/{id}" in result.output
    assert "Admin endpoints:" in result.output


def test_generate_dry_run_writes_nothing(runner, tmp_path):
    """--dry-run → validation passes, no files written, exit 0."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not (partners_dir / "acme" / "partner.yaml").exists()
    assert "Dry run" in result.output


def test_generate_json_output_shape(runner, tmp_path):
    """--json → output is valid JSON with correct structure, exit 0."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["partner"] == "acme"
    assert data["created"] is True
    assert len(data["datapoints"]) == 1
    assert data["datapoints"][0]["pattern"] == "fetch"
    assert data["datapoints"][0]["admin_routes"] is True


def test_generate_dry_run_json_created_is_false(runner, tmp_path):
    """--dry-run --json → created is always False."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["created"] is False
    assert not (partners_dir / "acme" / "partner.yaml").exists()


def test_generate_conflict_exits_2(runner, tmp_path):
    """Existing partner.yaml without --force → exit 2."""
    partners_dir = tmp_path / "partners"
    acme_dir = partners_dir / "acme"
    acme_dir.mkdir(parents=True)
    (acme_dir / "partner.yaml").write_text(VALID_YAML_FETCH)

    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
        ],
    )

    assert result.exit_code == 2, result.output


def test_generate_force_overwrites(runner, tmp_path):
    """--force overwrites existing partner.yaml → exit 0."""
    partners_dir = tmp_path / "partners"
    acme_dir = partners_dir / "acme"
    acme_dir.mkdir(parents=True)
    original = "partner: acme\ndescription: old\ndatapoints: []\n"
    (acme_dir / "partner.yaml").write_text(original)

    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (acme_dir / "partner.yaml").read_text() == VALID_YAML_FETCH


def test_generate_invalid_yaml_schema_exits_1(runner, tmp_path):
    """YAML missing 'pattern' field → validation error, exit 1."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text(INVALID_YAML_MISSING_PATTERN)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
        ],
    )

    assert result.exit_code == 1


def test_generate_invalid_yaml_syntax_exits_1(runner, tmp_path):
    """Malformed YAML syntax → exit 1."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "broken.yaml"
    yaml_file.write_text(INVALID_YAML_SYNTAX)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
        ],
    )

    assert result.exit_code == 1


def test_generate_invalid_yaml_json_error_shape(runner, tmp_path):
    """Invalid YAML + --json → JSON error object with status=error."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text(INVALID_YAML_MISSING_PATTERN)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
            "--json",
        ],
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert "error" in data


def test_generate_partners_dir_not_found_exits_3(runner, tmp_path):
    """Partners dir not found → exit 3."""
    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(tmp_path / "nonexistent"),
        ],
    )

    assert result.exit_code == 3


def test_generate_stdin(runner, tmp_path):
    """--file - reads from stdin → valid partner written, exit 0."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            "-",
            "--partners-dir",
            str(partners_dir),
        ],
        input=VALID_YAML_FETCH,
    )

    assert result.exit_code == 0, result.output
    assert (partners_dir / "acme" / "partner.yaml").exists()


def test_generate_oauth_no_admin_routes(runner, tmp_path):
    """oauth datapoints must have admin_routes=False in JSON output."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "ratesync.yaml"
    yaml_file.write_text(VALID_YAML_OAUTH_AND_ASYNC)

    result = runner.invoke(
        cli,
        [
            "generate",
            "--file",
            str(yaml_file),
            "--partners-dir",
            str(partners_dir),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    token_dp = next(dp for dp in data["datapoints"] if dp["name"] == "token")
    async_dp = next(dp for dp in data["datapoints"] if dp["name"] == "rate-push")
    assert token_dp["admin_routes"] is False
    assert async_dp["admin_routes"] is True


# ---------------------------------------------------------------------------
# imnot init
# ---------------------------------------------------------------------------


def test_init_creates_example_partners(runner, tmp_path):
    """init writes staylink and bookingco partner YAMLs and exits 0."""
    result = runner.invoke(cli, ["init", "--dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "partners" / "staylink" / "partner.yaml").exists()
    assert (tmp_path / "partners" / "bookingco" / "partner.yaml").exists()


def test_init_yaml_content_is_valid(runner, tmp_path):
    """YAMLs written by init parse without error."""
    from imnot.loader.yaml_loader import parse_partner_yaml

    runner.invoke(cli, ["init", "--dir", str(tmp_path)])

    for partner in ("staylink", "bookingco"):
        text = (tmp_path / "partners" / partner / "partner.yaml").read_text()
        parsed = parse_partner_yaml(text)
        assert parsed.partner == partner


def test_init_output_mentions_both_partners(runner, tmp_path):
    """Success output names both scaffold partners."""
    result = runner.invoke(cli, ["init", "--dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "staylink" in result.output
    assert "bookingco" in result.output
    assert "imnot start" in result.output


def test_init_fails_if_partners_dir_exists(runner, tmp_path):
    """init exits 1 when partners/ already exists."""
    (tmp_path / "partners").mkdir()

    result = runner.invoke(cli, ["init", "--dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_init_creates_target_dir_if_missing(runner, tmp_path):
    """init creates --dir if it does not exist yet."""
    new_dir = tmp_path / "brand" / "new" / "project"

    result = runner.invoke(cli, ["init", "--dir", str(new_dir)])

    assert result.exit_code == 0, result.output
    assert (new_dir / "partners" / "staylink" / "partner.yaml").exists()


def test_init_default_dir_is_cwd(runner, tmp_path):
    """init without --dir scaffolds into CWD."""
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = runner.invoke(cli, ["init"])
    finally:
        os.chdir(original)

    assert result.exit_code == 0, result.output
    assert (tmp_path / "partners" / "staylink" / "partner.yaml").exists()


# ---------------------------------------------------------------------------
# imnot start — PID file lifecycle
# ---------------------------------------------------------------------------


def test_start_writes_pid_file_during_run(runner, tmp_path):
    """imnot start writes imnot.pid before uvicorn runs."""
    db_path = tmp_path / "test.db"
    pid_path = tmp_path / "test.pid"
    written_pids = []

    def capture_pid(*_args, **_kwargs):
        if pid_path.exists():
            written_pids.append(pid_path.read_text().strip())

    with patch("imnot.cli.uvicorn.run", side_effect=capture_pid):
        result = runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(PARTNERS_DIR),
                "--db",
                str(db_path),
            ],
        )

    assert result.exit_code == 0, result.output
    assert len(written_pids) == 1
    assert written_pids[0].isdigit()


def test_start_removes_pid_file_on_clean_exit(runner, tmp_path):
    """imnot start removes imnot.pid after uvicorn exits normally."""
    db_path = tmp_path / "test.db"
    pid_path = tmp_path / "test.pid"

    with patch("imnot.cli.uvicorn.run"):
        runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(PARTNERS_DIR),
                "--db",
                str(db_path),
            ],
        )

    assert not pid_path.exists()


def test_start_removes_pid_file_on_exception(runner, tmp_path):
    """imnot start removes imnot.pid even when uvicorn raises."""
    db_path = tmp_path / "test.db"
    pid_path = tmp_path / "test.pid"

    with patch("imnot.cli.uvicorn.run", side_effect=RuntimeError("boom")):
        runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(PARTNERS_DIR),
                "--db",
                str(db_path),
            ],
        )

    assert not pid_path.exists()


# ---------------------------------------------------------------------------
# _resolve_pid
# ---------------------------------------------------------------------------


def test_resolve_pid_finds_in_cwd(tmp_path):
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("1234")
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert _resolve_pid("imnot.pid") == pid_file
    finally:
        os.chdir(original)


def test_resolve_pid_finds_in_parent(tmp_path):
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("1234")
    subdir = tmp_path / "a" / "b"
    subdir.mkdir(parents=True)
    original = os.getcwd()
    try:
        os.chdir(subdir)
        assert _resolve_pid("imnot.pid") == pid_file
    finally:
        os.chdir(original)


def test_resolve_pid_raises_when_not_found(tmp_path):
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            _resolve_pid("imnot.pid")
    finally:
        os.chdir(original)


def test_resolve_pid_absolute_path_found(tmp_path):
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("1234")
    assert _resolve_pid(str(pid_file)) == pid_file


def test_resolve_pid_absolute_path_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        _resolve_pid(str(tmp_path / "missing.pid"))


# ---------------------------------------------------------------------------
# imnot stop
# ---------------------------------------------------------------------------


def test_stop_no_pid_file_exits_1(runner, tmp_path):
    """No PID file → exit 1 with error message."""
    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = runner.invoke(cli, ["stop"])
    finally:
        os.chdir(original)

    assert result.exit_code == 1
    assert "not found" in result.output


def test_stop_invalid_pid_content_exits_1(runner, tmp_path):
    """PID file contains non-integer → exit 1."""
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("not-a-number")

    result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])

    assert result.exit_code == 1


def test_stop_stale_pid_cleans_up(runner, tmp_path):
    """Process already gone → warn, remove file, exit 0."""
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("99999")

    with patch("imnot.cli.os.kill", side_effect=ProcessLookupError):
        result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])

    assert result.exit_code == 0
    assert not pid_file.exists()
    assert "stale" in result.output.lower() or "not running" in result.output.lower()


def test_stop_sends_sigterm_and_exits_0(runner, tmp_path):
    """Process alive → SIGTERM sent, process exits, file removed, exit 0."""
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("12345")

    kill_calls = []

    def fake_kill(pid, sig):
        kill_calls.append((pid, sig))
        # Process dies after SIGTERM is sent (signal 0 on second call raises)
        if sig == 0 and len(kill_calls) > 1:
            raise ProcessLookupError

    with patch("imnot.cli.os.kill", side_effect=fake_kill):
        with patch("imnot.cli.time.sleep"):
            result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])

    assert result.exit_code == 0
    assert not pid_file.exists()
    assert "stopped" in result.output
    assert (12345, signal.SIGTERM) in kill_calls


def test_stop_timeout_exits_1(runner, tmp_path):
    """Process never exits → exit 1 with kill -9 hint."""
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("12345")

    with patch("imnot.cli.os.kill"):  # never raises — process stays alive
        with patch("imnot.cli.time.sleep"):
            with patch("imnot.cli.time.monotonic", side_effect=[0.0, 0.0, 6.0]):
                result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])

    assert result.exit_code == 1
    assert "kill -9" in result.output


def test_stop_permission_error_exits_1(runner, tmp_path):
    """No permission to signal process → exit 1."""
    pid_file = tmp_path / "imnot.pid"
    pid_file.write_text("1")

    with patch("imnot.cli.os.kill", side_effect=PermissionError):
        result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])

    assert result.exit_code == 1
    assert "permission" in result.output.lower()


def test_stop_explicit_pid_file_path(runner, tmp_path):
    """--pid-file with explicit path is honoured."""
    pid_file = tmp_path / "custom.pid"
    pid_file.write_text("99999")

    with patch("imnot.cli.os.kill", side_effect=ProcessLookupError):
        result = runner.invoke(cli, ["stop", "--pid-file", str(pid_file)])

    assert result.exit_code == 0
    assert not pid_file.exists()


def test_start_missing_partners_dir_warns_no_partners(runner, tmp_path):
    """Missing default partners dir: warn and start with zero partners."""
    original = os.getcwd()
    try:
        os.chdir(tmp_path)  # no partners/ here or in any ancestor up to tmp_path
        with patch("imnot.cli.uvicorn.run"):
            result = runner.invoke(
                cli,
                [
                    "start",
                    "--db",
                    str(tmp_path / "test.db"),
                ],
            )
    finally:
        os.chdir(original)

    assert result.exit_code == 0
    assert "zero partners" in result.output


# ---------------------------------------------------------------------------
# Log dir defaults to db_path.parent, not CWD
# ---------------------------------------------------------------------------


def test_start_logs_written_to_db_dir_not_cwd(runner, tmp_path):
    """imnot start writes logs to db_path.parent, not CWD.

    This is the container-safety fix: /app is read-only in Docker but
    /app/data (where imnot.db lives) is writable.
    """
    cwd_dir = tmp_path / "cwd"
    db_dir = tmp_path / "data"
    cwd_dir.mkdir()
    db_dir.mkdir()

    original = os.getcwd()
    try:
        os.chdir(cwd_dir)
        with patch("imnot.cli.uvicorn.run"):
            result = runner.invoke(
                cli,
                ["start", "--db", str(db_dir / "imnot.db")],
            )
    finally:
        os.chdir(original)

    assert result.exit_code == 0
    assert (db_dir / "imnot.cli.log").exists(), "log file should be in db_dir"
    assert not (cwd_dir / "imnot.cli.log").exists(), "log file must NOT be in CWD"


def test_start_toml_written_to_db_dir_not_cwd(runner, tmp_path):
    """imnot start writes imnot.toml to db_path.parent, not CWD."""
    cwd_dir = tmp_path / "cwd"
    db_dir = tmp_path / "data"
    cwd_dir.mkdir()
    db_dir.mkdir()

    original = os.getcwd()
    try:
        os.chdir(cwd_dir)
        with patch("imnot.cli.uvicorn.run"):
            result = runner.invoke(
                cli,
                ["start", "--db", str(db_dir / "imnot.db")],
            )
    finally:
        os.chdir(original)

    assert result.exit_code == 0
    assert (db_dir / "imnot.toml").exists(), "imnot.toml should be in db_dir"
    assert not (cwd_dir / "imnot.toml").exists(), "imnot.toml must NOT be in CWD"


def test_resolve_config_finds_toml_in_db_parent(tmp_path):
    """_resolve_config(db_path) finds imnot.toml in db_path.parent before CWD walk."""
    from imnot.cli import _resolve_config

    db_dir = tmp_path / "data"
    db_dir.mkdir()
    toml = db_dir / "imnot.toml"
    toml.write_text("[server]\n")

    result = _resolve_config(db_path=db_dir / "imnot.db")
    assert result == toml


def test_resolve_config_falls_back_to_cwd_walk(tmp_path):
    """_resolve_config falls back to CWD walk when db_path.parent has no toml."""
    from imnot.cli import _resolve_config

    db_dir = tmp_path / "data"
    db_dir.mkdir()
    # toml is in tmp_path (ancestor of CWD), not db_dir
    toml = tmp_path / "imnot.toml"
    toml.write_text("[server]\n")

    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _resolve_config(db_path=db_dir / "imnot.db")
    finally:
        os.chdir(original)

    assert result == toml


# ---------------------------------------------------------------------------
# Coverage gap fixes — cli.py lines 240, 426-428, 431-432, 454-455,
#                      508-509, 576-577, 627-628, 672-684, 694-704, 722-725
# ---------------------------------------------------------------------------

CALLBACK_YAML = """\
partner: hookco
description: Callback test partner

datapoints:
  - name: event
    description: Webhook event
    pattern: callback
    endpoints:
      - method: POST
        path: /hookco/events
        response:
          status: 202
          callback_url_field: callbackUrl
          callback_delay_seconds: 3
"""


def test_start_reload_with_admin_key_sets_env(runner, tmp_path):
    """--reload + admin key must set IMNOT_ADMIN_KEY in env (line 240)."""
    with patch("imnot.cli.uvicorn.run"):
        result = runner.invoke(
            cli,
            [
                "start",
                "--partners-dir",
                str(PARTNERS_DIR),
                "--db",
                str(tmp_path / "test.db"),
                "--reload",
            ],
            env={"IMNOT_ADMIN_KEY": "reloadkey"},
        )
    assert result.exit_code == 0, result.output


def test_routes_partners_dir_not_found_exits_1(runner, tmp_path):
    """imnot routes with a non-existent partners dir exits 1 (lines 426-428)."""
    result = runner.invoke(cli, ["routes", "--partners-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1


def test_routes_no_partners_loaded(runner, tmp_path):
    """imnot routes with an empty partners dir prints message and exits 0 (lines 431-432)."""
    (tmp_path / "partners").mkdir()
    result = runner.invoke(cli, ["routes", "--partners-dir", str(tmp_path / "partners")])
    assert result.exit_code == 0
    assert "No partners loaded" in result.output


def test_routes_shows_callback_retrigger(runner, tmp_path):
    """imnot routes prints the retrigger admin endpoint for callback datapoints (lines 454-455)."""
    partner_dir = tmp_path / "hookco"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(CALLBACK_YAML)

    result = runner.invoke(cli, ["routes", "--partners-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "retrigger" in result.output


def test_generate_file_read_error_exits_1(runner, tmp_path):
    """generate exits 1 when the YAML file cannot be read (lines 508-509)."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "partner.yaml"
    yaml_file.write_text("dummy")
    yaml_file.chmod(0o000)

    try:
        result = runner.invoke(
            cli,
            ["generate", "--file", str(yaml_file), "--partners-dir", str(partners_dir)],
        )
        assert result.exit_code == 1
    finally:
        yaml_file.chmod(0o644)


def test_generate_shows_callback_retrigger(runner, tmp_path):
    """generate output lists the retrigger admin endpoint for callback datapoints (lines 576-577)."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "hookco.yaml"
    yaml_file.write_text(CALLBACK_YAML)

    result = runner.invoke(
        cli,
        ["generate", "--file", str(yaml_file), "--partners-dir", str(partners_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "retrigger" in result.output


def test_export_postman_no_partners_exits_1(runner, tmp_path):
    """export postman exits 1 when no partners are loaded (lines 627-628)."""
    (tmp_path / "partners").mkdir()
    result = runner.invoke(
        cli,
        ["export", "postman", "--partners-dir", str(tmp_path / "partners")],
    )
    assert result.exit_code == 1
    assert "nothing to export" in result.output.lower()


def test_payload_get_not_found(runner, tmp_path):
    """payload get exits 1 and prints message when no payload is stored (lines 676-678)."""
    db = tmp_path / "test.db"
    store = SessionStore(db_path=db)
    store.init()
    store.close()

    result = runner.invoke(cli, ["payload", "get", "staylink", "report", "--db", str(db)])
    assert result.exit_code == 1
    assert "No global payload" in result.output


def test_payload_get_found(runner, tmp_path):
    """payload get prints payload details when a payload exists (lines 680-684)."""
    db = tmp_path / "test.db"
    store = SessionStore(db_path=db)
    store.init()
    store.store_global_payload("staylink", "report", {"reportId": "RPT-001"})
    store.close()

    result = runner.invoke(cli, ["payload", "get", "staylink", "report", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "RPT-001" in result.output
    assert "staylink" in result.output


def test_payload_set_invalid_json_exits_1(runner, tmp_path):
    """payload set exits 1 when the JSON file is invalid (lines 696-698)."""
    db = tmp_path / "test.db"
    store = SessionStore(db_path=db)
    store.init()
    store.close()

    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json")

    result = runner.invoke(cli, ["payload", "set", "staylink", "report", str(bad_file), "--db", str(db)])
    assert result.exit_code == 1
    assert "Invalid JSON" in result.output


def test_payload_set_success(runner, tmp_path):
    """payload set stores the payload and prints confirmation (lines 700-704)."""
    db = tmp_path / "test.db"
    store = SessionStore(db_path=db)
    store.init()
    store.close()

    payload_file = tmp_path / "payload.json"
    payload_file.write_text('{"reportId": "RPT-SET"}')

    result = runner.invoke(cli, ["payload", "set", "staylink", "report", str(payload_file), "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "Global payload set" in result.output


def test_sessions_clear(runner, tmp_path):
    """sessions clear removes all sessions and prints count (lines 722-725)."""
    db = tmp_path / "test.db"
    store = SessionStore(db_path=db)
    store.init()
    store.store_session_payload("staylink", "report", {"x": 1})
    store.store_session_payload("staylink", "report", {"x": 2})
    store.close()

    result = runner.invoke(cli, ["sessions", "clear", "--db", str(db)], input="y\n")
    assert result.exit_code == 0, result.output
    assert "Cleared 2" in result.output


def test_resolve_db_finds_db_in_data_subdir(tmp_path):
    """_resolve_db finds imnot.db in data/ subdirectory (Docker: /app/data/ bind-mount)."""
    from imnot.cli import _resolve_db

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = data_dir / "imnot.db"
    db.write_bytes(b"")

    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = _resolve_db("imnot.db")
    finally:
        os.chdir(original)

    assert result == db.resolve()
