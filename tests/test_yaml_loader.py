"""Tests for the YAML loader."""

from pathlib import Path

import pytest

from imnot.loader.yaml_loader import (
    DatapointDef,
    EndpointDef,
    PartnerDef,
    load_partners,
    parse_partner_yaml,
)

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


# ---------------------------------------------------------------------------
# Happy path: real StayLink YAML
# ---------------------------------------------------------------------------


def test_load_staylink_partner():
    partners = load_partners(PARTNERS_DIR)
    staylink = next((p for p in partners if p.partner == "staylink"), None)
    assert staylink is not None
    assert isinstance(staylink, PartnerDef)
    assert len(staylink.datapoints) == 2


def test_staylink_token_datapoint():
    staylink = next(p for p in load_partners(PARTNERS_DIR) if p.partner == "staylink")
    token = next(dp for dp in staylink.datapoints if dp.name == "token")

    assert isinstance(token, DatapointDef)
    assert token.pattern == "oauth"
    assert len(token.endpoints) == 1

    ep = token.endpoints[0]
    assert isinstance(ep, EndpointDef)
    assert ep.method == "POST"
    assert ep.path == "/oauth/token"
    assert ep.step is None
    assert ep.response["status"] == 200
    assert ep.response["token_type"] == "Bearer"


def test_staylink_report_datapoint():
    staylink = next(p for p in load_partners(PARTNERS_DIR) if p.partner == "staylink")
    report = next(dp for dp in staylink.datapoints if dp.name == "report")

    assert report.pattern == "polling"
    assert len(report.endpoints) == 3

    steps = {ep.step: ep for ep in report.endpoints}
    assert set(steps.keys()) == {1, 2, 3}

    assert steps[1].method == "POST"
    assert steps[1].response["status"] == 202
    assert steps[1].response["generates_id"] is True
    assert steps[1].response["id_header"] == "Location"
    assert steps[1].response["id_header_value"] == "/staylink/reports/{id}"

    assert steps[2].method == "HEAD"
    assert steps[2].response["status"] == 201
    assert steps[2].response["headers"]["Status"] == "COMPLETED"

    assert steps[3].method == "GET"
    assert steps[3].response["status"] == 200
    assert steps[3].response["returns_payload"] is True


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_missing_partners_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_partners(tmp_path / "nonexistent")


def test_empty_partners_dir(tmp_path):
    result = load_partners(tmp_path)
    assert result == []


def test_missing_partner_key(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "partner.yaml").write_text("description: oops\ndatapoints: []\n")
    # Bad file is skipped, empty list returned
    result = load_partners(tmp_path)
    assert result == []


def test_unsupported_pattern(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "partner.yaml").write_text(
        "partner: bad\n"
        "datapoints:\n"
        "  - name: foo\n"
        "    pattern: unknown\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /foo\n"
    )
    result = load_partners(tmp_path)
    assert result == []


def test_polling_pattern_is_valid(tmp_path):
    partner_dir = tmp_path / "testpartner"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: testpartner\n"
        "datapoints:\n"
        "  - name: job\n"
        "    pattern: polling\n"
        "    endpoints:\n"
        "      - step: 1\n"
        "        method: POST\n"
        "        path: /jobs\n"
        "        response:\n"
        "          status: 202\n"
        "          generates_id: true\n"
        "          id_header: Location\n"
        "          id_header_value: /jobs/{id}\n"
    )
    result = load_partners(tmp_path)
    assert len(result) == 1
    assert result[0].datapoints[0].pattern == "polling"


# ---------------------------------------------------------------------------
# paginated pattern
# ---------------------------------------------------------------------------

_VALID_PAGINATED_YAML = (
    "partner: ratesync\n"
    "datapoints:\n"
    "  - name: listing\n"
    "    pattern: paginated\n"
    "    endpoints:\n"
    "      - method: GET\n"
    "        path: /ratesync/listings\n"
    "        response:\n"
    "          status: 200\n"
    "    pagination:\n"
    "      style: offset_limit\n"
    "      items_field: results\n"
    "      total_field: total\n"
    "      has_more_field: hasMore\n"
    "      next_offset_field: nextOffset\n"
)


