"""Tests for the CLI."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from imnot.cli import cli, _resolve_partners_dir
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
    with patch("imnot.cli.uvicorn.run") as mock_run:
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
    assert args[0] == "imnot.api.server:create_app_from_env"
    assert kwargs.get("reload") is True
    assert kwargs.get("factory") is True
    assert "*.yaml" in kwargs.get("reload_includes", [])


def test_start_prints_address(runner, tmp_path):
    with patch("imnot.cli.uvicorn.run"):
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
# imnot status
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
    description: Async rate push
    pattern: async
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

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
    ])

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

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
        "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    assert not (partners_dir / "acme" / "partner.yaml").exists()
    assert "Dry run" in result.output


def test_generate_json_output_shape(runner, tmp_path):
    """--json → output is valid JSON with correct structure, exit 0."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
        "--json",
    ])

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

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
        "--dry-run", "--json",
    ])

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

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
    ])

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

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
        "--force",
    ])

    assert result.exit_code == 0, result.output
    assert (acme_dir / "partner.yaml").read_text() == VALID_YAML_FETCH


def test_generate_invalid_yaml_schema_exits_1(runner, tmp_path):
    """YAML missing 'pattern' field → validation error, exit 1."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text(INVALID_YAML_MISSING_PATTERN)

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
    ])

    assert result.exit_code == 1


def test_generate_invalid_yaml_syntax_exits_1(runner, tmp_path):
    """Malformed YAML syntax → exit 1."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "broken.yaml"
    yaml_file.write_text(INVALID_YAML_SYNTAX)

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
    ])

    assert result.exit_code == 1


def test_generate_invalid_yaml_json_error_shape(runner, tmp_path):
    """Invalid YAML + --json → JSON error object with status=error."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "bad.yaml"
    yaml_file.write_text(INVALID_YAML_MISSING_PATTERN)

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
        "--json",
    ])

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["status"] == "error"
    assert "error" in data


def test_generate_partners_dir_not_found_exits_3(runner, tmp_path):
    """Partners dir not found → exit 3."""
    yaml_file = tmp_path / "acme.yaml"
    yaml_file.write_text(VALID_YAML_FETCH)

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(tmp_path / "nonexistent"),
    ])

    assert result.exit_code == 3


def test_generate_stdin(runner, tmp_path):
    """--file - reads from stdin → valid partner written, exit 0."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    result = runner.invoke(cli, [
        "generate",
        "--file", "-",
        "--partners-dir", str(partners_dir),
    ], input=VALID_YAML_FETCH)

    assert result.exit_code == 0, result.output
    assert (partners_dir / "acme" / "partner.yaml").exists()


def test_generate_oauth_no_admin_routes(runner, tmp_path):
    """oauth datapoints must have admin_routes=False in JSON output."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    yaml_file = tmp_path / "ratesync.yaml"
    yaml_file.write_text(VALID_YAML_OAUTH_AND_ASYNC)

    result = runner.invoke(cli, [
        "generate",
        "--file", str(yaml_file),
        "--partners-dir", str(partners_dir),
        "--json",
    ])

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


def test_start_missing_partners_dir_suggests_init(runner, tmp_path):
    """Default-path failure message should mention `imnot init`."""
    original = os.getcwd()
    try:
        os.chdir(tmp_path)  # no partners/ here or in any ancestor up to tmp_path
        result = runner.invoke(cli, [
            "start",
            "--db", str(tmp_path / "test.db"),
        ])
    finally:
        os.chdir(original)

    assert result.exit_code != 0
    assert "imnot init" in result.output
