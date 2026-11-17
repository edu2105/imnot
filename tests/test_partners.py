"""Unit tests for imnot.partners.register_partner."""

import pytest
import yaml

from imnot.partners import register_partner

VALID_YAML = """\
partner: staylink
description: StayLink reservation API

datapoints:
  - name: reservation
    description: Fetch a reservation
    pattern: fetch
    endpoints:
      - method: GET
        path: /staylink/v1/reservations/{id}
        response:
          status: 200
"""

VALID_YAML_STATIC = """\
partner: bookingco
description: BookingCo static mock

datapoints:
  - name: status
    description: Service status
    pattern: static
    endpoints:
      - method: GET
        path: /bookingco/status
        response:
          status: 200
          body:
            ok: true
"""

INVALID_YAML_SYNTAX = """\
partner: broken
  this is: [not valid yaml
"""

INVALID_YAML_MISSING_PATTERN = """\
partner: badpartner
description: Missing pattern field

datapoints:
  - name: broken
    description: No pattern here
    endpoints:
      - method: GET
        path: /bad/endpoint
        response:
          status: 200
"""


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_creates_partner_dir_and_file(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    result = register_partner(VALID_YAML, partners_dir)

    dest = partners_dir / "staylink" / "partner.yaml"
    assert dest.exists()
    assert dest.read_text() == VALID_YAML
    assert result.created is True
    assert result.dest_file == dest
    assert result.partner.partner == "staylink"


def test_creates_partners_dir_if_missing(tmp_path):
    partners_dir = tmp_path / "partners"
    # Do NOT pre-create partners_dir — register_partner should create the subdir
    partners_dir.mkdir()

    result = register_partner(VALID_YAML, partners_dir)

    assert (partners_dir / "staylink" / "partner.yaml").exists()
    assert result.created is True


def test_force_overwrites_existing(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    register_partner(VALID_YAML, partners_dir)
    updated_yaml = VALID_YAML.replace("StayLink reservation API", "StayLink v2")
    result = register_partner(updated_yaml, partners_dir, force=True)

    dest = partners_dir / "staylink" / "partner.yaml"
    assert dest.read_text() == updated_yaml
    assert result.created is False


def test_dry_run_writes_nothing(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    result = register_partner(VALID_YAML, partners_dir, dry_run=True)

    assert not (partners_dir / "staylink").exists()
    assert result.created is False
    assert result.partner.partner == "staylink"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_raises_file_exists_error_without_force(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    register_partner(VALID_YAML, partners_dir)

    with pytest.raises(FileExistsError, match="already exists"):
        register_partner(VALID_YAML, partners_dir)


def test_raises_on_invalid_yaml_syntax(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    with pytest.raises(yaml.YAMLError):
        register_partner(INVALID_YAML_SYNTAX, partners_dir)


def test_raises_on_invalid_yaml_schema(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    with pytest.raises(ValueError):
        register_partner(INVALID_YAML_MISSING_PATTERN, partners_dir)


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


def test_result_contains_partner_def(tmp_path):
    partners_dir = tmp_path / "partners"
    partners_dir.mkdir()

    result = register_partner(VALID_YAML, partners_dir)

    assert result.partner.description == "StayLink reservation API"
    assert len(result.partner.datapoints) == 1
    assert result.partner.datapoints[0].pattern == "fetch"


# ---------------------------------------------------------------------------
# dropped_fields — Builder edit-mode guard
# ---------------------------------------------------------------------------

_HAND_WRITTEN = """\
partner: bookingco
description: BookingCo
datapoints:
  - name: reservation
    description: Fixed reservation
    pattern: static
    endpoints:
      - method: GET
        path: /bookingco/v1/reservation
        validate:
          query:
            id: {required: true}
        response:
          status: 200
          headers: {X-Version: "2"}
          body:
            reservationId: RES-001
            nights: 2
  - name: charges
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/v1/charges
        response:
          status: 200
"""

_BUILDER_OUTPUT = """\
partner: bookingco
description: BookingCo
datapoints:
  - name: reservation
    pattern: static
    endpoints:
      - method: GET
        path: /bookingco/v1/reservation
        response:
          status: 200
          body: {}
  - name: charges
    pattern: fetch
    endpoints:
      - method: GET
        path: /bookingco/v1/charges
        response:
          status: 200
"""


def test_dropped_fields_lists_what_the_builder_would_lose():
    from imnot.partners import dropped_fields

    assert dropped_fields(_HAND_WRITTEN, _BUILDER_OUTPUT) == [
        "datapoints[reservation].description",
        "datapoints[reservation].endpoints[GET /bookingco/v1/reservation].validate",
        "datapoints[reservation].endpoints[GET /bookingco/v1/reservation].response.headers",
        "datapoints[reservation].endpoints[GET /bookingco/v1/reservation].response.body.reservationId",
        "datapoints[reservation].endpoints[GET /bookingco/v1/reservation].response.body.nights",
    ]


def test_dropped_fields_ignores_changed_values_and_removed_datapoints():
    from imnot.partners import dropped_fields

    edited = _HAND_WRITTEN.replace("status: 200", "status: 201").replace("description: BookingCo\n", "description: X\n")
    without_charges = _HAND_WRITTEN.split("  - name: charges")[0]

    assert dropped_fields(_HAND_WRITTEN, edited) == []
    assert dropped_fields(_HAND_WRITTEN, without_charges) == []


def test_dropped_fields_matches_endpoints_by_position_when_the_path_changes():
    from imnot.partners import dropped_fields

    moved = _HAND_WRITTEN.replace("/bookingco/v1/reservation\n", "/bookingco/v2/reservation\n")
    moved_and_stripped = moved.replace("        validate:\n          query:\n            id: {required: true}\n", "")

    assert dropped_fields(_HAND_WRITTEN, moved_and_stripped) == [
        "datapoints[reservation].endpoints[GET /bookingco/v1/reservation].validate"
    ]


def test_dropped_fields_with_unparseable_old_file_reports_nothing():
    from imnot.partners import dropped_fields

    assert dropped_fields("", _BUILDER_OUTPUT) == []
