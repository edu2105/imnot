"""Export the OpenAPI schema for imnot admin endpoints.

Usage:
    .venv/bin/python scripts/export_openapi.py

Outputs openapi.json in the repo root. Run before tagging a release
alongside `make ui`.
"""
import json
from pathlib import Path

from imnot.api.server import create_app

app = create_app(partners_dir=None, admin_key=None)
schema = app.openapi()

out = Path(__file__).parent.parent / "openapi.json"
out.write_text(json.dumps(schema, indent=2))
print(f"Written to {out}")
