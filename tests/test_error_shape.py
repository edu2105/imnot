"""Partner-shaped error: blocks for validate: and rate_limit:."""

import pytest
from fastapi.testclient import TestClient

from imnot.api.server import create_app
from imnot.loader.yaml_loader import parse_partner_yaml

_YAML = """\
partner: errco
datapoints:
  - name: orders
    pattern: fetch
    endpoints:
      - method: GET
        path: /errco/orders
{blocks}
        response:
          status: 200
"""

_VALIDATE = """\
        validate:
          query:
            id: {required: true}
            limit: {type: integer}
{error}"""

_RATE = """\
        rate_limit:
          requests_per_minute: 1
{error}"""


def _client(tmp_path, blocks):
    d = tmp_path / "partners" / "errco"
    d.mkdir(parents=True)
    (d / "partner.yaml").write_text(_YAML.replace("{blocks}", blocks))
    return TestClient(create_app(partners_dir=tmp_path / "partners", db_path=tmp_path / "e.db"))


def test_validation_error_uses_the_partner_shape(tmp_path):
    error = """\
          error:
            status: 400
            headers: {X-Error-Code: INVALID}
            body: {code: INVALID_REQUEST, message: "Bad request: {{message}}", details: "{{errors}}"}"""
    with _client(tmp_path, _VALIDATE.replace("{error}", error)) as c:
        r = c.get("/errco/orders?limit=abc")
    assert r.status_code == 400 and r.headers["x-error-code"] == "INVALID"
    body = r.json()
    assert body["code"] == "INVALID_REQUEST"
    assert isinstance(body["details"], list) and len(body["details"]) == 2
    assert body["message"].startswith("Bad request: ") and "; " in body["message"]


def test_without_error_block_validation_keeps_imnot_shape(tmp_path):
    with _client(tmp_path, _VALIDATE.replace("{error}", "")) as c:
        r = c.get("/errco/orders")
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


def test_rate_limit_error_uses_the_partner_shape_and_keeps_retry_after(tmp_path):
    error = """\
          error:
            status: 429
            body: {error: too_many_requests, retryInSeconds: "{{retry_after}}", limitPerMinute: "{{limit}}"}"""
    with _client(tmp_path, _RATE.replace("{error}", error)) as c:
        c.post("/imnot/admin/errco/orders/payload", json={"ok": True})
        assert c.get("/errco/orders").status_code == 200
        r = c.get("/errco/orders")
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    body = r.json()
    assert body["error"] == "too_many_requests" and body["limitPerMinute"] == 1
    assert body["retryInSeconds"] == int(r.headers["retry-after"])


def test_without_error_block_rate_limit_keeps_imnot_shape(tmp_path):
    with _client(tmp_path, _RATE.replace("{error}", "")) as c:
        c.post("/imnot/admin/errco/orders/payload", json={"ok": True})
        c.get("/errco/orders")
        r = c.get("/errco/orders")
    assert r.status_code == 429 and "Rate limit exceeded" in r.json()["detail"]


@pytest.mark.parametrize(
    "blocks, message",
    [
        (_VALIDATE.replace("{error}", "          error: {body: {}}"), "'error.status' is required"),
        (
            _VALIDATE.replace("{error}", "          error: {status: 400, code: X}"),
            "'error' must be a mapping with keys",
        ),
        (_RATE.replace("{error}", "          error: {status: 999}"), "'error.status'"),
        (_RATE.replace("{error}", "          error: {status: 429, headers: [x]}"), "'error.headers' must be a mapping"),
    ],
)
def test_bad_error_blocks_are_load_errors(blocks, message):
    with pytest.raises(ValueError, match=message):
        parse_partner_yaml(_YAML.replace("{blocks}", blocks))


def test_error_blocks_pass_strict_validation():
    blocks = (
        _VALIDATE.replace("{error}", "          error: {status: 400}")
        + "\n"
        + _RATE.replace("{error}", "          error: {status: 429}")
    )
    parse_partner_yaml(_YAML.replace("{blocks}", blocks), strict=True)
