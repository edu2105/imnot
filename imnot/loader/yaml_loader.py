"""
YAML loader: reads and validates partner definition files.

Responsibilities:
- Scan the `partners/` directory for partner.yaml files.
- Parse each file into a structured PartnerDefinition dataclass/model.
- Validate required fields (partner name, base path, datapoints, patterns).
- Return a list of PartnerDefinition objects ready for consumption by the router.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SUPPORTED_PATTERNS = {"oauth", "polling", "callback", "static", "fetch", "paginated"}

_PAGINATION_VALID_KEYS = {
    "style",
    "items_field",
    "total_field",
    "has_more_field",
    "next_offset_field",
    "offset_echo_field",
    "limit_echo_field",
    "cursor_field",
    "cursor_ttl_seconds",
    "page_param",
    "size_param",
    "next_url_field",
    "previous_url_field",
    "total_pages",
}

_VALIDATE_VALID_KEYS = {"body", "query", "headers"}
_RULE_VALID_KEYS = {"required", "type", "allowed", "pattern", "min", "max"}
_VALID_RULE_TYPES = {"string", "integer", "number", "boolean", "array", "object"}

_RATE_LIMIT_VALID_KEYS = {"requests_per_minute"}

# Keys the loader and the pattern handlers actually read. Anything else is almost always a typo
# (``respose:``, ``vaildate:``) that would otherwise be ignored silently. Unknown keys are a
# warning when the server loads partners and an error in ``imnot validate`` / ``generate``.
_PARTNER_KEYS = {"partner", "description", "datapoints"}
_DATAPOINT_KEYS = {"name", "description", "pattern", "endpoints", "pagination"}
_ENDPOINT_KEYS = {"method", "path", "step", "response", "validate", "rate_limit"}
_RESPONSE_KEYS: dict[str, set[str]] = {
    "static": {"status", "body", "headers"},
    "oauth": {"status", "token_type", "expires_in"},
    "fetch": {"status"},
    "paginated": {"status"},
    "callback": {"status", "callback_url_field", "callback_url_header", "callback_method", "callback_delay_seconds"},
    "polling": {
        "status",
        "body",
        "headers",
        "generates_id",
        "id_header",
        "id_header_value",
        "id_body_field",
        "returns_payload",
    },
}
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EndpointDef:
    method: str  # HTTP verb, upper-cased
    path: str  # e.g. /staylink/reservations/{uuid}
    step: int | None  # polling step number (1/2/3); None for oauth/static/fetch
    response: dict[str, Any]  # raw response config from YAML
    validate: dict[str, Any] | None = None  # raw validate block; None when absent
    rate_limit: dict[str, Any] | None = None  # raw rate_limit block; None when absent


@dataclass
class DatapointDef:
    name: str  # e.g. "reservation"
    description: str
    pattern: str  # "oauth" | "polling" | "fetch" | "static" | "callback" | "paginated"
    endpoints: list[EndpointDef]
    pagination: dict[str, Any] | None = None  # raw pagination block; None for non-paginated patterns


@dataclass
class PartnerDef:
    partner: str  # e.g. "staylink"
    description: str
    datapoints: list[DatapointDef]
    source_path: Path  # absolute path to the partner.yaml file
    warnings: list[str] = field(default_factory=list)  # unknown keys found while parsing (see _PARTNER_KEYS)
    # Global payloads seeded from partners/<partner>/payloads/<datapoint>.json, keyed by datapoint name.
    seed_payloads: dict[str, Any] = field(default_factory=dict)


# Patterns whose responses come from an uploaded payload. Single source: router, cli and postman import it.
PAYLOAD_PATTERNS = {"fetch", "polling", "callback", "paginated"}


def load_payload_files(partner: PartnerDef, payloads_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Read ``<payloads_dir>/<datapoint>.json`` files for *partner*.

    Returns ``(payloads, problems)``. A file is skipped (and reported) when its JSON is invalid,
    its name matches no datapoint, the datapoint does not use a payload, or a ``paginated``
    payload is not a JSON array.
    """
    payloads: dict[str, Any] = {}
    problems: list[str] = []
    if not payloads_dir.is_dir():
        return payloads, problems
    by_name = {dp.name: dp for dp in partner.datapoints}
    for path in sorted(payloads_dir.glob("*.json")):
        label = f"payloads/{path.name}"
        dp = by_name.get(path.stem)
        if dp is None:
            problems.append(f"{label}: no datapoint named '{path.stem}' in partner '{partner.partner}'")
            continue
        if dp.pattern not in PAYLOAD_PATTERNS:
            problems.append(f"{label}: datapoint '{dp.name}' uses pattern '{dp.pattern}', which takes no payload")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            problems.append(f"{label}: invalid JSON ({exc})")
            continue
        if dp.pattern == "paginated" and not isinstance(payload, list):
            problems.append(f"{label}: a 'paginated' payload must be a JSON array of items")
            continue
        payloads[dp.name] = payload
    return payloads, problems


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _validate_validate_block(validate: dict[str, Any], path_hint: str) -> None:
    unknown_top = set(validate.keys()) - _VALIDATE_VALID_KEYS
    if unknown_top:
        raise ValueError(
            f"Endpoint {path_hint}: unknown key(s) under 'validate:': {sorted(unknown_top)}. "
            f"Allowed: {sorted(_VALIDATE_VALID_KEYS)}"
        )
    for section in _VALIDATE_VALID_KEYS:
        section_rules = validate.get(section)
        if section_rules is None:
            continue
        if not isinstance(section_rules, dict):
            raise ValueError(
                f"Endpoint {path_hint}: 'validate.{section}' must be a mapping of field names to rule dicts"
            )
        for field_name, field_rules in section_rules.items():
            if not isinstance(field_rules, dict):
                raise ValueError(f"Endpoint {path_hint}: 'validate.{section}.{field_name}' must be a rule dict")
            unknown_rule_keys = set(field_rules.keys()) - _RULE_VALID_KEYS
            if unknown_rule_keys:
                raise ValueError(
                    f"Endpoint {path_hint}: unknown rule attribute(s) for '{section}.{field_name}': "
                    f"{sorted(unknown_rule_keys)}. Allowed: {sorted(_RULE_VALID_KEYS)}"
                )
            rule_type = field_rules.get("type")
            if rule_type is not None and rule_type not in _VALID_RULE_TYPES:
                raise ValueError(
                    f"Endpoint {path_hint}: unknown type '{rule_type}' for '{section}.{field_name}'. "
                    f"Allowed: {sorted(_VALID_RULE_TYPES)}"
                )


