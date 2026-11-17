"""Fault injection: endpoint-level delay_ms and fail: blocks."""

import time

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.loader.yaml_loader import parse_partner_yaml

_YAML = """\
partner: flaky
datapoints:
  - name: charges
    pattern: fetch
    endpoints:
      - method: GET
        path: /flaky/charges
{extra}
        response:
          status: 200
  - name: notify
    pattern: callback
    endpoints:
      - method: POST
        path: /flaky/notify
{notify_extra}
        response:
          status: 202
          callback_url_field: callbackUrl
"""


def _client(tmp_path, extra="", notify_extra=""):
    d = tmp_path / "partners" / "flaky"
    d.mkdir(parents=True)
    (d / "partner.yaml").write_text(_YAML.format(extra=extra, notify_extra=notify_extra))
    app = create_app(partners_dir=tmp_path / "partners", db_path=tmp_path / "f.db")
    return TestClient(app)


def test_fail_first_n_then_succeed(tmp_path):
    extra = "        fail: {status: 503, first_n: 2, headers: {Retry-After: 1}}"
    with _client(tmp_path, extra) as c:
        c.post("/imnot/admin/flaky/charges/payload", json={"ok": True})
        first, second, third = (c.get("/flaky/charges") for _ in range(3))
    assert (first.status_code, second.status_code, third.status_code) == (503, 503, 200)
    assert first.headers["retry-after"] == "1"
    assert first.json() == {"detail": "Simulated failure (imnot fail: block)"}
    assert third.json() == {"ok": True}


def test_fail_without_first_n_always_fails_with_custom_body(tmp_path):
    extra = '        fail: {status: 429, body: {error: "slow down"}}'
    with _client(tmp_path, extra) as c:
        responses = [c.get("/flaky/charges") for _ in range(3)]
    assert [r.status_code for r in responses] == [429, 429, 429]
    assert responses[0].json() == {"error": "slow down"}


def test_first_n_is_counted_per_session_and_reset_by_admin(tmp_path):
    extra = "        fail: {status: 500, first_n: 1}"
    with _client(tmp_path, extra) as c:
        sid = c.post("/imnot/admin/flaky/charges/payload/session", json={"s": 1}).json()["session_id"]
        other = c.post("/imnot/admin/flaky/charges/payload/session", json={"s": 2}).json()["session_id"]
        assert c.get("/flaky/charges", headers={"X-Imnot-Session": sid}).status_code == 500
        assert c.get("/flaky/charges", headers={"X-Imnot-Session": sid}).status_code == 200
        assert c.get("/flaky/charges", headers={"X-Imnot-Session": other}).status_code == 500

        assert c.delete("/imnot/admin/faults").json()["status"] == "ok"
        assert c.get("/flaky/charges", headers={"X-Imnot-Session": sid}).status_code == 500


def test_delay_ms_delays_the_response(tmp_path):
    with _client(tmp_path, "        delay_ms: 300") as c:
        c.post("/imnot/admin/flaky/charges/payload", json={"ok": True})
        start = time.perf_counter()
        r = c.get("/flaky/charges")
        elapsed = time.perf_counter() - start
    assert r.status_code == 200 and elapsed >= 0.3


def test_fail_applies_to_handlers_with_extra_parameters(tmp_path, monkeypatch):
    """The callback handler also takes background_tasks: the wrapper must keep its signature."""
    import imnot.engine.patterns.push as push

    async def no_callback(*args, **kwargs):
        return None

    monkeypatch.setattr(push, "fire_callback", no_callback)
    with _client(tmp_path, notify_extra="        fail: {status: 503, first_n: 1}") as c:
        c.post("/imnot/admin/flaky/notify/payload", json={"result": "ok"})
        body = {"callbackUrl": "http://127.0.0.1:9/never"}
        assert c.post("/flaky/notify", json=body).status_code == 503
        assert c.post("/flaky/notify", json=body).status_code == 202


def test_endpoints_without_faults_are_untouched(tmp_path):
    with _client(tmp_path) as c:
        c.post("/imnot/admin/flaky/charges/payload", json={"ok": True})
        assert c.get("/flaky/charges").json() == {"ok": True}


@pytest.mark.parametrize(
    "extra, message",
    [
        ("        delay_ms: -1", "'delay_ms' must be an integer"),
        ("        delay_ms: 60001", "'delay_ms' must be an integer"),
        ("        fail: {first_n: 1}", "'fail.status' is required"),
        ("        fail: {status: 503, first_n: 0}", "'fail.first_n' must be a positive integer"),
        ("        fail: {status: 503, retries: 2}", "unknown key"),
        ("        fail: 503", "'fail' must be a mapping"),
    ],
)
def test_bad_fault_config_is_a_load_error(extra, message):
    with pytest.raises(ValueError, match=message):
        parse_partner_yaml(_YAML.format(extra=extra, notify_extra=""))
