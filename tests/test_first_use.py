"""First use: the empty state's "Load examples" endpoint, `imnot init --empty`, and what
`--strict` / `imnot validate` accept when there is no partner at all."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.cli import cli
from imnot.partners import EXAMPLE_PARTNERS, example_partner_files, load_example_partner

EXAMPLES = "/imnot/admin/partners/examples"
NAMES = ["staylink", "bookingco", "ratesync"]

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
"""


@pytest.fixture
def runner():
    return CliRunner()


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _names(client) -> list[str]:
    return sorted(p["partner"] for p in client.get("/imnot/admin/partners").json())


def _start(runner, *args):
    with patch("imnot.cli.uvicorn.run") as mock_run:
        result = runner.invoke(cli, ["start", *args])
    return result, mock_run


# ---------------------------------------------------------------------------
# POST /imnot/admin/partners/examples
# ---------------------------------------------------------------------------


def test_examples_are_the_ones_init_writes(runner, tmp_path):
    runner.invoke(cli, ["init", "--dir", str(tmp_path)])
    assert [name for name, _ in EXAMPLE_PARTNERS] == NAMES
    for name in NAMES:
        yaml_text, payloads = example_partner_files(name)
        assert (tmp_path / "partners" / name / "partner.yaml").read_text() == yaml_text
        for file_name, text in payloads.items():
            assert (tmp_path / "partners" / name / "payloads" / file_name).read_text() == text
    partner, _ = load_example_partner("ratesync")
    assert set(partner.seed_payloads) == {"rate_update", "properties"}


