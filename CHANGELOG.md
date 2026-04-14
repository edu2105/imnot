# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `GET /healthz` — lightweight health check endpoint; always returns `200 {"status":"ok","version":"…"}`, exempt from `IMNOT_ADMIN_KEY` auth, no file I/O or DB queries. Intended for Kubernetes/ECS liveness and readiness probes.

## [0.3.0] - 2026-04-14

### Changed

- Project renamed from `mirage` to `imnot` — package, CLI entry point, all admin routes (`/mirage/` → `/imnot/`), session header (`X-Mirage-Session` → `X-Imnot-Session`), env var (`MIRAGE_ADMIN_KEY` → `IMNOT_ADMIN_KEY`), and Docker image (`ghcr.io/edu2105/mirage` → `ghcr.io/edu2105/imnot`). This is a breaking change for existing deployments.

## [0.2.0] - 2026-04-14

### Added

- `POST /mirage/admin/partners` — register a new partner from a raw YAML body over HTTP; routes go live immediately without a server restart. Designed for containerised deployments where exec-ing into the pod is not practical.
- `mirage/partners.py` — `register_partner()` shared core used by both `mirage generate` and the new HTTP endpoint, eliminating duplication.

### Changed

- `mirage generate` refactored to call `register_partner()` internally — behaviour is identical, no CLI changes.
- `docs/` directory is now gitignored and excluded from the Docker image; design documents are kept locally only.

## [0.1.1] - 2026-04-13

### Added

- `GET /mirage/docs` — serves `README.md` as plain text (no auth required)
- `GET /mirage/docs/partners` — serves `partners/README.md` as plain text (no auth required)

## [0.1.0] - 2026-04-13

### Added

- Five interaction patterns: `oauth`, `static`, `fetch`, `async`, and `push`
- YAML-based partner definitions — no code required to add new partners or endpoints
- Stateful payload storage with global and session-isolated modes (`X-Mirage-Session`)
- Admin API for uploading payloads, inspecting sessions, listing partners, and hot-reloading YAMLs
- `MIRAGE_ADMIN_KEY` Bearer token auth on all admin endpoints
- `mirage start` with optional `--reload` flag for auto-restart on YAML changes
- `mirage generate` to validate and scaffold partner YAMLs into `partners/`
- `mirage export postman` and `GET /mirage/admin/postman` for Postman collection v2.1 export
- `mirage routes`, `mirage payload`, and `mirage sessions` CLI commands
- Docker image published at `ghcr.io/edu2105/mirage` with volume mounts for partners and data
- GitHub Actions CI (pytest on Python 3.11 and 3.12, bandit security scan)
- Push pattern retrigger endpoint (`POST /mirage/admin/{partner}/{datapoint}/push/{id}/retrigger`)
- Route collision detection — startup fails fast on conflicting routes across partners