def test_paginated_pattern_is_valid(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(_VALID_PAGINATED_YAML)
    result = load_partners(tmp_path)
    assert len(result) == 1
    dp = result[0].datapoints[0]
    assert dp.pattern == "paginated"
    assert dp.pagination is not None
    assert dp.pagination["style"] == "offset_limit"
    assert dp.pagination["items_field"] == "results"
    assert dp.pagination["total_field"] == "total"
    assert dp.pagination["has_more_field"] == "hasMore"
    assert dp.pagination["next_offset_field"] == "nextOffset"


def test_paginated_offset_echo_fields_valid(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: offset_limit\n"
        "      items_field: results\n"
        "      total_field: count\n"
        "      offset_echo_field: offset\n"
        "      limit_echo_field: limit\n"
    )
    result = load_partners(tmp_path)
    assert len(result) == 1
    dp = result[0].datapoints[0]
    assert dp.pagination["offset_echo_field"] == "offset"
    assert dp.pagination["limit_echo_field"] == "limit"


def test_paginated_missing_style(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      items_field: results\n"
    )
    result = load_partners(tmp_path)
    assert result == []


def test_paginated_unknown_style(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: graphql\n"
        "      items_field: results\n"
    )
    result = load_partners(tmp_path)
    assert result == []


def test_paginated_cursor_style_valid(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: cursor\n"
        "      items_field: results\n"
        "      cursor_field: nextCursor\n"
        "      cursor_ttl_seconds: 1800\n"
    )
    result = load_partners(tmp_path)
    assert len(result) == 1
    dp = result[0].datapoints[0]
    assert dp.pagination["style"] == "cursor"
    assert dp.pagination["cursor_field"] == "nextCursor"
    assert dp.pagination["cursor_ttl_seconds"] == 1800


def test_paginated_cursor_missing_cursor_field(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: cursor\n"
        "      items_field: results\n"
    )
    result = load_partners(tmp_path)
    assert result == []


def test_paginated_page_number_style_valid(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: page_number\n"
        "      items_field: results\n"
    )
    result = load_partners(tmp_path)
    assert len(result) == 1
    dp = result[0].datapoints[0]
    assert dp.pagination["style"] == "page_number"
    assert dp.pagination["items_field"] == "results"


def test_paginated_page_number_custom_params(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: page_number\n"
        "      items_field: data\n"
        "      page_param: pageNum\n"
        "      size_param: perPage\n"
    )
    result = load_partners(tmp_path)
    assert len(result) == 1
    dp = result[0].datapoints[0]
    assert dp.pagination["page_param"] == "pageNum"
    assert dp.pagination["size_param"] == "perPage"


def test_paginated_missing_items_field(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: offset_limit\n"
    )
    result = load_partners(tmp_path)
    assert result == []


def test_paginated_missing_pagination_block(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
    )
    result = load_partners(tmp_path)
    assert result == []


def test_paginated_unknown_key_in_pagination_block(tmp_path):
    partner_dir = tmp_path / "ratesync"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: ratesync\n"
        "datapoints:\n"
        "  - name: listing\n"
        "    pattern: paginated\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /ratesync/listings\n"
        "        response:\n"
        "          status: 200\n"
        "    pagination:\n"
        "      style: offset_limit\n"
        "      items_field: results\n"
        "      typo_field: oops\n"
    )
    result = load_partners(tmp_path)
    assert result == []


def test_non_paginated_datapoint_has_none_pagination(tmp_path):
    partner_dir = tmp_path / "bookingco"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: bookingco\n"
        "datapoints:\n"
        "  - name: charges\n"
        "    pattern: fetch\n"
        "    endpoints:\n"
        "      - method: GET\n"
        "        path: /bookingco/charges\n"
        "        response:\n"
        "          status: 200\n"
    )
    result = load_partners(tmp_path)
    assert len(result) == 1
    assert result[0].datapoints[0].pagination is None


# ---------------------------------------------------------------------------
# Trailing slash normalisation
# ---------------------------------------------------------------------------

_TRAILING_SLASH_YAML = """\
partner: ratesync
datapoints:
  - name: rates
    pattern: static
    endpoints:
      - method: GET
        path: /api/v2/rates/
        response:
          status: 200
          body:
            ok: true
"""


def test_trailing_slash_stripped_from_endpoint_path():
    partner = parse_partner_yaml(_TRAILING_SLASH_YAML)
    assert partner.datapoints[0].endpoints[0].path == "/api/v2/rates"


def test_root_path_preserved():
    yaml = """\
partner: ratesync
datapoints:
  - name: root
    pattern: static
    endpoints:
      - method: GET
        path: /
        response:
          status: 200
"""
    partner = parse_partner_yaml(yaml)
    assert partner.datapoints[0].endpoints[0].path == "/"


def test_trailing_slash_endpoint_reachable_without_slash():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from imnot.engine.patterns.static import make_static_handler

    partner = parse_partner_yaml(_TRAILING_SLASH_YAML)
    ep = partner.datapoints[0].endpoints[0]
    configs: dict = {}
    handler = make_static_handler("ratesync", "rates", ep, configs)
    app = FastAPI()
    app.add_api_route(ep.path, handler, methods=["GET"])
    c = TestClient(app, follow_redirects=False)
    r = c.get("/api/v2/rates")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------------------------------------------------------------------------
# validate: block — YAML loader
# ---------------------------------------------------------------------------

_VALIDATE_YAML = """\
partner: bookingco
description: Test partner with validation
datapoints:
  - name: search
    description: Search endpoint
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        validate:
          body:
            query:
              required: true
              type: string
          query:
            limit:
              type: integer
              min: 1
              max: 100
          headers:
            X-Partner-ID:
              required: true
              pattern: "^P-[0-9]+"
        response:
          status: 200
"""

_VALIDATE_UNKNOWN_TOP_KEY_YAML = """\
partner: bookingco
description: Test
datapoints:
  - name: search
    description: Search
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        validate:
          extra_key: {}
        response:
          status: 200
"""