def _validate_rate_limit_block(
    rate_limit: dict[str, Any], path_hint: str, pattern: str, pagination: dict[str, Any] | None = None
) -> None:
    allowed = pattern == "fetch" or (
        pattern == "paginated" and pagination is not None and pagination.get("style") == "page_number_url"
    )
    if not allowed:
        raise ValueError(
            f"Endpoint {path_hint}: 'rate_limit:' is declared on a '{pattern}' pattern endpoint, but "
            f"'rate_limit:' is only supported on 'fetch' pattern endpoints, or 'paginated' pattern endpoints "
            f"using pagination.style 'page_number_url', in the current version"
        )

    unknown_top = set(rate_limit.keys()) - _RATE_LIMIT_VALID_KEYS
    if unknown_top:
        raise ValueError(
            f"Endpoint {path_hint}: unknown key(s) under 'rate_limit:': {sorted(unknown_top)}. "
            f"Allowed: {sorted(_RATE_LIMIT_VALID_KEYS)}"
        )

    if "requests_per_minute" not in rate_limit:
        raise ValueError(f"Endpoint {path_hint}: 'rate_limit.requests_per_minute' is required")

    value = rate_limit["requests_per_minute"]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(
            f"Endpoint {path_hint}: 'rate_limit.requests_per_minute' must be a positive integer (got {value!r})"
        )


def _check_unknown_keys(raw: dict[str, Any], known: set[str], where: str, warns: list[str] | None) -> None:
    if warns is None:
        return
    for key in sorted(set(raw) - known, key=str):
        warns.append(f"{where}: unknown key '{key}' (ignored). Known keys: {sorted(known)}")


