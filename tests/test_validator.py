"""Unit tests for imnot.engine.validator."""

from imnot.engine.validator import validate_request


def _no_body():
    return None


def _body(**kwargs):
    return dict(**kwargs)


# ---------------------------------------------------------------------------
# Empty / no-op
# ---------------------------------------------------------------------------


def test_empty_rules_returns_no_errors():
    assert validate_request({}, {}, {}, {}) == []


def test_no_declared_sections_returns_no_errors():
    assert validate_request({}, {"foo": "bar"}, {"q": "1"}, {"X-Header": "v"}) == []


# ---------------------------------------------------------------------------
# body — required
# ---------------------------------------------------------------------------


def test_body_required_field_present_passes():
    rules = {"body": {"name": {"required": True}}}
    errors = validate_request(rules, {"name": "Alice"}, {}, {})
    assert errors == []


def test_body_required_field_missing_returns_error():
    rules = {"body": {"name": {"required": True}}}
    errors = validate_request(rules, {}, {}, {})
    assert len(errors) == 1
    assert "body.name" in errors[0]
    assert "required" in errors[0]


def test_body_optional_field_missing_passes():
    rules = {"body": {"name": {"required": False}}}
    errors = validate_request(rules, {}, {}, {})
    assert errors == []


def test_body_not_a_dict_fires_required_error():
    rules = {"body": {"name": {"required": True}}}
    errors = validate_request(rules, "not-a-dict", {}, {})
    assert any("body.name" in e and "required" in e for e in errors)


# ---------------------------------------------------------------------------
# query — required
# ---------------------------------------------------------------------------


def test_query_required_field_present_passes():
    rules = {"query": {"limit": {"required": True}}}
    errors = validate_request(rules, None, {"limit": "10"}, {})
    assert errors == []


def test_query_required_field_missing_returns_error():
    rules = {"query": {"limit": {"required": True}}}
    errors = validate_request(rules, None, {}, {})
    assert len(errors) == 1
    assert "query.limit" in errors[0]
    assert "required" in errors[0]


# ---------------------------------------------------------------------------
# headers — required
# ---------------------------------------------------------------------------


def test_header_required_field_present_passes():
    rules = {"headers": {"X-Partner-ID": {"required": True}}}
    errors = validate_request(rules, None, {}, {"X-Partner-ID": "P-123"})
    assert errors == []


def test_header_required_field_missing_returns_error():
    rules = {"headers": {"X-Partner-ID": {"required": True}}}
    errors = validate_request(rules, None, {}, {})
    assert len(errors) == 1
    assert "headers.X-Partner-ID" in errors[0]
    assert "required" in errors[0]


# ---------------------------------------------------------------------------
# type checks — body
# ---------------------------------------------------------------------------


def test_body_correct_type_string_passes():
    rules = {"body": {"name": {"type": "string"}}}
    errors = validate_request(rules, {"name": "Alice"}, {}, {})
    assert errors == []


def test_body_wrong_type_integer_given_string_returns_error():
    rules = {"body": {"count": {"type": "integer"}}}
    errors = validate_request(rules, {"count": "not-an-int"}, {}, {})
    assert len(errors) == 1
    assert "body.count" in errors[0]
    assert "integer" in errors[0]


def test_body_correct_type_integer_passes():
    rules = {"body": {"count": {"type": "integer"}}}
    errors = validate_request(rules, {"count": 5}, {}, {})
    assert errors == []


def test_body_boolean_rejected_as_integer():
    rules = {"body": {"count": {"type": "integer"}}}
    errors = validate_request(rules, {"count": True}, {}, {})
    assert len(errors) == 1


def test_body_type_array_correct_passes():
    rules = {"body": {"items": {"type": "array"}}}
    errors = validate_request(rules, {"items": [1, 2, 3]}, {}, {})
    assert errors == []


def test_body_type_array_wrong_returns_error():
    rules = {"body": {"items": {"type": "array"}}}
    errors = validate_request(rules, {"items": "not-a-list"}, {}, {})
    assert len(errors) == 1


def test_body_type_object_correct_passes():
    rules = {"body": {"meta": {"type": "object"}}}
    errors = validate_request(rules, {"meta": {"k": "v"}}, {}, {})
    assert errors == []


def test_body_type_number_float_passes():
    rules = {"body": {"price": {"type": "number"}}}
    errors = validate_request(rules, {"price": 9.99}, {}, {})
    assert errors == []


def test_body_type_boolean_correct_passes():
    rules = {"body": {"active": {"type": "boolean"}}}
    errors = validate_request(rules, {"active": True}, {}, {})
    assert errors == []


def test_body_type_boolean_wrong_returns_error():
    rules = {"body": {"active": {"type": "boolean"}}}
    errors = validate_request(rules, {"active": "yes"}, {}, {})
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# allowed
# ---------------------------------------------------------------------------


def test_body_value_in_allowed_list_passes():
    rules = {"body": {"status": {"allowed": ["pending", "active"]}}}
    errors = validate_request(rules, {"status": "active"}, {}, {})
    assert errors == []


def test_body_value_not_in_allowed_list_returns_error():
    rules = {"body": {"status": {"allowed": ["pending", "active"]}}}
    errors = validate_request(rules, {"status": "unknown"}, {}, {})
    assert len(errors) == 1
    assert "must be one of" in errors[0]


