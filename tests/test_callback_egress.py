"""Where a callback may be sent: imnot.engine.egress.CallbackPolicy and its use by the callback pattern."""

from __future__ import annotations

import ipaddress

import pytest
from click.testing import CliRunner

import imnot.engine.egress as egress
from imnot.api.server import create_app
from imnot.cli import cli
from imnot.engine.egress import CallbackPolicy
from tests.test_push_pattern import _BODY_FIELD_YAML, _build_client, _mock_httpx


def _resolves_to(monkeypatch, *addresses: str) -> None:
    async def fake_resolve(host, port):
        return [ipaddress.ip_address(a) for a in addresses]

    monkeypatch.setattr(egress, "_resolve", fake_resolve)


# ---------------------------------------------------------------------------
# Always-on rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://169.254.170.2/v2/credentials",
        "http://[fe80::1]/x",
        "http://[fd00:ec2::254]/x",
        "http://[::ffff:169.254.169.254]/x",
    ],
)
async def test_metadata_and_link_local_addresses_are_refused(url):
    assert "link-local" in await CallbackPolicy().problem(url)


@pytest.mark.asyncio
async def test_a_name_that_resolves_to_metadata_is_refused(monkeypatch):
    _resolves_to(monkeypatch, "10.0.0.5", "169.254.169.254")
    assert "link-local" in await CallbackPolicy().problem("http://metadata.internal/x")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["ftp://consumer/x", "file:///etc/passwd", "gopher://x/"])
async def test_only_http_and_https(url):
    assert await CallbackPolicy().problem(url) == "must use http or https"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["http://127.0.0.1:9000/cb", "http://10.1.2.3/cb", "https://[::1]/cb"])
async def test_private_and_loopback_addresses_are_allowed_by_default(url):
    # The system under test usually runs next to imnot.
    assert await CallbackPolicy().problem(url) is None


@pytest.mark.asyncio
async def test_an_unresolvable_name_is_allowed_without_an_allowlist(monkeypatch):
    _resolves_to(monkeypatch)  # the receiver may not be up yet; the delivery (and its retries) will tell
    assert await CallbackPolicy().problem("http://not-up-yet/cb") is None


# ---------------------------------------------------------------------------
# IMNOT_CALLBACK_ALLOWED_HOSTS
# ---------------------------------------------------------------------------


def test_parse_names_suffixes_and_networks():
    p = CallbackPolicy.parse(" Orders.Team-A , *.team-a.svc.cluster.local,10.20.0.0/16,, ")
    assert p.allowed_names == ("orders.team-a", ".team-a.svc.cluster.local")
    assert p.allowed_networks == (ipaddress.ip_network("10.20.0.0/16"),)
    assert not CallbackPolicy.parse(None).restricted


@pytest.mark.parametrize("bad", ["http://x", "a b", "*", "*.", "x/y", "a*b"])
def test_parse_rejects_bad_entries(bad):
    with pytest.raises(ValueError, match="invalid entry"):
        CallbackPolicy.parse(bad)


@pytest.mark.asyncio
async def test_allowlist_by_name_and_suffix(monkeypatch):
    _resolves_to(monkeypatch, "10.9.9.9")
    p = CallbackPolicy.parse("orders.team-a,*.team-a.svc")
    assert await p.problem("http://ORDERS.team-a/cb") is None
    assert await p.problem("http://hooks.team-a.svc:8080/cb") is None
    assert "allowed hosts" in await p.problem("http://team-a.svc/cb")  # *.x does not match x itself
    assert "allowed hosts" in await p.problem("http://evil.example/cb")


@pytest.mark.asyncio
async def test_allowlist_by_network_needs_every_address_inside(monkeypatch):
    p = CallbackPolicy.parse("10.20.0.0/16")
    assert await p.problem("http://10.20.1.1/cb") is None
    _resolves_to(monkeypatch, "10.20.0.7")
    assert await p.problem("http://svc/cb") is None
    _resolves_to(monkeypatch, "10.20.0.7", "10.30.0.1")
    assert "allowed hosts" in await p.problem("http://svc/cb")
    _resolves_to(monkeypatch)
    assert "allowed hosts" in await p.problem("http://svc/cb")


