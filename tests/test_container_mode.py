"""Container mode: `imnot start --stateless` / `--strict`, options from environment variables,
and the admin API on a partners directory that cannot be written.

The defaults (files next to the database, lenient start) are pinned here too, because none of this
may change what `imnot start` does when the new options are not used.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from imnot.api.server import create_app, create_app_from_env
from imnot.cli import cli
from imnot.config import LoggingConfig
from imnot.logging_setup import configure_logging

ROOT = Path(__file__).parent.parent

_PARTNER = """\
partner: {name}
datapoints:
  - name: ping
    pattern: static
    endpoints:
      - method: GET
        path: /{name}/ping
        response:
          status: 200
          body: {{ok: true}}
  - name: charges
    pattern: fetch
    endpoints:
      - method: GET
        path: /{name}/charges
        response:
          status: 200
"""


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A directory with one valid partner (and a seeded payload) that is also the CWD."""
    partner = tmp_path / "partners" / "staylink"
    (partner / "payloads").mkdir(parents=True)
    (partner / "partner.yaml").write_text(_PARTNER.format(name="staylink"))
    (partner / "payloads" / "charges.json").write_text('{"total": 42}')
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _start(runner, *args, env=None):
    """Run `imnot start` with uvicorn patched out. Returns (result, uvicorn.run mock)."""
    with patch("imnot.cli.uvicorn.run") as mock_run:
        result = runner.invoke(cli, ["start", *args], env=env)
    return result, mock_run


# ---------------------------------------------------------------------------
# --stateless
# ---------------------------------------------------------------------------


def test_stateless_writes_no_files(runner, project):
    before = _files(project)
    result, mock_run = _start(runner, "--stateless")
    assert result.exit_code == 0, result.output
    assert mock_run.called
    assert _files(project) == before  # no imnot.db, imnot.toml, imnot.pid or logs/


def test_stateless_starts_from_a_read_only_directory(runner, project):
    if os.getuid() == 0:
        pytest.skip("root ignores directory permissions")
    project.chmod(0o555)
    try:
        result, mock_run = _start(runner, "--stateless")
    finally:
        project.chmod(0o755)
    assert result.exit_code == 0, result.output
    assert mock_run.called


def test_stateless_serves_seeded_payloads_and_keeps_state_in_memory(runner, project):
    result, mock_run = _start(runner, "--stateless")
    assert result.exit_code == 0, result.output
    app = mock_run.call_args.args[0]
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/staylink/charges").json() == {"total": 42}
        # Uploads, sessions and the journal work as usual, in memory.
        assert c.post("/imnot/admin/staylink/charges/payload", json={"total": 7}).status_code == 200
        assert c.get("/staylink/charges").json() == {"total": 7}
        session = c.post("/imnot/admin/staylink/charges/payload/session", json={"total": 1}).json()["session_id"]
        assert c.get("/staylink/charges", headers={"X-Imnot-Session": session}).json() == {"total": 1}
        assert len(c.get("/imnot/admin/requests").json()) >= 2
    assert not (project / ":memory:").exists()


def test_stateless_load_test_store_works_in_memory(runner, project):
    """The load-test store opens its own connection: with `:memory:` that is a second, private database,
    which is fine because it only holds its own tables."""
    _, mock_run = _start(runner, "--stateless")
    with TestClient(mock_run.call_args.args[0]) as c:
        created = c.post("/imnot/admin/stress/templates", json={"name": "t", "config": {"target_url": "http://x"}})
        assert created.status_code == 201, created.text
        assert [t["name"] for t in c.get("/imnot/admin/stress/templates").json()] == ["t"]
        assert c.get("/imnot/admin/stress/runs").json() == []


def test_stateless_ignores_db_option(runner, project, tmp_path):
    result, _ = _start(runner, "--stateless", "--db", str(tmp_path / "data" / "imnot.db"))
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "data").exists()


def test_stateless_logs_go_to_stdout_only(runner, project):
    result, _ = _start(runner, "--stateless")
    assert "Starting imnot host=127.0.0.1" in result.stdout  # the imnot.cli log line, not only the banner
    for name in ("imnot.cli", "imnot.http", "imnot"):
        handlers = logging.getLogger(name).handlers
        assert handlers and not any(isinstance(h, logging.FileHandler) for h in handlers)


