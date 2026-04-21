"""Tests for the YAML loader."""

from pathlib import Path

import pytest

from imnot.loader.yaml_loader import (
    DatapointDef,
    EndpointDef,
    PartnerDef,
    load_partners,
)

PARTNERS_DIR = Path(__file__).parent.parent / "partners"


# ---------------------------------------------------------------------------
# Happy path: real OHIP YAML
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


def test_staylink_reservation_datapoint():
    staylink = next(p for p in load_partners(PARTNERS_DIR) if p.partner == "staylink")
    reservation = next(dp for dp in staylink.datapoints if dp.name == "reservation")

    assert reservation.pattern == "async"
    assert len(reservation.endpoints) == 3

    steps = {ep.step: ep for ep in reservation.endpoints}
    assert set(steps.keys()) == {1, 2, 3}

    assert steps[1].method == "POST"
    assert steps[1].response["status"] == 202
    assert steps[1].response["generates_id"] is True
    assert steps[1].response["id_header"] == "Location"
    assert steps[1].response["id_header_value"] == "/staylink/reservations/{id}"

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


def test_async_pattern_is_valid(tmp_path):
    partner_dir = tmp_path / "testpartner"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: testpartner\n"
        "datapoints:\n"
        "  - name: job\n"
        "    pattern: async\n"
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
    assert result[0].datapoints[0].pattern == "async"


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
        "      style: cursor\n"
        "      items_field: results\n"
    )
    result = load_partners(tmp_path)
    assert result == []


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