def test_query_allowed_list_passes():
    rules = {"query": {"limit": {"allowed": ["10", "50", "100"]}}}
    errors = validate_request(rules, None, {"limit": "50"}, {})
    assert errors == []


def test_query_allowed_list_fails():
    rules = {"query": {"limit": {"allowed": ["10", "50", "100"]}}}
    errors = validate_request(rules, None, {"limit": "999"}, {})
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# pattern
# ---------------------------------------------------------------------------


def test_body_string_matches_pattern_passes():
    rules = {"body": {"code": {"pattern": "^[A-Z]{3}$"}}}
    errors = validate_request(rules, {"code": "ABC"}, {}, {})
    assert errors == []


def test_body_string_not_matching_pattern_returns_error():
    rules = {"body": {"code": {"pattern": "^[A-Z]{3}$"}}}
    errors = validate_request(rules, {"code": "abc"}, {}, {})
    assert len(errors) == 1
    assert "does not match pattern" in errors[0]


def test_header_pattern_check():
    rules = {"headers": {"X-Partner-ID": {"pattern": "^P-[0-9]+"}}}
    errors = validate_request(rules, None, {}, {"X-Partner-ID": "X-999"})
    assert len(errors) == 1
    assert "does not match pattern" in errors[0]


def test_pattern_skipped_on_non_string_after_type_error():
    rules = {"body": {"val": {"type": "integer", "pattern": "^[0-9]+$"}}}
    errors = validate_request(rules, {"val": "not-int"}, {}, {})
    assert len(errors) == 1
    assert "integer" in errors[0]


# ---------------------------------------------------------------------------
# min / max
# ---------------------------------------------------------------------------


def test_body_numeric_below_min_returns_error():
    rules = {"body": {"age": {"type": "integer", "min": 18}}}
    errors = validate_request(rules, {"age": 10}, {}, {})
    assert len(errors) == 1
    assert ">=" in errors[0]


def test_body_numeric_above_max_returns_error():
    rules = {"body": {"age": {"type": "integer", "max": 120}}}
    errors = validate_request(rules, {"age": 200}, {}, {})
    assert len(errors) == 1
    assert "<=" in errors[0]


def test_body_numeric_within_range_passes():
    rules = {"body": {"age": {"type": "integer", "min": 18, "max": 120}}}
    errors = validate_request(rules, {"age": 25}, {}, {})
    assert errors == []


def test_query_integer_coercion_with_min_max():
    rules = {"query": {"page": {"type": "integer", "min": 1, "max": 100}}}
    errors = validate_request(rules, None, {"page": "5"}, {})
    assert errors == []


def test_query_integer_coercion_below_min():
    rules = {"query": {"page": {"type": "integer", "min": 1}}}
    errors = validate_request(rules, None, {"page": "0"}, {})
    assert len(errors) == 1
    assert ">=" in errors[0]


# ---------------------------------------------------------------------------
# Multiple violations — non-short-circuit
# ---------------------------------------------------------------------------


def test_multiple_violations_all_collected():
    rules = {
        "body": {
            "name": {"required": True},
            "age": {"required": True},
        },
        "query": {"limit": {"required": True}},
    }
    errors = validate_request(rules, {}, {}, {})
    assert len(errors) == 3


# ---------------------------------------------------------------------------
# type fails → skip remaining rules for that field
# ---------------------------------------------------------------------------


def test_type_fail_skips_min_max():
    rules = {"body": {"count": {"type": "integer", "min": 1, "max": 100}}}
    errors = validate_request(rules, {"count": "bad"}, {}, {})
    assert len(errors) == 1
    assert "integer" in errors[0]


# ---------------------------------------------------------------------------
# type: number — string coercion (L44-53)
# ---------------------------------------------------------------------------


def test_body_type_number_string_coerced_via_float_passes():
    rules = {"body": {"price": {"type": "number"}}}
    errors = validate_request(rules, {"price": "3.14"}, {}, {})
    assert errors == []


def test_body_type_number_non_numeric_string_returns_error():
    rules = {"body": {"price": {"type": "number"}}}
    errors = validate_request(rules, {"price": "abc"}, {}, {})
    assert len(errors) == 1
    assert "number" in errors[0]


def test_body_type_number_boolean_rejected():
    rules = {"body": {"price": {"type": "number"}}}
    errors = validate_request(rules, {"price": True}, {}, {})
    assert len(errors) == 1
    assert "number" in errors[0]


# ---------------------------------------------------------------------------
# type: boolean — string coercion (L54-60)
# ---------------------------------------------------------------------------


def test_body_type_boolean_string_true_coerced():
    rules = {"body": {"active": {"type": "boolean"}}}
    errors = validate_request(rules, {"active": "true"}, {}, {})
    assert errors == []


def test_body_type_boolean_string_false_coerced():
    rules = {"body": {"active": {"type": "boolean"}}}
    errors = validate_request(rules, {"active": "false"}, {}, {})
    assert errors == []


def test_body_type_boolean_string_yes_returns_error():
    rules = {"body": {"active": {"type": "boolean"}}}
    errors = validate_request(rules, {"active": "yes"}, {}, {})
    assert len(errors) == 1
    assert "boolean" in errors[0]