def test_stateless_reads_an_existing_imnot_toml_but_never_creates_one(runner, project):
    (project / "imnot.toml").write_text("[ui]\nenabled = false\n")
    _, mock_run = _start(runner, "--stateless")
    with TestClient(mock_run.call_args.args[0]) as c:
        assert c.get("/imnot/admin/ui").status_code == 404


def test_stateless_cannot_be_combined_with_reload(runner, project):
    result, mock_run = _start(runner, "--stateless", "--reload")
    assert result.exit_code == 2
    assert "--stateless cannot be combined with --reload" in result.output
    assert not mock_run.called


def test_stateless_from_env_var(runner, project):
    before = _files(project)
    result, _ = _start(runner, env={"IMNOT_STATELESS": "1"})
    assert result.exit_code == 0, result.output
    assert _files(project) == before


def test_default_start_still_writes_db_dir_files(runner, project):
    """Without --stateless nothing changes: imnot.toml and logs/ next to the database, pid during the run."""
    seen: dict[str, bool] = {}

    def running(*_a, **_k):
        seen["pid"] = (project / "imnot.pid").exists()

    with patch("imnot.cli.uvicorn.run", side_effect=running):
        result = runner.invoke(cli, ["start"])
    assert result.exit_code == 0, result.output
    assert seen["pid"] and not (project / "imnot.pid").exists()
    assert (project / "imnot.toml").exists()
    assert (project / "logs" / "imnot.cli.log").exists()


def test_start_explains_an_unwritable_data_dir(runner, project, tmp_path):
    if os.getuid() == 0:
        pytest.skip("root ignores directory permissions")
    data = tmp_path / "data"
    data.mkdir()
    data.chmod(0o555)
    try:
        result, mock_run = _start(runner, "--db", str(data / "imnot.db"))
    finally:
        data.chmod(0o755)
    assert result.exit_code == 1
    assert "Cannot write logs" in result.output and "--stateless" in result.output
    assert not mock_run.called


# ---------------------------------------------------------------------------
# Logging without files
# ---------------------------------------------------------------------------


def test_configure_logging_without_log_dir_uses_stdout(capsys):
    configure_logging(LoggingConfig(), None)
    logging.getLogger("imnot.cli").info("cli line")
    logging.getLogger("imnot.http").info("http line")
    logging.getLogger("imnot.loader.yaml_loader").info("module line")
    out = capsys.readouterr()
    assert out.err == ""
    for line in ("cli line", "http line", "module line"):
        assert out.out.count(line) == 1  # each message once, none duplicated


# ---------------------------------------------------------------------------
# --strict
# ---------------------------------------------------------------------------


def _add_broken_partner(project: Path) -> None:
    broken = project / "partners" / "broken"
    broken.mkdir()
    (broken / "partner.yaml").write_text("partner: broken\ndatapoints: nope\n")


def test_strict_starts_when_every_partner_is_valid(runner, project):
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 0, result.output
    assert mock_run.called


def test_strict_exits_1_on_a_broken_partner(runner, project):
    _add_broken_partner(project)
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 1
    assert "FAIL" in result.output and "broken/partner.yaml" in result.output
    assert "--strict: refusing to start" in result.output
    assert not mock_run.called


def test_without_strict_a_broken_partner_is_skipped(runner, project):
    _add_broken_partner(project)
    result, mock_run = _start(runner, "--stateless")
    assert result.exit_code == 0, result.output
    assert "Skipped:   broken" in result.output
    assert mock_run.called


def test_strict_exits_1_on_unknown_key_and_bad_payload_file(runner, project):
    yaml_file = project / "partners" / "staylink" / "partner.yaml"
    yaml_file.write_text(yaml_file.read_text().replace("status: 200\n          body", "statuss: 200\n          body"))
    result, _ = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 1
    assert "statuss" in result.output

    yaml_file.write_text(_PARTNER.format(name="staylink"))
    (project / "partners" / "staylink" / "payloads" / "nope.json").write_text("{}")
    result, _ = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 1
    assert "nope.json" in result.output


