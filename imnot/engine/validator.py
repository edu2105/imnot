from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


def _validate_field(
    section: str,
    field: str,
    value: Any,
    present: bool,
    rules: dict[str, Any],
    errors: list[str],
) -> None:
    required = rules.get("required", False)
    expected_type = rules.get("type")
    allowed = rules.get("allowed")
    pattern = rules.get("pattern")
    min_val = rules.get("min")
    max_val = rules.get("max")

    if not present:
        if required:
            errors.append(f"{section}.{field}: required")
        return

    typed_value = value
    type_ok = True

    if expected_type is not None:
        if expected_type == "string":
            type_ok = isinstance(value, str)
        elif expected_type == "integer":
            if isinstance(value, bool):
                type_ok = False
            elif isinstance(value, int):
                typed_value = value
            else:
                try:
                    typed_value = int(value)
                except (ValueError, TypeError):
                    type_ok = False
        elif expected_type == "number":
            if isinstance(value, bool):
                type_ok = False
            elif isinstance(value, (int, float)):
                typed_value = value
            else:
                try:
                    typed_value = float(value)
                except (ValueError, TypeError):
                    type_ok = False
        elif expected_type == "boolean":
            if isinstance(value, bool):
                typed_value = value
            elif isinstance(value, str) and value.lower() in ("true", "false"):
                typed_value = value.lower() == "true"
            else:
                type_ok = False
        elif expected_type == "array":
            type_ok = isinstance(value, list)
        elif expected_type == "object":
            type_ok = isinstance(value, dict)

        if not type_ok:
            errors.append(f"{section}.{field}: must be of type {expected_type}")
            return

    if allowed is not None and typed_value not in allowed:
        errors.append(f"{section}.{field}: must be one of {allowed}")

    if pattern is not None and isinstance(typed_value, str):
        if not re.search(pattern, typed_value):
            errors.append(f"{section}.{field}: does not match pattern '{pattern}'")

    if min_val is not None and isinstance(typed_value, (int, float)) and not isinstance(typed_value, bool):
        if typed_value < min_val:
            errors.append(f"{section}.{field}: must be >= {min_val}")

    if max_val is not None and isinstance(typed_value, (int, float)) and not isinstance(typed_value, bool):
        if typed_value > max_val:
            errors.append(f"{section}.{field}: must be <= {max_val}")


def validate_request(
    rules: dict[str, Any],
    body: Any,
    query_params: Mapping[str, str],
    headers: Mapping[str, str],
) -> list[str]:
    errors: list[str] = []

    body_rules: dict[str, Any] = rules.get("body") or {}
    query_rules: dict[str, Any] = rules.get("query") or {}
    header_rules: dict[str, Any] = rules.get("headers") or {}

    body_dict = body if isinstance(body, dict) else {}

    for field, field_rules in body_rules.items():
        present = field in body_dict
        value = body_dict.get(field)
        _validate_field("body", field, value, present, field_rules, errors)

    for field, field_rules in query_rules.items():
        present = field in query_params
        value = query_params.get(field)
        _validate_field("query", field, value, present, field_rules, errors)

    for field, field_rules in header_rules.items():
        present = field in headers
        value = headers.get(field)
        _validate_field("headers", field, value, present, field_rules, errors)

    return errors