def _parse_endpoint(
    raw: dict[str, Any],
    pattern: str,
    pagination: dict[str, Any] | None = None,
    warns: list[str] | None = None,
) -> EndpointDef:
    if not isinstance(raw, dict):
        raise ValueError(f"Endpoint must be a mapping, got {raw!r}")
    method = raw.get("method")
    path = raw.get("path")

    if not method:
        raise ValueError(f"Endpoint is missing 'method': {raw}")
    if not path:
        raise ValueError(f"Endpoint is missing 'path': {raw}")
    if not isinstance(method, str) or method.upper() not in _HTTP_METHODS:
        raise ValueError(f"Endpoint {path}: 'method' must be one of {sorted(_HTTP_METHODS)} (got {method!r})")
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(f"Endpoint {method.upper()} {path}: 'path' must start with '/' (got {path!r})")
    where = f"Endpoint {method.upper()} {path}"
    _check_unknown_keys(raw, _ENDPOINT_KEYS, where, warns)

    response = raw.get("response") or {}
    if not isinstance(response, dict):
        raise ValueError(f"{where}: 'response' must be a mapping (got {response!r})")
    status = response.get("status")
    if status is not None and (isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599):
        raise ValueError(f"{where}: 'response.status' must be an HTTP status code between 100 and 599 (got {status!r})")
    _check_unknown_keys(response, _RESPONSE_KEYS[pattern], f"{where} response", warns)
    if pattern == "callback":
        has_field, has_header = bool(response.get("callback_url_field")), bool(response.get("callback_url_header"))
        if has_field == has_header:
            raise ValueError(
                f"{where}: callback needs exactly one of "
                "'response.callback_url_field' or 'response.callback_url_header'"
            )
    if pattern == "polling" and response.get("generates_id"):
        if not (response.get("id_header") and response.get("id_header_value")) and not response.get("id_body_field"):
            raise ValueError(f"{where}: 'generates_id: true' needs 'id_header' + 'id_header_value' or 'id_body_field'")

    raw_validate = raw.get("validate")
    if raw_validate is not None:
        _validate_validate_block(raw_validate, f"{method.upper()} {path}")

    raw_rate_limit = raw.get("rate_limit")
    if raw_rate_limit is not None:
        _validate_rate_limit_block(raw_rate_limit, f"{method.upper()} {path}", pattern, pagination)

    return EndpointDef(
        method=method.upper(),
        path=path.rstrip("/") or "/",
        step=raw.get("step"),  # optional; only polling endpoints carry this
        response=response,
        validate=raw_validate,
        rate_limit=raw_rate_limit,
    )


def _parse_datapoint(raw: dict[str, Any], partner: str, warns: list[str] | None = None) -> DatapointDef:
    if not isinstance(raw, dict):
        raise ValueError(f"Datapoint in partner '{partner}' must be a mapping, got {raw!r}")
    name = raw.get("name")
    pattern = raw.get("pattern")

    if not name:
        raise ValueError(f"Datapoint in partner '{partner}' is missing 'name'")
    if not pattern:
        raise ValueError(f"Datapoint '{name}' in partner '{partner}' is missing 'pattern'")
    if pattern not in SUPPORTED_PATTERNS:
        raise ValueError(
            f"Datapoint '{name}' in partner '{partner}' uses unknown pattern '{pattern}'. "
            f"Supported: {sorted(SUPPORTED_PATTERNS)}"
        )

    raw_endpoints = raw.get("endpoints")
    if not raw_endpoints:
        raise ValueError(f"Datapoint '{name}' in partner '{partner}' has no endpoints")
    if not isinstance(raw_endpoints, list):
        raise ValueError(f"Datapoint '{name}' in partner '{partner}': 'endpoints' must be a list")
    _check_unknown_keys(raw, _DATAPOINT_KEYS, f"Datapoint '{name}' in partner '{partner}'", warns)

    pagination: dict[str, Any] | None = None
    if pattern == "paginated":
        raw_pagination = raw.get("pagination")
        if not raw_pagination:
            raise ValueError(
                f"Datapoint '{name}' in partner '{partner}' with pattern 'paginated' requires a 'pagination:' block"
            )
        unknown_keys = set(raw_pagination.keys()) - _PAGINATION_VALID_KEYS
        if unknown_keys:
            raise ValueError(
                f"Datapoint '{name}' in partner '{partner}': unrecognized key(s) in "
                f"'pagination:' block: {sorted(unknown_keys)}. "
                f"Recognized keys: {sorted(_PAGINATION_VALID_KEYS)}"
            )
        style = raw_pagination.get("style")
        if not style:
            raise ValueError(f"Datapoint '{name}' in partner '{partner}': 'pagination.style' is required")
        _VALID_STYLES = {"offset_limit", "cursor", "page_number", "page_number_url"}
        if style not in _VALID_STYLES:
            raise ValueError(
                f"Datapoint '{name}' in partner '{partner}': 'pagination.style' must be one of "
                f"{sorted(_VALID_STYLES)} (got '{style}')"
            )
        if not raw_pagination.get("items_field"):
            raise ValueError(f"Datapoint '{name}' in partner '{partner}': 'pagination.items_field' is required")
        if style == "cursor" and not raw_pagination.get("cursor_field"):
            raise ValueError(
                f"Datapoint '{name}' in partner '{partner}': 'pagination.cursor_field' is required for style 'cursor'"
            )
        if style == "page_number_url" and (
            not raw_pagination.get("next_url_field") or not raw_pagination.get("previous_url_field")
        ):
            raise ValueError(
                f"Datapoint '{name}' in partner '{partner}': 'pagination.next_url_field' and "
                f"'pagination.previous_url_field' are both required for style 'page_number_url'"
            )
        if "total_pages" in raw_pagination:
            total_pages = raw_pagination["total_pages"]
            if isinstance(total_pages, bool) or not isinstance(total_pages, int) or total_pages <= 0:
                raise ValueError(
                    f"Datapoint '{name}' in partner '{partner}': 'pagination.total_pages' must be a "
                    f"positive integer (got {total_pages!r})"
                )
        pagination = raw_pagination

    return DatapointDef(
        name=name,
        description=raw.get("description", ""),
        pattern=pattern,
        endpoints=[_parse_endpoint(e, pattern, pagination, warns) for e in raw_endpoints],
        pagination=pagination,
    )