@pytest.mark.asyncio
async def test_allowlist_never_reopens_metadata():
    assert "link-local" in await CallbackPolicy.parse("169.254.0.0/16").problem("http://169.254.169.254/")


# ---------------------------------------------------------------------------
# The callback pattern
# ---------------------------------------------------------------------------


def test_submit_with_a_metadata_url_is_422_and_nothing_is_sent(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    store.store_global_payload("pushpartner", "notification", {"e": 1})
    patcher, mock_client = _mock_httpx()
    with patcher:
        r = client.post("/pushpartner/notify", json={"callbackUrl": "http://169.254.169.254/latest/"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Callback URL points to a link-local or cloud metadata address"
    mock_client.request.assert_not_called()


def test_submit_outside_the_allowlist_is_422(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    client.app.state.callback_policy = CallbackPolicy.parse("127.0.0.0/8")
    store.store_global_payload("pushpartner", "notification", {"e": 1})
    patcher, mock_client = _mock_httpx()
    with patcher:
        refused = client.post("/pushpartner/notify", json={"callbackUrl": "http://10.1.1.1/cb"})
        accepted = client.post("/pushpartner/notify", json={"callbackUrl": "http://127.0.0.1:9/cb"})
    assert refused.status_code == 422 and "allowed hosts" in refused.json()["detail"]
    assert accepted.status_code == 202
    assert mock_client.request.call_count == 1


def test_delivery_is_refused_when_the_name_later_resolves_to_metadata(store, tmp_path, monkeypatch):
    # DNS answered a private address at submit time and the metadata address at delivery time.
    answers = [["10.0.0.5"], ["169.254.169.254"]]

    async def flipping_resolve(host, port):
        return [ipaddress.ip_address(a) for a in answers.pop(0)]

    monkeypatch.setattr(egress, "_resolve", flipping_resolve)
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    store.store_global_payload("pushpartner", "notification", {"e": 1})
    patcher, mock_client = _mock_httpx()
    with patcher:
        r = client.post("/pushpartner/notify", json={"callbackUrl": "http://rebinding.example/cb"})
    assert r.status_code == 202
    mock_client.request.assert_not_called()


def test_retrigger_follows_the_current_policy(store, tmp_path):
    client = _build_client(_BODY_FIELD_YAML, store, tmp_path)
    store.store_global_payload("pushpartner", "notification", {"e": 1})
    patcher, mock_client = _mock_httpx()
    with patcher:
        request_id = client.post("/pushpartner/notify", json={"callbackUrl": "http://127.0.0.1:9/cb"}).json()[
            "request_id"
        ]
        client.app.state.callback_policy = CallbackPolicy.parse("10.0.0.0/8")
        r = client.post(f"/imnot/admin/pushpartner/notification/callback/{request_id}/retrigger")
    assert r.status_code == 200
    assert mock_client.request.call_count == 1  # the submit's delivery only


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_create_app_rejects_a_bad_allowlist(tmp_path):
    with pytest.raises(ValueError, match="invalid entry"):
        create_app(partners_dir=None, db_path=tmp_path / "x.db", callback_allowed_hosts="http://x")


def test_start_rejects_a_bad_allowlist_before_starting(tmp_path):
    result = CliRunner().invoke(
        cli,
        ["start", "--stateless", "--partners-dir", str(tmp_path)],
        env={"IMNOT_CALLBACK_ALLOWED_HOSTS": "orders, http://x"},
    )
    assert result.exit_code == 2
    assert "--callback-allowed-hosts" in result.output


@pytest.fixture
def store(tmp_path):
    from imnot.engine.session_store import SessionStore

    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()