def test_stateless_loads_examples_in_memory_and_reload_drops_them(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    with TestClient(create_app(partners_dir=partners_dir, db_path=Path(":memory:"), stateless=True)) as c:
        assert _names(c) == []
        r = c.post(EXAMPLES)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["partners"] == NAMES and body["persisted"] is False
        assert "GET /ratesync/v1/properties" in body["routes_added"] and body["routes_conflicts"] == []
        assert _names(c) == sorted(NAMES)
        assert _files(tmp_path) == set()  # nothing written

        # The seeded payload answers right away, and a non-payload pattern works too.
        page = c.get("/ratesync/v1/properties?limit=2").json()
        assert [p["id"] for p in page["properties"]] == ["P-001", "P-002"]
        assert c.post("/oauth/token").status_code == 200
        # The Builder can open an in-memory example for editing.
        assert c.get("/imnot/admin/partners/ratesync").json()["partner"] == "ratesync"

        assert c.post("/imnot/admin/reload").status_code == 200
        assert _names(c) == []
        assert c.get("/ratesync/v1/properties").status_code == 404
        assert c.post(EXAMPLES).status_code == 201  # and they can be loaded again


def test_classic_writes_examples_as_files_like_init(runner, tmp_path):
    runner.invoke(cli, ["init", "--dir", str(tmp_path / "ref")])
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    with TestClient(create_app(partners_dir=partners_dir, db_path=tmp_path / "imnot.db")) as c:
        r = c.post(EXAMPLES)
        assert r.status_code == 201, r.text
        assert r.json()["persisted"] is True
        assert _files(partners_dir) == _files(tmp_path / "ref" / "partners")
        assert c.get("/ratesync/v1/properties?limit=2").json()["total"] == 3

        # A reload keeps them: they are ordinary files now.
        reload = c.post("/imnot/admin/reload").json()
        assert reload["status"] == "ok" and reload["removed"] == []
        assert _names(c) == sorted(NAMES)
        assert c.get("/ratesync/v1/properties?limit=2").json()["total"] == 3
    assert runner.invoke(cli, ["validate", "--partners-dir", str(partners_dir)]).exit_code == 0


@pytest.mark.parametrize("stateless", [True, False])
def test_examples_409_and_nothing_loaded_if_one_already_exists(tmp_path, stateless):
    partners_dir = tmp_path / "partners"
    (partners_dir / "bookingco").mkdir(parents=True)
    (partners_dir / "bookingco" / "partner.yaml").write_text(_PARTNER.format(name="bookingco"))
    before = _files(partners_dir)
    db = Path(":memory:") if stateless else tmp_path / "imnot.db"
    with TestClient(create_app(partners_dir=partners_dir, db_path=db, stateless=stateless)) as c:
        r = c.post(EXAMPLES)
        assert r.status_code == 409
        assert r.json()["existing"] == ["bookingco"] and "bookingco" in r.json()["detail"]
        assert _names(c) == ["bookingco"]
        assert c.get("/bookingco/ping").json() == {"ok": True}
    assert _files(partners_dir) == before


def test_classic_409_on_a_leftover_directory_that_is_not_a_loaded_partner(tmp_path):
    partners_dir = tmp_path / "partners"
    (partners_dir / "ratesync").mkdir(parents=True)  # e.g. a half-deleted partner
    with TestClient(create_app(partners_dir=partners_dir, db_path=tmp_path / "imnot.db")) as c:
        r = c.post(EXAMPLES)
        assert r.status_code == 409 and r.json()["existing"] == ["ratesync"]
    assert _files(partners_dir) == set()


def test_second_call_is_a_409(tmp_path):
    with TestClient(create_app(partners_dir=None, db_path=Path(":memory:"), stateless=True)) as c:
        assert c.post(EXAMPLES).status_code == 201  # stateless needs no partners directory at all
        r = c.post(EXAMPLES)
        assert r.status_code == 409 and r.json()["existing"] == NAMES


def test_classic_without_partners_dir_is_a_400(tmp_path):
    with TestClient(create_app(partners_dir=None, db_path=tmp_path / "imnot.db")) as c:
        r = c.post(EXAMPLES)
        assert r.status_code == 400 and "imnot init" in r.json()["detail"]


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs POSIX permissions as non-root")
def test_classic_read_only_partners_dir_is_a_403(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    partners_dir.chmod(0o555)
    try:
        with TestClient(create_app(partners_dir=partners_dir, db_path=tmp_path / "imnot.db")) as c:
            r = c.post(EXAMPLES)
            assert r.status_code == 403 and "--stateless" in r.json()["detail"]
            assert _names(c) == []
            assert c.get("/ratesync/v1/properties").status_code == 404
    finally:
        partners_dir.chmod(0o755)


def test_examples_endpoint_needs_the_admin_key(tmp_path):
    app = create_app(partners_dir=None, db_path=Path(":memory:"), stateless=True, admin_key="secret")
    with TestClient(app) as c:
        assert c.post(EXAMPLES).status_code == 401
        assert c.post(EXAMPLES, headers={"Authorization": "Bearer secret"}).status_code == 201


def test_creating_a_partner_still_works_after_the_refactor(tmp_path):
    """POST /imnot/admin/partners shares its hot-load step with the examples endpoint."""
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()
    with TestClient(create_app(partners_dir=partners_dir, db_path=tmp_path / "imnot.db")) as c:
        r = c.post("/imnot/admin/partners", content=_PARTNER.format(name="acme"))
        assert r.status_code == 201 and r.json()["routes_added"] == ["GET /acme/ping"]
        assert c.get("/acme/ping").json() == {"ok": True}
        assert c.post(EXAMPLES).status_code == 201  # other partners do not block the examples
        assert _names(c) == ["acme", "bookingco", "ratesync", "staylink"]


# ---------------------------------------------------------------------------
# The UI
# ---------------------------------------------------------------------------


def test_ui_ships_the_first_use_empty_state(tmp_path):
    with TestClient(create_app(partners_dir=None, db_path=tmp_path / "imnot.db")) as c:
        html = c.get("/imnot/admin/ui").text
    assert "Create your first partner" in html and "Load examples" in html
    assert "/imnot/admin/partners/examples" in html
    assert "go away on Reload or restart" in html  # the stateless note
    assert ".first-use {" in html  # CSS inlined by `make ui`


# ---------------------------------------------------------------------------
# imnot init --empty
# ---------------------------------------------------------------------------


def test_init_empty_creates_the_project_without_examples(runner, tmp_path):
    result = runner.invoke(cli, ["init", "--empty", "--dir", str(tmp_path / "proj")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "proj" / "partners").is_dir()
    assert list((tmp_path / "proj" / "partners").iterdir()) == []
    assert (tmp_path / "proj" / "imnot.toml").is_file()
    assert "staylink" not in result.output and "partners/   (empty)" in result.output
    # Same guard as a plain init: never touch an existing partners/.
    assert runner.invoke(cli, ["init", "--empty", "--dir", str(tmp_path / "proj")]).exit_code == 1


def test_init_without_empty_is_unchanged(runner, tmp_path):
    result = runner.invoke(cli, ["init", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert _files(tmp_path / "partners") == {
        "staylink/partner.yaml",
        "bookingco/partner.yaml",
        "ratesync/partner.yaml",
        "ratesync/payloads/properties.json",
        "ratesync/payloads/rate_update.json",
    }
    assert "partners/staylink/partner.yaml   (oauth + polling)" in result.output
    assert "partners/ratesync/payloads/properties.json   (example payload)" in result.output
    assert "Run `imnot start` to launch the mock server." in result.output


# ---------------------------------------------------------------------------
# --strict and `imnot validate` with no partners
# ---------------------------------------------------------------------------


def test_strict_starts_on_a_completely_empty_partners_dir(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "partners").mkdir()
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 0, result.output
    assert "is empty" in result.output
    mock_run.assert_called_once()


def test_strict_ignores_dotfiles_in_an_empty_partners_dir(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "partners").mkdir()
    (tmp_path / "partners" / ".gitkeep").write_text("")
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()


@pytest.mark.parametrize(
    "wrong",
    ["partners/partners/staylink/partner.yaml", "partners/partner.yaml", "partners/staylink/staylink.yaml"],
)
def test_strict_and_validate_still_fail_on_a_wrong_layout(runner, tmp_path, monkeypatch, wrong):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / wrong
    path.parent.mkdir(parents=True)
    path.write_text(_PARTNER.format(name="staylink"))
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 1
    assert "No partner.yaml files found" in result.output and "--strict: refusing to start" in result.output
    mock_run.assert_not_called()
    validate = runner.invoke(cli, ["validate", "--partners-dir", str(tmp_path / "partners")])
    assert validate.exit_code == 1 and "No partner.yaml files found" in validate.output


def test_strict_still_fails_on_an_empty_subfolder(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "partners" / "staylink").mkdir(parents=True)
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 1
    mock_run.assert_not_called()


def test_strict_still_fails_without_a_partners_dir(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result, mock_run = _start(runner, "--strict", "--stateless")
    assert result.exit_code == 1 and "--strict: no partners directory found" in result.output
    mock_run.assert_not_called()


def test_validate_passes_on_a_completely_empty_dir(runner, tmp_path):
    result = runner.invoke(cli, ["validate", "--partners-dir", str(tmp_path)])
    assert result.exit_code == 0 and "is empty" in result.output
    assert runner.invoke(cli, ["validate", "--partners-dir", str(tmp_path / "nope")]).exit_code == 1
