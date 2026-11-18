"""
Core partner registration logic, shared by the CLI and the HTTP admin endpoint.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from imnot.loader.yaml_loader import PartnerDef, parse_partner_yaml

_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@dataclass
class RegisterResult:
    partner: PartnerDef
    created: bool  # True = new file written, False = overwritten
    dest_file: Path


def register_partner(
    yaml_text: str,
    partners_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> RegisterResult:
    """Validate *yaml_text* and write it to *partners_dir/<name>/partner.yaml*.

    Raises:
        yaml.YAMLError / ValueError  — invalid YAML or schema validation error.
        FileExistsError              — partner already exists and *force* is False.
    """
    partner = parse_partner_yaml(yaml_text, strict=True)

    if not _SAFE_NAME.match(partner.partner):
        raise ValueError(
            f"Partner name '{partner.partner}' is invalid. "
            "Use only letters, digits, hyphens, and underscores (max 64 chars)."
        )

    dest_dir = partners_dir / partner.partner
    # Guard against path traversal — pathlib does not resolve '..' in '/' joins.
    try:
        dest_dir.resolve().relative_to(partners_dir.resolve())
    except ValueError:
        raise ValueError(f"Partner name '{partner.partner}' would escape the partners directory.")
    dest_file = dest_dir / "partner.yaml"
    file_exists = dest_file.exists()

    if file_exists and not force:
        raise FileExistsError(f"partners/{partner.partner}/partner.yaml already exists. Use --force to overwrite.")

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(yaml_text)

    return RegisterResult(
        partner=partner,
        created=False if dry_run else not file_exists,
        dest_file=dest_file,
    )


def dropped_fields(old_yaml: str, new_yaml: str) -> list[str]:
    """Return the fields present in *old_yaml* that *new_yaml* would silently lose.

    Used by the Builder's edit mode, which regenerates partner.yaml from a form that does
    not round-trip every field. Only removals count, not changed values. Datapoints are
    matched by name and endpoints by ``(method, path, step)``, falling back to position;
    a datapoint missing from *new_yaml* is treated as removed on purpose, not as a drop.
    """
    old = yaml.safe_load(old_yaml)
    new = yaml.safe_load(new_yaml)
    if not isinstance(old, dict) or not isinstance(new, dict):
        return []

    dropped: list[str] = []
    _diff_keys(old, new, "", dropped, skip={"datapoints"})

    new_dps = {dp.get("name"): dp for dp in new.get("datapoints") or [] if isinstance(dp, dict)}
    for old_dp in old.get("datapoints") or []:
        if not isinstance(old_dp, dict) or old_dp.get("name") not in new_dps:
            continue
        new_dp = new_dps[old_dp["name"]]
        where = f"datapoints[{old_dp['name']}]"
        _diff_keys(old_dp, new_dp, where, dropped, skip={"endpoints"})

        new_eps = [ep for ep in new_dp.get("endpoints") or [] if isinstance(ep, dict)]
        by_key = {_endpoint_key(ep): ep for ep in new_eps}
        for i, old_ep in enumerate(old_dp.get("endpoints") or []):
            if not isinstance(old_ep, dict):
                continue
            new_ep = by_key.get(_endpoint_key(old_ep)) or (new_eps[i] if i < len(new_eps) else None)
            if new_ep is None:
                continue
            label = f"{str(old_ep.get('method', '')).upper()} {old_ep.get('path', '')}".strip()
            _diff_keys(old_ep, new_ep, f"{where}.endpoints[{label}]", dropped)
    return dropped


def _endpoint_key(ep: dict) -> tuple:
    return (str(ep.get("method", "")).upper(), ep.get("path"), ep.get("step"))


def _diff_keys(old: dict, new: dict, where: str, out: list[str], skip: set[str] = frozenset()) -> None:
    for key, old_val in old.items():
        if key in skip:
            continue
        path = f"{where}.{key}" if where else str(key)
        if key not in new:
            out.append(path)
        elif isinstance(old_val, dict) and isinstance(new[key], dict):
            _diff_keys(old_val, new[key], path, out)


# Keys the Builder form never writes. When the Builder saves an existing partner with
# merge_from, these are carried over from the current file (see merge_unmanaged_fields).
# Everything else is the form's to decide, so a field the user removed in the form stays removed.
_UNMANAGED_DATAPOINT_KEYS = {"description"}
_UNMANAGED_ENDPOINT_KEYS = {"validate", "delay_ms", "fail"}
_UNMANAGED_RESPONSE_KEYS = {"headers", "payload_by", "pending", "callback_method"}
_UNMANAGED_RESPONSE_KEYS_BY_PATTERN = {"polling": {"body"}}  # the form only edits a static body


def merge_unmanaged_fields(old_yaml: str, new_yaml: str) -> str:
    """Return *new_yaml* plus the fields of *old_yaml* the Builder form does not manage.

    Datapoints are matched by name and endpoints like ``dropped_fields`` does. Comments are not
    kept (the file is re-serialised). If either side is not a mapping, *new_yaml* is returned as is.
    """
    old = yaml.safe_load(old_yaml)
    new = yaml.safe_load(new_yaml)
    if not isinstance(old, dict) or not isinstance(new, dict):
        return new_yaml

    old_dps = {dp.get("name"): dp for dp in old.get("datapoints") or [] if isinstance(dp, dict)}
    for new_dp in new.get("datapoints") or []:
        old_dp = old_dps.get(new_dp.get("name")) if isinstance(new_dp, dict) else None
        if old_dp is None:
            continue
        _carry(old_dp, new_dp, _UNMANAGED_DATAPOINT_KEYS)
        pattern = new_dp.get("pattern")
        old_eps = [ep for ep in old_dp.get("endpoints") or [] if isinstance(ep, dict)]
        by_key = {_endpoint_key(ep): ep for ep in old_eps}
        for i, new_ep in enumerate(new_dp.get("endpoints") or []):
            if not isinstance(new_ep, dict):
                continue
            old_ep = by_key.get(_endpoint_key(new_ep)) or (old_eps[i] if i < len(old_eps) else None)
            if old_ep is None:
                continue
            _carry(old_ep, new_ep, _UNMANAGED_ENDPOINT_KEYS)
            old_resp, new_resp = old_ep.get("response"), new_ep.get("response")
            if isinstance(old_resp, dict) and isinstance(new_resp, dict):
                keys = _UNMANAGED_RESPONSE_KEYS | _UNMANAGED_RESPONSE_KEYS_BY_PATTERN.get(pattern, set())
                _carry(old_resp, new_resp, keys)
    return yaml.safe_dump(new, sort_keys=False, allow_unicode=True)


def _carry(old: dict, new: dict, keys: set[str]) -> None:
    for key in keys:
        if key in old and key not in new:
            new[key] = old[key]
