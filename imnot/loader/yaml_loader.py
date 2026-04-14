"""
YAML loader: reads and validates partner definition files.

Responsibilities:
- Scan the `partners/` directory for partner.yaml files.
- Parse each file into a structured PartnerDefinition dataclass/model.
- Validate required fields (partner name, base path, datapoints, patterns).
- Return a list of PartnerDefinition objects ready for consumption by the router.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SUPPORTED_PATTERNS = {"oauth", "async", "push", "static", "fetch"}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class EndpointDef:
    method: str                        # HTTP verb, upper-cased
    path: str                          # e.g. /staylink/reservations/{uuid}
    step: int | None                   # async step number (1/2/3); None for oauth/static/fetch
    response: dict[str, Any]           # raw response config from YAML


@dataclass
class DatapointDef:
    name: str                          # e.g. "reservation"
    description: str
    pattern: str                       # "oauth" | "async" | "fetch" | "static" | "push"
    endpoints: list[EndpointDef]


@dataclass
class PartnerDef:
    partner: str                       # e.g. "staylink"
    description: str
    datapoints: list[DatapointDef]
    source_path: Path                  # absolute path to the partner.yaml file


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_endpoint(raw: dict[str, Any]) -> EndpointDef:
    method = raw.get("method")
    path = raw.get("path")

    if not method:
        raise ValueError(f"Endpoint is missing 'method': {raw}")
    if not path:
        raise ValueError(f"Endpoint is missing 'path': {raw}")

    return EndpointDef(
        method=method.upper(),
        path=path,
        step=raw.get("step"),          # optional; only async endpoints carry this
        response=raw.get("response") or {},
    )


def _parse_datapoint(raw: dict[str, Any], partner: str) -> DatapointDef:
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

    return DatapointDef(
        name=name,
        description=raw.get("description", ""),
        pattern=pattern,
        endpoints=[_parse_endpoint(e) for e in raw_endpoints],
    )


def _parse_partner(raw: dict[str, Any], source_path: Path) -> PartnerDef:
    partner = raw.get("partner")
    if not partner:
        raise ValueError(f"Partner YAML at {source_path} is missing the 'partner' key")

    raw_datapoints = raw.get("datapoints")
    if not raw_datapoints:
        raise ValueError(f"Partner '{partner}' has no datapoints defined")

    return PartnerDef(
        partner=partner,
        description=raw.get("description", ""),
        datapoints=[_parse_datapoint(dp, partner) for dp in raw_datapoints],
        source_path=source_path,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_partner_yaml(text: str, source_path: Path = Path("<input>")) -> PartnerDef:
    """Parse and validate a partner YAML string.

    Raises:
        yaml.YAMLError: if the text is not valid YAML.
        ValueError: if the parsed content fails schema validation.
    """
    raw = yaml.safe_load(text)
    return _parse_partner(raw, source_path)


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
            partners.append(partner)
            logger.info(
                "Loaded partner '%s' with %d datapoint(s) from %s",
                partner.partner,
                len(partner.datapoints),
                yaml_path,
            )
        except Exception as exc:
            logger.error("Failed to load partner from %s: %s", yaml_path, exc)

    return partners
