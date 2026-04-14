"""
Core partner registration logic, shared by the CLI and the HTTP admin endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from imnot.loader.yaml_loader import PartnerDef, parse_partner_yaml


@dataclass
class RegisterResult:
    partner: PartnerDef
    created: bool   # True = new file written, False = overwritten
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
    partner = parse_partner_yaml(yaml_text)

    dest_dir = partners_dir / partner.partner
    dest_file = dest_dir / "partner.yaml"
    file_exists = dest_file.exists()

    if file_exists and not force:
        raise FileExistsError(
            f"partners/{partner.partner}/partner.yaml already exists. Use --force to overwrite."
        )

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(yaml_text)

    return RegisterResult(
        partner=partner,
        created=False if dry_run else not file_exists,
        dest_file=dest_file,
    )
