"""Polling steps that answer "pending" N times per request id before the real response."""

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.loader.yaml_loader import parse_partner_yaml

_YAML = """\
partner: slowco
datapoints:
  - name: report
    pattern: polling
    endpoints:
      - step: 1
        method: POST
        path: /slowco/reports
        response:
          status: 202
          generates_id: true
          id_body_field: reportId
      - step: 2
        method: GET
        path: /slowco/reports/{{id}}/status
        response:
          status: 200
          body: {{state: DONE}}
{status_pending}
      - step: 3
        method: GET
        path: /slowco/reports/{{id}}
        response:
          status: 200
          returns_payload: true
{fetch_pending}
"""


def _client(tmp_path, status_pending="", fetch_pending=""):
    d = tmp_path / "partners" / "slowco"
    d.mkdir(parents=True)
    (d / "partner.yaml").write_text(_YAML.format(status_pending=status_pending, fetch_pending=fetch_pending))
    return TestClient(create_app(partners_dir=tmp_path / "partners", db_path=tmp_path / "p.db"))


def _submit(c):
    return c.post("/slowco/reports").json()["reportId"]


def test_status_step_is_pending_n_times_per_id_then_done(tmp_path):
    pending = "          pending: {times: 2, body: {state: RUNNING}, headers: {Retry-After: 1}}"
    with _client(tmp_path, status_pending=pending) as c:
        first, second = _submit(c), _submit(c)
        a1, a2, a3 = (c.get(f"/slowco/reports/{first}/status") for _ in range(3))
        b1 = c.get(f"/slowco/reports/{second}/status")

    assert (a1.status_code, a1.json()) == (202, {"state": "RUNNING"})
    assert a1.headers["retry-after"] == "1"
    assert a2.status_code == 202
    assert (a3.status_code, a3.json()) == (200, {"state": "DONE"})
    assert b1.status_code == 202  # a new id starts from zero


def test_fetch_step_can_be_pending_before_returning_the_payload(tmp_path):
    with _client(tmp_path, fetch_pending="          pending: {times: 1, status: 404}") as c:
        c.post("/imnot/admin/slowco/report/payload", json={"rows": 3})
        rid = _submit(c)
        assert c.get(f"/slowco/reports/{rid}").status_code == 404
        assert c.get(f"/slowco/reports/{rid}").json() == {"rows": 3}


def test_status_step_with_unknown_id_is_404_not_done(tmp_path):
    with _client(tmp_path) as c:
        r = c.get("/slowco/reports/never-submitted/status")
    assert r.status_code == 404


def test_without_pending_the_flow_is_unchanged(tmp_path):
    with _client(tmp_path) as c:
        rid = _submit(c)
        assert c.get(f"/slowco/reports/{rid}/status").json() == {"state": "DONE"}


@pytest.mark.parametrize(
    "status_pending, message",
    [
        ("          pending: {status: 202}", "'pending.times' is required"),
        ("          pending: {times: 0}", "'pending.times' is required"),
        ("          pending: {times: 1, status: 99}", "'pending.status'"),
        ("          pending: {times: 1, retry: true}", "unknown key"),
        ("          pending: 3", "must be a mapping"),
    ],
)
def test_bad_pending_config_is_a_load_error(status_pending, message):
    with pytest.raises(ValueError, match=message):
        parse_partner_yaml(_YAML.format(status_pending=status_pending, fetch_pending=""))


def test_pending_needs_an_id_in_the_path_and_not_the_submit_step():
    no_id = _YAML.replace("/slowco/reports/{{id}}/status", "/slowco/status")
    with pytest.raises(ValueError, match="needs '\\{id\\}' in the path"):
        parse_partner_yaml(no_id.format(status_pending="          pending: {times: 1}", fetch_pending=""))
    on_submit = _YAML.format(status_pending="", fetch_pending="").replace(
        "          id_body_field: reportId", "          id_body_field: reportId\n          pending: {times: 1}"
    )
    with pytest.raises(ValueError, match="cannot be used on the step that generates"):
        parse_partner_yaml(on_submit)