def test_strict_exits_1_without_partners(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result, mock_run = _start(runner, "--strict", "--stateless")  # no partners directory
    assert result.exit_code == 1
    assert "--strict: no partners directory found" in result.output

    (tmp_path / "partners" / "group" / "staylink").mkdir(parents=True)  # one level too deep
    (tmp_path / "partners" / "group" / "staylink" / "partner.yaml").write_text(_PARTNER.format(name="staylink"))
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 1
    assert "No partner.yaml files found" in result.output
    assert not mock_run.called


def test_strict_from_env_var(runner, project):
    _add_broken_partner(project)
    result, _ = _start(runner, "--stateless", env={"IMNOT_STRICT": "true"})
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# Options from environment variables
# ---------------------------------------------------------------------------


def test_start_options_from_env_vars(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    partner = tmp_path / "contracts" / "staylink"
    partner.mkdir(parents=True)
    (partner / "partner.yaml").write_text(_PARTNER.format(name="staylink"))
    env = {
        "IMNOT_PARTNERS_DIR": str(tmp_path / "contracts"),
        "IMNOT_DB_PATH": str(tmp_path / "data" / "x.db"),
        "IMNOT_BIND_HOST": "0.0.0.0",
        "IMNOT_BIND_PORT": "9123",
        "IMNOT_BASE_URL": "https://mock.example.test",
        "IMNOT_ADMIN_KEY": "k",
    }
    (tmp_path / "data").mkdir()
    result, mock_run = _start(runner, env=env)
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs == {"host": "0.0.0.0", "port": 9123}
    app = mock_run.call_args.args[0]
    assert app.state.base_url == "https://mock.example.test"
    assert [p.partner for p in app.state.partners] == ["staylink"]
    assert (tmp_path / "data" / "imnot.toml").exists()  # files follow IMNOT_DB_PATH


def test_flags_win_over_env_vars_and_env_vars_over_toml(runner, project):
    (project / "imnot.toml").write_text('[server]\nport = 7001\nhost = "127.0.0.2"\nbase_url = "http://toml"\n')
    result, mock_run = _start(runner, "--stateless", "--port", "7003", env={"IMNOT_BIND_PORT": "7002"})
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs == {"host": "127.0.0.2", "port": 7003}
    assert mock_run.call_args.args[0].state.base_url == "http://toml"

    result, mock_run = _start(runner, "--stateless", env={"IMNOT_BIND_PORT": "7002", "IMNOT_BASE_URL": "http://env"})
    assert mock_run.call_args.kwargs["port"] == 7002
    assert mock_run.call_args.args[0].state.base_url == "http://env"

    result, mock_run = _start(runner, "--stateless", "--base-url", "http://flag", env={"IMNOT_BASE_URL": "http://env"})
    assert mock_run.call_args.args[0].state.base_url == "http://flag"


def test_kubernetes_service_env_vars_are_not_read(runner, project):
    """A Service named "imnot" makes Kubernetes inject these into every pod of the namespace."""
    env = {"IMNOT_PORT": "tcp://10.0.0.7:8000", "IMNOT_SERVICE_HOST": "10.0.0.7", "IMNOT_SERVICE_PORT": "8000"}
    result, mock_run = _start(runner, "--stateless", env=env)
    assert result.exit_code == 0, result.output
    assert mock_run.call_args.kwargs == {"host": "127.0.0.1", "port": 8000}


def test_reload_factory_reads_base_url_from_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("IMNOT_PARTNERS_DIR", "")
    monkeypatch.setenv("IMNOT_DB_PATH", str(tmp_path / "x.db"))
    assert create_app_from_env().state.base_url == "http://localhost:8000"
    monkeypatch.setenv("IMNOT_BASE_URL", "https://mock.example.test")
    assert create_app_from_env().state.base_url == "https://mock.example.test"


def test_start_reload_passes_base_url_flag_to_the_factory(runner, project):
    result, _ = _start(runner, "--reload", "--base-url", "http://flag")
    assert result.exit_code == 0, result.output
    assert os.environ["IMNOT_BASE_URL"] == "http://flag"


# ---------------------------------------------------------------------------
# Partners through the admin API: in memory when stateless, on disk otherwise
# ---------------------------------------------------------------------------

_NEW_PARTNER = _PARTNER.format(name="bookingco")
_EDITED = """\
partner: staylink
datapoints:
  - name: ping
    pattern: static
    endpoints:
      - method: GET
        path: /staylink/ping
        validate:
          query:
            token: {required: true}
        response:
          status: 200
          body: {ok: edited}
"""


@pytest.fixture
def stateless_client(project):
    app = create_app(partners_dir=project / "partners", db_path=Path(":memory:"), stateless=True)
    with TestClient(app) as c:
        yield c, project


def test_healthz_reports_the_mode(project):
    with TestClient(create_app(partners_dir=None, db_path=Path(":memory:"), stateless=True)) as c:
        assert c.get("/healthz").json()["stateless"] is True
    with TestClient(create_app(partners_dir=None, db_path=Path(":memory:"))) as c:
        body = c.get("/healthz").json()
        assert body["stateless"] is False
        assert body["status"] == "ok" and body["auth_required"] is False  # the old keys are still there


def test_stateless_create_partner_lives_in_memory(stateless_client):
    c, project = stateless_client
    before = _files(project)
    created = c.post("/imnot/admin/partners", content=_NEW_PARTNER)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created"] is True and body["file"] is None and body["directory"] is None
    assert "GET /bookingco/ping" in body["routes_added"]
    assert _files(project) == before  # nothing written

    assert c.get("/bookingco/ping").json() == {"ok": True}
    assert "bookingco" in [p["partner"] for p in c.get("/imnot/admin/partners").json()]
    assert c.get("/imnot/admin/partners/bookingco").json()["partner"] == "bookingco"
    # Payload routes of the new partner work too.
    assert c.post("/imnot/admin/bookingco/charges/payload", json={"a": 1}).status_code == 200
    assert c.get("/bookingco/charges").json() == {"a": 1}

    assert c.post("/imnot/admin/partners", content=_NEW_PARTNER).status_code == 409
    assert c.post("/imnot/admin/partners?force=true", content=_NEW_PARTNER).status_code == 200
    assert c.post("/imnot/admin/partners", content="partner: [").status_code == 422
    assert c.post("/imnot/admin/partners", content=_PARTNER.format(name="bad name")).status_code == 422


def test_stateless_works_without_a_partners_dir():
    with TestClient(create_app(partners_dir=None, db_path=Path(":memory:"), stateless=True)) as c:
        assert c.post("/imnot/admin/partners", content=_NEW_PARTNER).status_code == 201
        assert c.get("/bookingco/ping").status_code == 200
        assert c.get("/imnot/admin/partners/bookingco?format=yaml").text == _NEW_PARTNER
        assert c.get("/imnot/admin/partners/nope").status_code == 404


def test_stateless_edit_replaces_the_partner_completely(stateless_client):
    """An edit applies whole, with no reload: removed endpoints stop answering, validate: is enforced."""
    c, project = stateless_client
    on_disk = (project / "partners" / "staylink" / "partner.yaml").read_text()
    assert c.post("/imnot/admin/partners", content=_EDITED).status_code == 409  # exists: needs force
    assert c.post("/imnot/admin/partners?force=true", content=_EDITED).status_code == 200

    assert c.get("/staylink/ping").status_code == 422  # the new validate: rule
    assert c.get("/staylink/ping?token=x").json() == {"ok": "edited"}
    assert c.get("/staylink/charges").status_code == 404  # datapoint removed by the edit
    assert c.post("/imnot/admin/staylink/charges/payload", json={}).status_code in (404, 405)
    assert c.get("/imnot/admin/partners/staylink").json()["datapoints"][0]["endpoints"][0]["validate"]
    assert (project / "partners" / "staylink" / "partner.yaml").read_text() == on_disk


def test_stateless_builder_guards_read_the_in_memory_yaml(stateless_client):
    c, _ = stateless_client
    assert c.post("/imnot/admin/partners?force=true", content=_EDITED).status_code == 200
    from_form = _EDITED.replace("        validate:\n          query:\n            token: {required: true}\n", "")

    guarded = c.post("/imnot/admin/partners?force=true&compare_to=staylink", content=from_form)
    assert guarded.status_code == 409
    assert any("validate" in d for d in guarded.json()["dropped"])

    merged = c.post("/imnot/admin/partners?force=true&merge_from=staylink&compare_to=staylink", content=from_form)
    assert merged.status_code == 200, merged.text
    assert c.get("/staylink/ping").status_code == 422  # validate: was carried over from memory


def test_stateless_delete_is_in_memory_and_reload_goes_back_to_the_files(stateless_client):
    c, project = stateless_client
    c.post("/imnot/admin/partners", content=_NEW_PARTNER)
    c.post("/imnot/admin/partners?force=true", content=_EDITED)
    c.post("/imnot/admin/staylink/charges/payload", json={"uploaded": True})  # route is gone: no effect

    assert c.delete("/imnot/admin/partners/staylink").status_code == 200
    assert c.get("/staylink/ping?token=x").status_code == 404
    assert c.get("/imnot/admin/partners/staylink").status_code == 404
    assert c.delete("/imnot/admin/partners/staylink").status_code == 404
    assert (project / "partners" / "staylink" / "partner.yaml").exists()

    reloaded = c.post("/imnot/admin/reload")
    assert reloaded.status_code == 200 and reloaded.json()["status"] == "ok"
    assert c.get("/staylink/ping").json() == {"ok": True}  # the file's version, without validate:
    assert c.get("/staylink/charges").json() == {"total": 42}
    assert c.get("/bookingco/ping").status_code == 404  # the UI-made partner is gone
    assert c.get("/imnot/admin/partners/bookingco").status_code == 404
    assert [p["partner"] for p in c.get("/imnot/admin/partners").json()] == ["staylink"]


def test_download_partner_yaml(stateless_client, project):
    c, _ = stateless_client
    on_disk = (project / "partners" / "staylink" / "partner.yaml").read_text()
    r = c.get("/imnot/admin/partners/staylink?format=yaml")
    assert r.status_code == 200 and r.text == on_disk
    assert "attachment" in r.headers["content-disposition"] and "staylink" in r.headers["content-disposition"]
    c.post("/imnot/admin/partners?force=true", content=_EDITED)
    assert c.get("/imnot/admin/partners/staylink?format=yaml").text == _EDITED
    assert c.get("/imnot/admin/partners/nope?format=yaml").status_code == 404

    # Classic mode serves the file as it is, comments included.
    (project / "partners" / "staylink" / "partner.yaml").write_text("# mine\n" + on_disk)
    with TestClient(create_app(partners_dir=project / "partners", db_path=Path(":memory:"))) as classic:
        assert classic.get("/imnot/admin/partners/staylink?format=yaml").text.startswith("# mine\n")
        assert classic.get("/imnot/admin/partners/staylink").json()["partner"] == "staylink"


def test_partners_admin_writes_still_work_by_default(project):
    app = create_app(partners_dir=project / "partners", db_path=Path(":memory:"))
    with TestClient(app) as c:
        assert c.post("/imnot/admin/partners", content=_NEW_PARTNER).status_code == 201
        assert (project / "partners" / "bookingco" / "partner.yaml").exists()
        assert c.delete("/imnot/admin/partners/bookingco").status_code == 200
        assert not (project / "partners" / "bookingco").exists()


def test_unwritable_partners_dir_gives_403_not_500(project):
    if os.getuid() == 0:
        pytest.skip("root ignores directory permissions")
    partners = project / "partners"
    app = create_app(partners_dir=partners, db_path=Path(":memory:"))
    partners.chmod(0o555)
    (partners / "staylink").chmod(0o555)
    try:
        with TestClient(app) as c:
            created = c.post("/imnot/admin/partners", content=_NEW_PARTNER)
            assert created.status_code == 403
            assert "not writable" in created.json()["detail"]
            assert c.get("/bookingco/ping").status_code == 404  # classic mode never falls back to memory
            overwritten = c.post("/imnot/admin/partners?force=true", content=_PARTNER.format(name="staylink"))
            assert overwritten.status_code in (200, 403)  # the file itself may still be writable
            deleted = c.delete("/imnot/admin/partners/staylink")
            assert deleted.status_code == 403
            assert c.get("/staylink/ping").status_code == 200  # routes are kept when the delete fails
    finally:
        partners.chmod(0o755)
        (partners / "staylink").chmod(0o755)


# ---------------------------------------------------------------------------
# Docker image
# ---------------------------------------------------------------------------


def test_dockerfile_runs_as_a_numeric_non_root_user_with_overridable_defaults():
    dockerfile = (ROOT / "Dockerfile").read_text()
    user = re.search(r"^USER (\S+)$", dockerfile, re.MULTILINE)
    assert user and re.fullmatch(r"[1-9]\d*:[1-9]\d*", user.group(1)), "USER must be numeric (runAsNonRoot)"
    # The image's defaults did not change: same host, database and partners directory as the old ENTRYPOINT flags.
    for default in ("IMNOT_BIND_HOST=0.0.0.0", "IMNOT_DB_PATH=/app/data/imnot.db", "IMNOT_PARTNERS_DIR=/app/partners"):
        assert default in dockerfile
    assert "PYTHONUNBUFFERED=1" in dockerfile
    assert 'ENTRYPOINT ["imnot", "start"]' in dockerfile
