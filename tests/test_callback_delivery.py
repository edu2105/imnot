"""Callback delivery: custom headers, HMAC signature and retries."""

import hashlib
import hmac
import json

import pytest

import imnot.engine.patterns.push as push
from imnot.loader.yaml_loader import parse_partner_yaml


class _Recorder:
    """Stands in for httpx.AsyncClient; answers with the queued statuses (or raises)."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return type("R", (), {"status_code": outcome, "is_success": 200 <= outcome < 300})()


class _Store:
    def resolve_payload(self, partner, datapoint, session_id):
        return {"status": "DONE", "requestId": "{{request_id}}"}


async def _fire(monkeypatch, outcomes, delivery, context=None):
    rec = _Recorder(outcomes)
    monkeypatch.setattr(push.httpx, "AsyncClient", rec)
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(push.asyncio, "sleep", fake_sleep)
    await push.fire_callback(
        _Store(),
        "p",
        "d",
        None,
        "http://x/cb",
        "POST",
        context=context or {"request_id": "r-1"},
        delivery=delivery,
    )
    return rec, sleeps


@pytest.mark.asyncio
async def test_custom_headers_are_sent_and_templated(monkeypatch):
    rec, _ = await _fire(monkeypatch, [200], {"headers": {"X-Source": "imnot", "X-Request": "{{request_id}}"}})
    assert rec.calls[0]["headers"] == {"X-Source": "imnot", "X-Request": "r-1"}
    assert rec.calls[0]["json"] == {"status": "DONE", "requestId": "r-1"}


@pytest.mark.asyncio
async def test_signature_is_an_hmac_of_the_exact_bytes_sent(monkeypatch):
    rec, _ = await _fire(monkeypatch, [200], {"signature": {"secret": "s3cret", "header": "X-Signature"}})
    call = rec.calls[0]
    body = call["content"]
    expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert call["headers"]["X-Signature"] == f"sha256={expected}"
    assert call["headers"]["Content-Type"] == "application/json"
    assert json.loads(body) == {"status": "DONE", "requestId": "r-1"}


@pytest.mark.asyncio
async def test_default_signature_header_and_algorithm(monkeypatch):
    rec, _ = await _fire(monkeypatch, [200], {"signature": {"secret": "k", "algorithm": "sha512"}})
    assert rec.calls[0]["headers"]["X-Imnot-Signature"].startswith("sha512=")


@pytest.mark.asyncio
async def test_retries_on_errors_and_non_2xx_with_linear_backoff(monkeypatch):
    rec, sleeps = await _fire(
        monkeypatch, [ConnectionError("down"), 503, 200], {"retries": {"attempts": 3, "backoff_seconds": 2}}
    )
    assert len(rec.calls) == 3
    assert sleeps == [2.0, 4.0]


@pytest.mark.asyncio
async def test_stops_after_the_last_attempt(monkeypatch):
    rec, sleeps = await _fire(monkeypatch, [500, 500], {"retries": {"attempts": 2, "backoff_seconds": 0}})
    assert len(rec.calls) == 2 and sleeps == [0.0]


@pytest.mark.asyncio
async def test_without_delivery_config_behaves_as_before(monkeypatch):
    rec, sleeps = await _fire(monkeypatch, [500], None)
    assert len(rec.calls) == 1 and sleeps == [] and "json" in rec.calls[0]


_YAML = """\
partner: cb
datapoints:
  - name: notify
    pattern: callback
    endpoints:
      - method: POST
        path: /cb/notify
        response:
          status: 202
          callback_url_field: callbackUrl
{extra}
"""


@pytest.mark.parametrize(
    "extra, message",
    [
        ("          callback_headers: [a]", "'callback_headers' must be a mapping"),
        ("          callback_signature: {header: X}", "'callback_signature.secret' is required"),
        ("          callback_signature: {secret: k, algorithm: md5}", "'callback_signature.algorithm'"),
        ("          callback_retries: {attempts: 0}", "'callback_retries.attempts'"),
        ("          callback_retries: {attempts: 2, backoff_seconds: 90}", "'callback_retries.backoff_seconds'"),
        ("          callback_retries: {tries: 2}", "'callback_retries' must be a mapping with keys"),
    ],
)
def test_bad_delivery_config_is_a_load_error(extra, message):
    with pytest.raises(ValueError, match=message):
        parse_partner_yaml(_YAML.format(extra=extra))


def test_valid_delivery_config_passes_strict_validation():
    extra = (
        "          callback_headers: {X-Source: imnot}\n"
        "          callback_signature: {secret: k}\n"
        "          callback_retries: {attempts: 3, backoff_seconds: 1}"
    )
    parse_partner_yaml(_YAML.format(extra=extra), strict=True)