_VALIDATE_UNKNOWN_RULE_ATTR_YAML = """\
partner: bookingco
description: Test
datapoints:
  - name: search
    description: Search
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        validate:
          body:
            name:
              required: true
              unknown_attr: something
        response:
          status: 200
"""

_VALIDATE_UNKNOWN_TYPE_YAML = """\
partner: bookingco
description: Test
datapoints:
  - name: search
    description: Search
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        validate:
          body:
            name:
              type: uuid
        response:
          status: 200
"""

_VALIDATE_ABSENT_YAML = """\
partner: bookingco
description: Test
datapoints:
  - name: search
    description: Search
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        response:
          status: 200
"""


def test_validate_block_valid_structure_parses():
    partner = parse_partner_yaml(_VALIDATE_YAML)
    ep = partner.datapoints[0].endpoints[0]
    assert ep.validate is not None
    assert "body" in ep.validate
    assert "query" in ep.validate
    assert "headers" in ep.validate


def test_validate_block_unknown_top_key_raises():
    with pytest.raises(ValueError, match="unknown key"):
        parse_partner_yaml(_VALIDATE_UNKNOWN_TOP_KEY_YAML)


def test_validate_block_unknown_rule_attr_raises():
    with pytest.raises(ValueError, match="unknown rule attribute"):
        parse_partner_yaml(_VALIDATE_UNKNOWN_RULE_ATTR_YAML)


def test_validate_block_unknown_type_raises():
    with pytest.raises(ValueError, match="unknown type"):
        parse_partner_yaml(_VALIDATE_UNKNOWN_TYPE_YAML)


def test_validate_absent_gives_none():
    partner = parse_partner_yaml(_VALIDATE_ABSENT_YAML)
    ep = partner.datapoints[0].endpoints[0]
    assert ep.validate is None


def test_validate_null_section_is_skipped():
    yaml_text = """\
partner: bookingco
description: Test
datapoints:
  - name: search
    description: Search
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        validate:
          body: null
          query:
            page:
              required: true
        response:
          status: 200
"""
    partner = parse_partner_yaml(yaml_text)
    ep = partner.datapoints[0].endpoints[0]
    assert ep.validate is not None
    assert "query" in ep.validate
    assert ep.validate.get("body") is None


# ---------------------------------------------------------------------------
# validate: block — section value not a dict (L91)
# ---------------------------------------------------------------------------


def test_validate_section_value_not_a_dict_raises():
    yaml_text = """\
partner: bookingco
description: Test
datapoints:
  - name: search
    description: Search
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        validate:
          body: "flat_string_not_a_dict"
        response:
          status: 200
"""
    with pytest.raises(ValueError, match="must be a mapping"):
        parse_partner_yaml(yaml_text)


# ---------------------------------------------------------------------------
# validate: block — rule entry not a dict (L96)
# ---------------------------------------------------------------------------


def test_validate_rule_entry_not_a_dict_raises():
    yaml_text = """\
partner: bookingco
description: Test
datapoints:
  - name: search
    description: Search
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/search
        validate:
          body:
            field: "not-a-dict"
        response:
          status: 200
"""
    with pytest.raises(ValueError, match="rule dict"):
        parse_partner_yaml(yaml_text)


# ---------------------------------------------------------------------------
# endpoint missing method: (L116)
# ---------------------------------------------------------------------------


def test_endpoint_missing_method_raises():
    yaml_text = """\
partner: bookingco
datapoints:
  - name: search
    pattern: fetch
    endpoints:
      - path: /bookingco/search
        response:
          status: 200
"""
    with pytest.raises(ValueError, match="missing 'method'"):
        parse_partner_yaml(yaml_text)


# ---------------------------------------------------------------------------
# endpoint missing path: (L118)
# ---------------------------------------------------------------------------


def test_endpoint_missing_path_raises():
    yaml_text = """\
partner: bookingco
datapoints:
  - name: search
    pattern: fetch
    endpoints:
      - method: GET
        response:
          status: 200
"""
    with pytest.raises(ValueError, match="missing 'path'"):
        parse_partner_yaml(yaml_text)


# ---------------------------------------------------------------------------
# datapoint missing name: (L138)
# ---------------------------------------------------------------------------


def test_datapoint_missing_name_raises():
    yaml_text = """\
partner: bookingco
datapoints:
  - pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/items
        response:
          status: 200
"""
    with pytest.raises(ValueError, match="missing 'name'"):
        parse_partner_yaml(yaml_text)


# ---------------------------------------------------------------------------
# datapoint with no endpoints: (L149)
# ---------------------------------------------------------------------------


def test_datapoint_missing_endpoints_raises():
    yaml_text = """\
partner: bookingco
datapoints:
  - name: search
    pattern: fetch
"""
    with pytest.raises(ValueError, match="no endpoints"):
        parse_partner_yaml(yaml_text)


# ---------------------------------------------------------------------------
# partner with no datapoints: (L198)
# ---------------------------------------------------------------------------


def test_partner_missing_datapoints_raises():
    yaml_text = """\
partner: bookingco
description: No datapoints here
"""
    with pytest.raises(ValueError, match="no datapoints"):
        parse_partner_yaml(yaml_text)
