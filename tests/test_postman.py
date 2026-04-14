"""Tests for Postman collection generation.

Covers:
- Collection structure (name, schema, baseUrl variable)
- Partner and datapoint folders
- Consumer endpoint requests (method, URL, headers, body)
- Admin sub-folder presence and contents
- X-Imnot-Session header (disabled) on payload-pattern endpoints
- Push-specific body / header pre-filling
- URL path variable conversion ({param} → :param)
- CLI: `imnot export postman` writes file, respects --out, prints summary
- Admin endpoint: GET /imnot/admin/postman returns collection JSON
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imnot.cli import cli
from imnot.engine.router import register_routes
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import DatapointDef, EndpointDef, PartnerDef, load_partners
from imnot.postman import build_postman_collection, collection_stats

# ---------------------------------------------------------------------------
# Helpers — minimal partner / datapoint / endpoint builders
# ---------------------------------------------------------------------------


def _ep(method: str, path: str, response: dict | None = None, step: int | None = None) -> EndpointDef:
    return EndpointDef(method=method, path=path, response=response or {"status": 200}, step=step)


def _dp(name: str, pattern: str, endpoints: list[EndpointDef], description: str = "") -> DatapointDef:
    return DatapointDef(name=name, pattern=pattern, endpoints=endpoints, description=description)


def _partner(name: str, datapoints: list[DatapointDef], description: str = "") -> PartnerDef:
    return PartnerDef(partner=name, datapoints=datapoints, description=description, source_path=Path("/fake/partner.yaml"))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fetch_partner():
    return _partner("staylink", [
        _dp("charges", "fetch", [_ep("GET", "/staylink/charges")]),
    ])


@pytest.fixture
def push_field_partner():
    """Push datapoint where callback URL comes from a request body field."""
    ep = _ep("POST", "/partner/rates", {
        "status": 202,
        "callback_url_field": "callbackUrl",
        "callback_method": "POST",
    })
    return _partner("bookingco", [_dp("rate-push", "push", [ep])])


@pytest.fixture
def push_header_partner():
    """Push datapoint where callback URL comes from a request header."""
    ep = _ep("POST", "/partner/rates", {
        "status": 202,
        "callback_url_header": "X-Callback-URL",
    })
    return _partner("bookingco", [_dp("rate-push", "push", [ep])])


@pytest.fixture
def oauth_partner():
    return _partner("idp", [
        _dp("token", "oauth", [_ep("POST", "/oauth/token", {"status": 200})]),
    ])


@pytest.fixture
def static_partner():
    ep = _ep("POST", "/partner/auth/token", {"status": 200, "body": {"token": "abc"}})
    return _partner("idp", [_dp("token", "static", [ep])])


@pytest.fixture
def async_partner():
    ep1 = _ep("POST", "/async/jobs", {"status": 202, "generates_id": True, "id_header": "Location", "id_header_value": "/async/jobs/{id}"}, step=1)
    ep2 = _ep("GET", "/async/jobs/{id}", {"status": 200, "returns_payload": True}, step=2)
    return _partner("asyncco", [_dp("job", "async", [ep1, ep2])])


# ---------------------------------------------------------------------------
# Collection structure
# ---------------------------------------------------------------------------


def test_collection_has_correct_name_and_schema(fetch_partner):
    col = build_postman_collection([fetch_partner])
    assert col["info"]["name"] == "imnot"
    assert "v2.1.0" in col["info"]["schema"]


def test_collection_has_base_url_variable(fetch_partner):
    col = build_postman_collection([fetch_partner])
    base_url_vars = [v for v in col["variable"] if v["key"] == "baseUrl"]
    assert len(base_url_vars) == 1
    assert base_url_vars[0]["value"] == "http://localhost:8000"


def test_one_folder_per_partner():
    partners = [
        _partner("alpha", [_dp("ep", "oauth", [_ep("POST", "/alpha/token")])]),
        _partner("beta", [_dp("ep", "oauth", [_ep("POST", "/beta/token")])]),
    ]
    col = build_postman_collection(partners)
    folder_names = [item["name"] for item in col["item"]]
    assert "alpha" in folder_names
    assert "beta" in folder_names
    assert len(folder_names) == 2


def test_one_subfolder_per_datapoint():
    dp1 = _dp("charges", "fetch", [_ep("GET", "/charges")])
    dp2 = _dp("bookings", "fetch", [_ep("GET", "/bookings")])
    col = build_postman_collection([_partner("co", [dp1, dp2])])
    partner_folder = col["item"][0]
    dp_names = [item["name"] for item in partner_folder["item"]]
    assert "charges" in dp_names
    assert "bookings" in dp_names


# ---------------------------------------------------------------------------
# Consumer endpoints
# ---------------------------------------------------------------------------


def test_consumer_endpoint_method_and_url(fetch_partner):
    col = build_postman_collection([fetch_partner])
    dp_folder = col["item"][0]["item"][0]
    consumer = dp_folder["item"][0]
    assert consumer["request"]["method"] == "GET"
    assert "{{baseUrl}}" in consumer["request"]["url"]["raw"]
    assert "/staylink/charges" in consumer["request"]["url"]["raw"]


def test_consumer_endpoint_name_format():
    ep = _ep("GET", "/foo/bar")
    col = build_postman_collection([_partner("p", [_dp("d", "fetch", [ep])])])
    item = col["item"][0]["item"][0]["item"][0]
    assert item["name"] == "GET /foo/bar"


def test_get_endpoint_has_no_body(fetch_partner):
    col = build_postman_collection([fetch_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    assert "body" not in consumer["request"]


def test_post_without_known_body_has_no_body(static_partner):
    col = build_postman_collection([static_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    # static POST — Mirage doesn't know the consumer body shape
    assert "body" not in consumer["request"]


def test_post_with_known_body_has_content_type():
    ep = _ep("POST", "/partner/rates", {"status": 202, "callback_url_field": "callbackUrl"})
    col = build_postman_collection([_partner("co", [_dp("rate", "push", [ep])])])
    consumer = col["item"][0]["item"][0]["item"][0]
    headers = {h["key"]: h["value"] for h in consumer["request"]["header"] if not h.get("disabled")}
    assert headers.get("Content-Type") == "application/json"


# ---------------------------------------------------------------------------
# oauth / static — consumer routes, no Admin sub-folder
# ---------------------------------------------------------------------------


def test_oauth_datapoint_included_no_admin_folder(oauth_partner):
    col = build_postman_collection([oauth_partner])
    dp_folder = col["item"][0]["item"][0]
    item_names = [i["name"] for i in dp_folder["item"]]
    assert "POST /oauth/token" in item_names
    assert "Admin" not in item_names


def test_static_datapoint_included_no_admin_folder(static_partner):
    col = build_postman_collection([static_partner])
    dp_folder = col["item"][0]["item"][0]
    item_names = [i["name"] for i in dp_folder["item"]]
    assert "Admin" not in item_names


# ---------------------------------------------------------------------------
# Admin sub-folder — fetch and async (4 requests)
# ---------------------------------------------------------------------------


def test_fetch_datapoint_has_admin_subfolder(fetch_partner):
    col = build_postman_collection([fetch_partner])
    dp_folder = col["item"][0]["item"][0]
    admin = next(i for i in dp_folder["item"] if i["name"] == "Admin")
    assert admin is not None


def test_fetch_admin_subfolder_has_4_requests(fetch_partner):
    col = build_postman_collection([fetch_partner])
    dp_folder = col["item"][0]["item"][0]
    admin = next(i for i in dp_folder["item"] if i["name"] == "Admin")
    assert len(admin["item"]) == 4


def test_async_datapoint_has_admin_subfolder_with_4_requests(async_partner):
    col = build_postman_collection([async_partner])
    dp_folder = col["item"][0]["item"][0]
    admin = next(i for i in dp_folder["item"] if i["name"] == "Admin")
    assert len(admin["item"]) == 4


def test_admin_subfolder_request_names_and_methods(fetch_partner):
    col = build_postman_collection([fetch_partner])
    dp_folder = col["item"][0]["item"][0]
    admin = next(i for i in dp_folder["item"] if i["name"] == "Admin")
    method_names = [(i["request"]["method"], i["name"]) for i in admin["item"]]
    base = "/imnot/admin/staylink/charges/payload"
    assert ("POST", f"POST {base}") in method_names
    assert ("GET", f"GET {base}") in method_names
    assert ("POST", f"POST {base}/session") in method_names
    assert ("GET", f"GET {base}/session/:session_id") in method_names


# ---------------------------------------------------------------------------
# Push — Admin sub-folder (5 requests) and consumer pre-filling
# ---------------------------------------------------------------------------


def test_push_admin_subfolder_has_5_requests(push_field_partner):
    col = build_postman_collection([push_field_partner])
    dp_folder = col["item"][0]["item"][0]
    admin = next(i for i in dp_folder["item"] if i["name"] == "Admin")
    assert len(admin["item"]) == 5


def test_push_admin_subfolder_includes_retrigger(push_field_partner):
    col = build_postman_collection([push_field_partner])
    dp_folder = col["item"][0]["item"][0]
    admin = next(i for i in dp_folder["item"] if i["name"] == "Admin")
    names = [i["name"] for i in admin["item"]]
    assert any("retrigger" in n for n in names)


def test_push_callback_url_field_prefills_body(push_field_partner):
    col = build_postman_collection([push_field_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    assert "body" in consumer["request"]
    body_dict = json.loads(consumer["request"]["body"]["raw"])
    assert "callbackUrl" in body_dict
    assert body_dict["callbackUrl"] == "http://your-service/webhook"


def test_push_callback_url_header_prefills_header(push_header_partner):
    col = build_postman_collection([push_header_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    headers = {h["key"]: h["value"] for h in consumer["request"]["header"]}
    assert "X-Callback-URL" in headers
    assert headers["X-Callback-URL"] == "http://your-service/webhook"


def test_push_callback_url_header_has_no_body(push_header_partner):
    col = build_postman_collection([push_header_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    assert "body" not in consumer["request"]


# ---------------------------------------------------------------------------
# X-Imnot-Session header
# ---------------------------------------------------------------------------


def test_session_header_present_and_disabled_on_fetch(fetch_partner):
    col = build_postman_collection([fetch_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    session_headers = [h for h in consumer["request"]["header"] if h["key"] == "X-Imnot-Session"]
    assert len(session_headers) == 1
    assert session_headers[0].get("disabled") is True


def test_session_header_present_on_async(async_partner):
    col = build_postman_collection([async_partner])
    # step 1 consumer endpoint
    consumer = col["item"][0]["item"][0]["item"][0]
    session_headers = [h for h in consumer["request"]["header"] if h["key"] == "X-Imnot-Session"]
    assert len(session_headers) == 1
    assert session_headers[0].get("disabled") is True


def test_session_header_present_on_push(push_field_partner):
    col = build_postman_collection([push_field_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    session_headers = [h for h in consumer["request"]["header"] if h["key"] == "X-Imnot-Session"]
    assert len(session_headers) == 1
    assert session_headers[0].get("disabled") is True


def test_session_header_absent_on_oauth(oauth_partner):
    col = build_postman_collection([oauth_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    session_headers = [h for h in consumer["request"]["header"] if h["key"] == "X-Imnot-Session"]
    assert len(session_headers) == 0


def test_session_header_absent_on_static(static_partner):
    col = build_postman_collection([static_partner])
    consumer = col["item"][0]["item"][0]["item"][0]
    session_headers = [h for h in consumer["request"]["header"] if h["key"] == "X-Imnot-Session"]
    assert len(session_headers) == 0


# ---------------------------------------------------------------------------
# URL path variable conversion
# ---------------------------------------------------------------------------


def test_path_param_converted_to_colon_style():
    ep = _ep("GET", "/partner/resources/{id}")
    col = build_postman_collection([_partner("p", [_dp("d", "fetch", [ep])])])
    consumer = col["item"][0]["item"][0]["item"][0]
    url = consumer["request"]["url"]
    assert ":id" in url["raw"]
    assert "{id}" not in url["raw"]


def test_path_param_added_to_variable_array():
    ep = _ep("GET", "/partner/resources/{id}")
    col = build_postman_collection([_partner("p", [_dp("d", "fetch", [ep])])])
    url = col["item"][0]["item"][0]["item"][0]["request"]["url"]
    assert "variable" in url
    keys = [v["key"] for v in url["variable"]]
    assert "id" in keys


def test_no_variable_array_when_no_path_params(fetch_partner):
    col = build_postman_collection([fetch_partner])
    url = col["item"][0]["item"][0]["item"][0]["request"]["url"]
    assert "variable" not in url


# ---------------------------------------------------------------------------
# collection_stats
# ---------------------------------------------------------------------------


def test_collection_stats_counts(fetch_partner, oauth_partner):
    stats = collection_stats([fetch_partner, oauth_partner])
    assert stats["partners"] == 2
    assert "staylink" in stats["partner_names"]
    assert "idp" in stats["partner_names"]
    # fetch: 1 consumer + 4 admin
    # oauth: 1 consumer + 0 admin
    assert stats["consumer_requests"] == 2
    assert stats["admin_requests"] == 4
    assert stats["total_requests"] == 6


def test_collection_stats_push_counts_5_admin(push_field_partner):
    stats = collection_stats([push_field_partner])
    assert stats["admin_requests"] == 5


# ---------------------------------------------------------------------------
# CLI: imnot export postman
# ---------------------------------------------------------------------------


PARTNERS_DIR = Path(__file__).parent.parent / "partners"


@pytest.fixture
def runner():
    return CliRunner()


def test_export_postman_writes_file(runner, tmp_path):
    out = tmp_path / "collection.json"
    result = runner.invoke(cli, [
        "export", "postman",
        "--partners-dir", str(PARTNERS_DIR),
        "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["info"]["name"] == "imnot"


def test_export_postman_default_filename(runner, tmp_path):
    """--out defaults to imnot-collection.json in CWD."""
    result = runner.invoke(cli, [
        "export", "postman",
        "--partners-dir", str(PARTNERS_DIR),
    ], catch_exceptions=False)
    # CliRunner runs in a temp isolated filesystem only if we use mix_stderr / with fs_root —
    # just verify the command parsed correctly and no SystemExit(1)
    assert result.exit_code == 0, result.output


def test_export_postman_summary_output(runner, tmp_path):
    out = tmp_path / "collection.json"
    result = runner.invoke(cli, [
        "export", "postman",
        "--partners-dir", str(PARTNERS_DIR),
        "--out", str(out),
    ])
    assert "Collection written to" in result.output
    assert "Partners" in result.output
    assert "Requests" in result.output


def test_export_postman_invalid_partners_dir(runner, tmp_path):
    result = runner.invoke(cli, [
        "export", "postman",
        "--partners-dir", str(tmp_path / "nonexistent"),
        "--out", str(tmp_path / "out.json"),
    ])
    assert result.exit_code != 0


def test_export_postman_single_partner_filter(runner, tmp_path):
    """--partner filters the collection to just that partner."""
    out = tmp_path / "collection.json"
    # PARTNERS_DIR has staylink and bookingco
    result = runner.invoke(cli, [
        "export", "postman",
        "--partners-dir", str(PARTNERS_DIR),
        "--out", str(out),
        "--partner", "staylink",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    folder_names = [item["name"] for item in data["item"]]
    assert folder_names == ["staylink"]


def test_export_postman_multiple_partner_filter(runner, tmp_path):
    """Multiple --partner flags are all included."""
    out = tmp_path / "collection.json"
    result = runner.invoke(cli, [
        "export", "postman",
        "--partners-dir", str(PARTNERS_DIR),
        "--out", str(out),
        "--partner", "staylink",
        "--partner", "bookingco",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    folder_names = {item["name"] for item in data["item"]}
    assert "staylink" in folder_names
    assert "bookingco" in folder_names


def test_export_postman_unknown_partner_exits_nonzero(runner, tmp_path):
    """--partner with an unknown name exits non-zero with a helpful error."""
    out = tmp_path / "collection.json"
    result = runner.invoke(cli, [
        "export", "postman",
        "--partners-dir", str(PARTNERS_DIR),
        "--out", str(out),
        "--partner", "doesnotexist",
    ])
    assert result.exit_code != 0
    assert "doesnotexist" in result.output


# ---------------------------------------------------------------------------
# Admin endpoint: GET /imnot/admin/postman
# ---------------------------------------------------------------------------


@pytest.fixture
def http_client(tmp_path):
    store = SessionStore(db_path=tmp_path / "test.db")
    store.init()
    app = FastAPI()
    partners = load_partners(PARTNERS_DIR)
    register_routes(app, partners, store, partners_dir=PARTNERS_DIR)
    client = TestClient(app)
    yield client
    store.close()


def test_admin_postman_returns_200(http_client):
    resp = http_client.get("/imnot/admin/postman")
    assert resp.status_code == 200


def test_admin_postman_returns_valid_collection(http_client):
    resp = http_client.get("/imnot/admin/postman")
    data = resp.json()
    assert data["info"]["name"] == "imnot"
    assert "v2.1.0" in data["info"]["schema"]
    assert isinstance(data["item"], list)
    assert len(data["item"]) > 0


def test_admin_postman_content_type_is_json(http_client):
    resp = http_client.get("/imnot/admin/postman")
    assert "application/json" in resp.headers["content-type"]
