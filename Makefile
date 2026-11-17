.PHONY: ui dev openapi

# Use the project venv when it exists (local dev); fall back to python3 (CI, Docker).
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

# ui: inline all CSS files into index.html for production (before packaging the wheel).
#     Replaces everything between the IMNOT:CSS sentinel markers. Safe to run multiple times.
#
# dev: restore <link> tags so Live Server picks up css/*.css edits instantly.
#     Run this after 'make ui' when you want to go back to editing CSS files.
#
# openapi: regenerate openapi.json from the current route definitions.
#     Run before tagging a release alongside 'make ui'.

ui:
	$(PYTHON) scripts/css_build.py ui

dev:
	$(PYTHON) scripts/css_build.py dev

openapi:
	$(PYTHON) scripts/export_openapi.py