def _parse_partner(raw: Any, source_path: Path, strict: bool = False) -> PartnerDef:
    if not isinstance(raw, dict):
        raise ValueError(f"Partner YAML at {source_path} must be a YAML mapping with a 'partner' key")
    partner = raw.get("partner")
    if not partner:
        raise ValueError(f"Partner YAML at {source_path} is missing the 'partner' key")

    raw_datapoints = raw.get("datapoints")
    if not raw_datapoints:
        raise ValueError(f"Partner '{partner}' has no datapoints defined")
    if not isinstance(raw_datapoints, list):
        raise ValueError(f"Partner '{partner}': 'datapoints' must be a list")

    warns: list[str] = []
    _check_unknown_keys(raw, _PARTNER_KEYS, f"Partner '{partner}'", warns)
    datapoints = [_parse_datapoint(dp, partner, warns) for dp in raw_datapoints]
    if strict and warns:
        raise ValueError("; ".join(warns))

    return PartnerDef(
        partner=partner,
        description=raw.get("description", ""),
        datapoints=datapoints,
        source_path=source_path,
        warnings=warns,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_partner_yaml(text: str, source_path: Path = Path("<input>"), strict: bool = False) -> PartnerDef:
    """Parse and validate a partner YAML string.

    With ``strict=True`` unknown keys are errors instead of entries in ``PartnerDef.warnings``.

    Raises:
        yaml.YAMLError: if the text is not valid YAML.
        ValueError: if the parsed content fails schema validation.
    """
    raw = yaml.safe_load(text)
    return _parse_partner(raw, source_path, strict=strict)


def load_partners(partners_dir: Path) -> list[PartnerDef]:
    """Scan *partners_dir* for partner.yaml files and return parsed definitions.

    Each subdirectory of *partners_dir* may contain a ``partner.yaml`` file.
    Files that fail to parse are logged and skipped so a single bad definition
    does not prevent the rest from loading.
    """
    if not partners_dir.is_dir():
        raise FileNotFoundError(f"Partners directory not found: {partners_dir}")

    yaml_files = sorted(partners_dir.glob("*/partner.yaml"))
    if not yaml_files:
        logger.warning("No partner.yaml files found in %s", partners_dir)
        return []

    partners: list[PartnerDef] = []
    for yaml_path in yaml_files:
        try:
            raw = yaml.safe_load(yaml_path.read_text())
            partner = _parse_partner(raw, yaml_path)
            for warning in partner.warnings:
                logger.warning("%s: %s", yaml_path, warning)
            partner.seed_payloads, problems = load_payload_files(partner, yaml_path.parent / "payloads")
            for problem in problems:
                logger.warning("%s: %s (skipped)", yaml_path.parent, problem)
            partners.append(partner)
            logger.info(
                "Loaded partner '%s' with %d datapoint(s) from %s",
                partner.partner,
                len(partner.datapoints),
                yaml_path,
            )
        except (yaml.YAMLError, ValueError) as exc:
            logger.error("Failed to load partner from %s: %s", yaml_path, exc)

    return partners
