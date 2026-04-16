# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]

### Added

- Feat: add imnot init command for project scaffolding

`imnot init [--dir DIR]` creates a partners/ directory with working
staylink and bookingco example YAMLs bundled as package data, giving
new users a runnable starting point immediately after pipx install.

Also updates the imnot start error message to mention imnot init
when no partners directory is found.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([f677ebc](https://github.com/edu2105/imnot/commit/f677ebcafee2bd34d796df1882e7cd1eb5260064))

### CI

- Ci: replace publish workflows with secure release.yml

- Consolidates publish-pypi.yml and publish.yml into a single release.yml
- Adds a "production" GitHub Environment gate (required reviewer) so only
  the admin can approve a release — contributors cannot trigger it by
  pushing tags
- Sequential jobs: verify → publish-pypi → publish-docker → github-release
- verify job checks that the pushed tag matches the version in
  pyproject.toml, failing fast before any artifact is published
- github-release job generates release notes via git-cliff and creates
  the GitHub Release automatically
- Updates cliff.toml to work without conventional commits (catch-all
  parser, filter_unconventional = false)

One-time manual steps required in GitHub Settings (see design doc):
  1. Tag protection rule for v* (admin-only push)
  2. Create "production" environment with Eduardo as required reviewer

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([6eec9d1](https://github.com/edu2105/imnot/commit/6eec9d1dfbd6c8036c9b0e8d4696711b34a37c2a))

### Changes

- Merge pull request #17 from edu2105/feat/imnot-init

feat: add imnot init command for project scaffolding ([7af774e](https://github.com/edu2105/imnot/commit/7af774e2ac2b3621fb7d866415ce8a442e48bbbf))
- Merge pull request #16 from edu2105/ci/secure-release-workflow

ci: secure release workflow with admin-only gate and auto changelog ([fd96f2f](https://github.com/edu2105/imnot/commit/fd96f2f4469e3bb3caf82fb56539f86696523bba))

## [0.4.2] - 2026-04-16

### Changes

- Merge pull request #15 from edu2105/docs/ai-contribution-policy

docs: update Quick Start to use pip install from PyPI ([f60d8b7](https://github.com/edu2105/imnot/commit/f60d8b7d377ff49f3e30396088fc3a6cb21204fc))
- Merge pull request #13 from pureqin/fix/python313-ci

fix: Add Python 3.13 to the CI test matrix ([48c7c50](https://github.com/edu2105/imnot/commit/48c7c508cc4b1591b7b51d264ee161238a711180))
- Merge pull request #12 from edu2105/docs/ai-contribution-policy

docs: add AI-assisted contributions policy ([57a1dc9](https://github.com/edu2105/imnot/commit/57a1dc946ca8b3e4b19c031a27dfe0f80c0ba1dd))

### Documentation

- Docs: recommend pipx in Quick Start, clarify partner concept, fix start help text

- Swap pip → pipx as primary install method in Quick Start (handles
  externally-managed-environment errors on modern Debian/Ubuntu)
- Add one-liner explaining what a "partner" is right below the tagline
- Fix imnot start help text word order: "Start the mock server and load
  partner definitions" (action-first)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([5b2cb17](https://github.com/edu2105/imnot/commit/5b2cb17e5e4703b87154d043e437b382c1354332))
- Docs: update Quick Start to use pip install from PyPI

Replace the dev-install clone flow with a simple `pip install imnot`
now that the package is published. Move the clone steps to Contributing
where they belong.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([e5956fa](https://github.com/edu2105/imnot/commit/e5956fab8708781cd9358f61ee08d3b36368ed97))
- Docs: add AI-assisted contributions policy to CONTRIBUTING.md

Clarify that AI-assisted contributions are welcome but require a human
to review and take responsibility — fully autonomous PRs will be closed.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([cd03c37](https://github.com/edu2105/imnot/commit/cd03c37e21b2f4d3bb6e460952f65a86d47212e4))

### Fixed

- Fix: Add Python 3.13 to the CI test matrix ([1ec8ad0](https://github.com/edu2105/imnot/commit/1ec8ad00a71ac74ab23444be7796783aa3d87fa5))

## [0.4.1] - 2026-04-15

### Added

- Feat: add nametag SVG logo and update README header

Replaces the PNG header with a new pure-SVG nametag logo
("Hello, I am / Acme crossed out / imnot") that renders cleanly
on both light and dark GitHub themes without external font deps.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([c94e495](https://github.com/edu2105/imnot/commit/c94e4954381095b1c4d7d4b92b6eee586b9c7d27))

### CI

- Ci: add PyPI publish workflow via OIDC trusted publishing

Triggers on v* tags alongside the existing Docker publish workflow.
No API tokens required — uses PyPI's trusted publisher (OIDC) for auth.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([1341756](https://github.com/edu2105/imnot/commit/13417563129f155bf076520c9f32b466967f6c93))

### Documentation

- Docs: update test count in CONTRIBUTING.md to 228

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([12b1ebd](https://github.com/edu2105/imnot/commit/12b1ebd0fa2daf2511d81432208d3288c51c02c6))
- Docs: replace partner API jargon with external API + tighten AI prompts

Terminology: replace "partner's API" / "partner" in prose descriptions
with "external API" / "external service" — more universally understood.
Technical identifiers (partner.yaml, /admin/{partner}/, partners/ dir)
are unchanged — those are schema terms, not conceptual ones.

AI prompts: add explicit context so LLMs generate imnot YAML instead of
writing mock code. Each prompt now states the tool, the expected output
format (partner.yaml), the schema URL, and ends with "Output only the
YAML — no code, no explanation."

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([799bf2c](https://github.com/edu2105/imnot/commit/799bf2c3bf30861448be12a95e72dd815bd1377b))
- Docs: restructure README above the fold + add AI-ready section

- Condense Why imnot? from 3 paragraphs + 2 bullet lists to 3 tight bullets
- Add AI-ready section with copy-paste prompts for Claude/ChatGPT
- Move Quick Start above How it works so it lands above the fold
- Section order: Why → AI-ready → Quick Start → How it works → Patterns

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([5f0f44c](https://github.com/edu2105/imnot/commit/5f0f44c60fac4fc102c666e6d9fae50d7bcdfcab))
- Docs: rewrite Why imnot? section for clarity and broader positioning

Replaces the narrow async-focused pitch with a fuller value proposition:
simplicity of YAML-first setup, stateful multi-step flow support, session
isolation for parallel CI, and honest guidance on when other tools fit better.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([75002f7](https://github.com/edu2105/imnot/commit/75002f72920979734d83d0bf273ae9a21cdc64b7))

### Fixed

- Fix: restore "Hello, my name is" header text in nametag logo

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([64f0d57](https://github.com/edu2105/imnot/commit/64f0d572643ebae244a52c7de3d6cda17aad40ba))

### Maintenance

- Chore: add authors and project URLs to pyproject.toml

Required for PyPI publishing — adds maintainer identity and links
to homepage, repo, issues, and changelog.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([fcacedf](https://github.com/edu2105/imnot/commit/fcacedfec8b8fe5e306d0b8e2973dcad33aeff60))

## [0.4.0] - 2026-04-14

### Added

- Feat: add GET /healthz for container health probes (#6)

Lightweight endpoint that always returns 200 {"status":"ok","version":"…"}.
Exempt from IMNOT_ADMIN_KEY auth by design — the admin middleware only gates
/imnot/admin/* paths, so /healthz is naturally public.

No file I/O, no DB queries. Intended for Kubernetes/ECS liveness and
readiness probes as a replacement for the /imnot/docs workaround.

228 tests passing.

Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com> ([e0ab4d8](https://github.com/edu2105/imnot/commit/e0ab4d8bbb0fc4b3d4ecff5dc071994e3edd91a3))

## [0.3.0] - 2026-04-14

### Added

- Feat: rename project from mirage to imnot

- Python package directory mirage/ → imnot/; all internal imports updated
- CLI command: mirage → imnot
- API routes: /mirage/admin/… → /imnot/admin/…, /mirage/docs/… → /imnot/docs/…
- HTTP session header: X-Mirage-Session → X-Imnot-Session
- Env vars: MIRAGE_* → IMNOT_* (DB_PATH, ADMIN_KEY, PARTNERS_DIR)
- Default DB filename: mirage.db → imnot.db
- Docker image target: ghcr.io/edu2105/mirage → ghcr.io/edu2105/imnot
- Postman collection name and default output filename updated
- Asset renamed: assets/mirage-logo.png → assets/imnot-logo.png
- All test assertions, docs, and CI scripts updated
- 226 tests passing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([29c72c2](https://github.com/edu2105/imnot/commit/29c72c20d4a1e6df2ea4f5c7626e34960b44b518))

### Changes

- Merge pull request #5 from edu2105/rename/mirage-to-imnot

feat: rename project from mirage to imnot ([a06e5b0](https://github.com/edu2105/imnot/commit/a06e5b0f7c5decfec7ae2621892e605810cc3857))

### Fixed

- Fix: finish rename — update remaining Mirage product name references

- assets/logo.svg: MIRAGE → IMNOT wordmark
- README.md: all product name references (headings, prose, ASCII diagrams)
- imnot/postman.py: two docstring/description strings
- tests/test_docs.py: assertion against README content now checks "imnot"
- tests/test_postman.py: comment updated
- .github/ISSUE_TEMPLATE/bug_report.md: version field label

226 tests passing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([d4d0ed1](https://github.com/edu2105/imnot/commit/d4d0ed1da4da1b30f71be973cbacdeb89d99840b))

## [0.2.0] - 2026-04-14

### Added

- Feat: add POST /mirage/admin/partners for HTTP partner registration

Extracts register_partner() into mirage/partners.py — shared by both
mirage generate (CLI) and the new POST /mirage/admin/partners endpoint.
Routes go live immediately on success; no restart required.

Also gitignores docs/ (design docs stay local, excluded from Docker image).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([908ac14](https://github.com/edu2105/imnot/commit/908ac1437d5057ef16bb10018f21fdc915ec4f45))

## [0.1.1] - 2026-04-13

### Added

- Feat: add /mirage/docs endpoints serving README files as plain text

GET /mirage/docs         → README.md
GET /mirage/docs/partners → partners/README.md

Public, no auth required. Resolves paths via partners_dir.parent in
Docker and falls back to package-relative path for local installs.
12 new tests, 208 total passing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([c7cc6c8](https://github.com/edu2105/imnot/commit/c7cc6c8918265f7b5242a34e6fd6e8d17cec822c))

## [0.1.0] - 2026-04-13

### Added

- Feat: add --partner filter to mirage export postman

Allows generating a collection for one or more specific partners instead
of all loaded partners. Repeatable flag: --partner staylink --partner bookingco.
Exits non-zero with a clear error if an unknown partner name is given.

3 new tests; 196 total passing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([4d95707](https://github.com/edu2105/imnot/commit/4d957075ebf8e1cdc265cdda76933a85a18c8fac))
- Feat: add Postman collection export

Adds `mirage export postman` CLI command and `GET /mirage/admin/postman`
admin endpoint that generate a Postman collection v2.1 JSON from loaded
partner definitions. Covers all patterns (oauth, static, fetch, async, push),
pre-fills push callback bodies/headers, adds disabled X-Mirage-Session header
on payload-pattern endpoints, and includes Admin sub-folders for fetch/async/push
datapoints (4 requests each; 5 for push with retrigger).

37 new tests; 193 total passing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([1e09785](https://github.com/edu2105/imnot/commit/1e09785e89fae49bc1057f5c399bf4f751c3f5c5))
- Feat: implement push pattern (webhooks)

Adds the push pattern so Mirage can simulate partner APIs that call back
a consumer webhook instead of waiting to be polled.

- push.py: handler extracts callback URL from request body field or header,
  stores the request, returns configured status + request_id immediately,
  then fires the payload to the callback URL as a background task
- session_store.py: new push_requests table with callback_url and
  callback_method columns; store_push_request / get_push_request methods
- router.py: push branch in _register_consumer_routes; retrigger admin
  route (POST /mirage/admin/{partner}/{dp}/push/{id}/retrigger) registered
  for push datapoints so consumers can re-fire without restarting the flow
- cli.py: mirage routes and mirage generate both show the retrigger route
- 23 new tests covering startup validation, body/header URL extraction,
  session isolation, delay, retrigger (valid/unknown/updated payload/
  original session), and admin route presence — 156 total, all passing
- docs/design-push.md: permanent decision record
- README.md, partners/README.md: push pattern fully documented

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([064a5c5](https://github.com/edu2105/imnot/commit/064a5c51ae4d1c3bf395b1edc3aa0660e5707112))
- Feat: add mirage generate command

Validates and scaffolds a partner YAML into partners/ in one step.
Flags: --file (required, - for stdin), --dry-run, --json, --force, --partners-dir.
Exit codes: 0 ok, 1 validation error, 2 conflict, 3 partners dir not found.

Also fixes _resolve_partners_dir to raise FileNotFoundError for
non-existent absolute paths (previously returned silently).

133 tests passing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([02f4fe9](https://github.com/edu2105/imnot/commit/02f4fe9595205f8dadba10e3efe484bcc81f4734))
- Feat: migrate staylink partner from poll to async pattern

Update partner.yaml to use pattern: async with generates_id/id_header/
id_header_value/returns_payload schema. Rename poll consumer route tests
to staylink-prefixed names and update yaml_loader assertions to match.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([7e0cd70](https://github.com/edu2105/imnot/commit/7e0cd70c3cbb57918737d70a3e62e9125ae203d3))
- Feat: add async pattern dispatch to router

Wire the async pattern in _register_consumer_routes: import
make_async_handlers from patterns/async_ and add the dispatch block
that maps step numbers to EndpointDef routes. Add 6 integration tests
using an isolated tmp_path async partner fixture; all 6 pass.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([9fd50a8](https://github.com/edu2105/imnot/commit/9fd50a8abaa0b12a58d6c435aa5034d28f8a31b9))
- Feat: add async to supported YAML patterns, remove poll ([1a188d2](https://github.com/edu2105/imnot/commit/1a188d28ffd262f0c0f8aa5d0fbf0099fa496990))
- Feat: complete async pattern with static and fetch handlers

Replace NotImplementedError stubs in async_.py with real implementations.
Static handler returns configured status/headers and optional body verbatim.
Fetch handler validates the async UUID, resolves global or session payload,
and returns 404 with clear detail messages on any miss.
All 18 async pattern tests pass.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([808d506](https://github.com/edu2105/imnot/commit/808d506e15d3cc372b9fea5fec7071d21d888f32))
- Feat: add async pattern submit handler (header and body ID delivery)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([9375172](https://github.com/edu2105/imnot/commit/9375172640a079d0aa41736e31835c8849d54f83))
- Feat: add Docker support

- Dockerfile: python:3.12-slim, partners + data as volume mounts
- docker-compose.yml: one-command local experience, persists state in ./data/
- .dockerignore: excludes venv, cache, db files, tests from image
- .gitignore: add data/ to keep SQLite volume out of git
- README: docker compose up as the recommended quick start

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([353b0f9](https://github.com/edu2105/imnot/commit/353b0f97eb74a45b8a89ebf1ba6113b92d05fd7c))
- Feat: add SVG logo with reflection shimmer effect

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([f5f1846](https://github.com/edu2105/imnot/commit/f5f1846854fd3c21cd9111a92a9d9b700329639c))
- Feat: static/fetch patterns, LeanPMS partner, expanded CLI, and CI

- Add static pattern: returns fixed JSON body from YAML response.body
- Add fetch pattern: synchronous GET that resolves stored payload with
  full X-Mirage-Session support
- Add LeanPMS partner YAML (static token + fetch charges)
- Expand CLI: mirage routes, payload get/set, sessions clear
- Add GitHub Actions CI: pytest matrix on Python 3.11 + 3.12
- Pin asyncio_mode = strict in pyproject.toml
- Harden existing tests to be resilient to multiple loaded partners

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([ccedb56](https://github.com/edu2105/imnot/commit/ccedb5653ae41c2e7a509025ad5fd0510eda2cc6))
- Feat: admin GET endpoints to inspect stored payloads

- GET /mirage/admin/{partner}/{datapoint}/payload → current global payload + updated_at
- GET /mirage/admin/{partner}/{datapoint}/payload/session/{session_id} → session payload + metadata
- SessionStore.get_global_payload() and get_session_payload() backing methods
- 71 tests passing (+10 new)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([4c018c4](https://github.com/edu2105/imnot/commit/4c018c40ca8d5348b9a2aae63959aea01b0cb58d))
- Feat: app factory, CLI, and smoke test — POC complete

- mirage/api/server.py: create_app() factory with FastAPI lifespan for clean store init/shutdown
- mirage/cli.py: `mirage start` (uvicorn) and `mirage status` (session table) via Click
- tests/test_server.py: 5 integration tests including full global + session flows
- tests/test_cli.py: 6 CLI tests covering start, status, and error cases
- scripts/smoke_test.sh: end-to-end curl script covering all OHIP endpoints
- 61 tests total, all passing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([dffa5d9](https://github.com/edu2105/imnot/commit/dffa5d99aa2995ee9302363875aafd6f27c0861b))
- Feat: router, pattern handlers, and session store

- mirage/engine/router.py: dynamic route registration for all patterns + admin + infra endpoints
- mirage/engine/patterns/oauth.py: OAuth token handler factory
- mirage/engine/patterns/poll.py: three-step poll handler factory
- mirage/engine/session_store.py: SQLite-backed global/session payload persistence
- tests/test_router.py: 14 integration tests via TestClient (50 total, all passing)
- Remove PLAN.md from tracking (local only)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([4837b26](https://github.com/edu2105/imnot/commit/4837b26b75ba6766e433fe3cee9d5af1a61efd13))
- Feat: project scaffold, loader, session store, and pattern handlers

- Project scaffold: pyproject.toml, folder structure, __init__.py files
- partners/ohip/partner.yaml: full OHIP reservation flow (oauth + poll)
- mirage/loader/yaml_loader.py: parses partner YAMLs into PartnerDef/DatapointDef/EndpointDef
- mirage/engine/session_store.py: SQLite persistence for global/session payloads and poll requests
- mirage/engine/patterns/oauth.py: factory returning FastAPI handler for OAuth token endpoints
- mirage/engine/patterns/poll.py: factory returning step 1/2/3 handlers for async poll flows
- CLAUDE.md, PLAN.md: project context and build plan
- 36 unit tests, all passing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([f55f36a](https://github.com/edu2105/imnot/commit/f55f36acea314f63cca67e5ef3fba625b5961fef))

### Changed

- Refactor: rename poll_requests table and methods to async_requests

Renames the SQLite table from poll_requests to async_requests and renames
register_poll_request/get_poll_request to register_async_request/get_async_request.
Adds a migration in init() to rename the table in existing databases.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([054c7d5](https://github.com/edu2105/imnot/commit/054c7d57a8f3978d62a62eb20b4c39e07827ae8a))

### Changes

- Merge pull request #4 from edu2105/chore/going-public-docs

chore: contributor experience files for going public ([68a2ed9](https://github.com/edu2105/imnot/commit/68a2ed9d565001bdbb7156bc0c3163d1d3cc999a))
- Merge pull request #3 from edu2105/chore/security-audit

chore: security audit — suppress bandit false positives, add bandit to CI ([0922956](https://github.com/edu2105/imnot/commit/0922956c92408abedc6e065d5be9fda09a741a4e))
- Merge pull request #2 from edu2105/feat/postman-export

feat: add Postman collection export ([78eea0c](https://github.com/edu2105/imnot/commit/78eea0c25acb080fcca9996f6967cd9374290569))
- Merge pull request #1 from edu2105/feat/push-pattern

feat: implement push pattern (webhooks) ([281e07f](https://github.com/edu2105/imnot/commit/281e07f03815a02046b7390e734b2410cc8cd23b))
- Assets: update logo to illustrated desert mirage with transparent background

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([2bd5d53](https://github.com/edu2105/imnot/commit/2bd5d530eaa7623a9ac7aa3b96317b09af97c42c))
- Security: restrict admin endpoint exposure and add optional auth

Two mitigations for unauthenticated admin API exposure:

1. docker-compose.yml: bind to 127.0.0.1 by default so the container
   is not reachable from the network without an explicit decision.

2. Optional Bearer token auth on all /mirage/admin/* endpoints:
   - --admin-key CLI flag (or MIRAGE_ADMIN_KEY env var)
   - When set, requests without Authorization: Bearer <key> get 401
   - When unset, behaviour is unchanged (open, for local dev)
   - Consumer endpoints are never affected

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([ade5942](https://github.com/edu2105/imnot/commit/ade59426b2d246033449a84c2a87c9597143af81))
- Initial commit ([616d1ca](https://github.com/edu2105/imnot/commit/616d1ca39148b724a6fc6500f2769a4ca45a62e5))

### Documentation

- Docs: replace provider-specific cloud section with agnostic deployment notes

Remove Railway, Render, and VM-specific guides. Replace with a concise,
provider-agnostic section covering what Mirage itself requires (persistent
volume, admin key, host binding, partner YAMLs).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([303460e](https://github.com/edu2105/imnot/commit/303460e9853c6057cf5d5d8e1feda52484433ac1))
- Docs: document --partner filter for mirage export postman

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([c1f63cd](https://github.com/edu2105/imnot/commit/c1f63cdcb77744298221f5331a64553e7fc2ea68))
- Docs: add going-public design doc and workstream plan

Captures the checklist and implementation order for making the repo
public: security scan, branch protection, contributor docs, deployment
guidance, and ghcr.io image publishing.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([4932dd9](https://github.com/edu2105/imnot/commit/4932dd9b641e722bf579323abe14b2ed1b1eab80))
- Docs: add end-to-end example to mirage generate design doc

Full walkthrough: Claude Code generates YAML from API docs, dry-run
validates, generate scaffolds, reload activates, curl smoke test confirms.
Includes error path showing validation failure and recovery.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([de47b8d](https://github.com/edu2105/imnot/commit/de47b8d255b802ec10e91413ba417c17062c03c3))
- Docs: add design doc for mirage generate command

Covers interface, workflow, output format, exit codes, flags,
implementation plan, and out-of-scope decisions.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([210d1b8](https://github.com/edu2105/imnot/commit/210d1b808f4e259b5b632624562c020ac4d98504))
- Docs: make local install the primary quick start, demote Docker

Docker requires exec to use the CLI which is friction for new users.
Local install gives mirage commands immediately after clone.
Docker section reframed as a service/deployment option.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([8b80cb9](https://github.com/edu2105/imnot/commit/8b80cb9f64b83e740b829cd5ae1052dd44a55666))
- Docs: fix Docker quick start to show mirage routes via exec

The host shell doesn't have the mirage CLI installed after docker compose
up, so running mirage routes directly would fail. Show the correct
docker compose exec invocation instead.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([38efb88](https://github.com/edu2105/imnot/commit/38efb88f7515e522a6e50467248e8c3fe71df43c))
- Docs: update README and partners guide to replace poll with async pattern

Remove all references to the deleted poll pattern. Document the async pattern
with OHIP-style and Cloudbeds-style examples, ID delivery modes, and updated
checklist and AI guidance in partners/README.md.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([84ee268](https://github.com/edu2105/imnot/commit/84ee268b75a9902facd2bc19f3f6442ae2c53cef))
- Docs: fix stale poll comment in staylink partner.yaml ([36da756](https://github.com/edu2105/imnot/commit/36da756f95889dd1d74bfb86b8423a3b76b27de5))
- Docs: add async pattern implementation plan

7 tasks, TDD throughout: session store rename, async_.py (submit/static/fetch),
yaml_loader, router dispatch, staylink migration, poll removal.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([c6d4182](https://github.com/edu2105/imnot/commit/c6d41821d350c9aef810b54599e207f553db7a06))
- Docs: add design spec for async pattern (replaces poll)

Covers YAML schema, handler types, ID delivery modes (header vs body),
ID persistence rationale, session store migration, and files changed.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([0b199cd](https://github.com/edu2105/imnot/commit/0b199cd53b5b61de7e663118914e02e4077177ad))
- Docs: expand README with Why Mirage, sequence diagram, Quick Start, Deploy, Limitations, Contributing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([1368803](https://github.com/edu2105/imnot/commit/136880318d56754550da03e4fe30ec092ad5c545))
- Docs: document admin endpoint auth and Docker network exposure

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([73c94b9](https://github.com/edu2105/imnot/commit/73c94b9dcf0f3ba855da597419cfba635b206db5))
- Docs: use PNG logo, clean up stale references in README

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([0a3a950](https://github.com/edu2105/imnot/commit/0a3a950cc6d22e39e6f8553440e88aee724886ce))
- Docs: add partner YAML authoring guide

Covers full field reference, all patterns (oauth, poll, push/future),
path parameter rules, auto-generated admin endpoints, a pre-save checklist,
and a dedicated section for AI-assisted YAML generation from API docs.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([90d09db](https://github.com/edu2105/imnot/commit/90d09dbe70706b106b6e51636f314601a734f436))

### Fixed

- Fix: detect and reject cross-partner route collisions at startup

registered_routes changed from set to dict[(method, path) → owner] so
_check_route_collision() can raise ValueError with a clear message before
any app.add_api_route() call. Startup fails fast on conflict; reload reports
conflicts in the response body (status: "partial") instead of crashing.
partners/README.md checklist updated to call out the cross-partner constraint.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([5de4d47](https://github.com/edu2105/imnot/commit/5de4d47eeb5766e5bc0c3ce7bb56c00f584c7645))
- Fix: partners dir discovery, remove admin routes for oauth/static, add hot reload

- mirage routes/start now walk up from CWD to find partners/ automatically,
  so the commands work from any subdirectory of the project
- Admin payload routes (POST/GET payload + session) are no longer registered
  for oauth and static patterns — those patterns never use the payload store;
  only fetch, async, and push get admin routes (_PAYLOAD_PATTERNS constant)
- mirage start --reload now works correctly: switches to uvicorn factory mode
  (create_app_from_env) with reload_includes=["*.yaml"] so any YAML edit or
  new file triggers an automatic restart
- POST /mirage/admin/reload added: hot-swaps static response configs in place
  via a shared mutable configs dict, and registers new partners/datapoints
  dynamically without restarting the server
- static handlers now close over a key into the shared configs dict rather
  than the response config directly, enabling in-process config updates
- README and partners/README updated: admin route scope, reload workflows,
  oauth vs static guidance for custom token fields

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([8cf8c91](https://github.com/edu2105/imnot/commit/8cf8c914b3762f84ab16e4941e52e5a625c42b32))
- Fix: include partner in static handler __name__ to prevent OpenAPI operationId collisions ([469b665](https://github.com/edu2105/imnot/commit/469b665c01902540eb1e942fd0da9a3e7d19d17d))
- Fix: async stubs return callables and validate id delivery config

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([849d59a](https://github.com/edu2105/imnot/commit/849d59ad13fbf09c9441fbe2290847bbaebfcd05))
- Fix: update poll.py callers and harden migration guard after store rename

Also update two test assertions in test_poll_pattern.py that still called
the old get_poll_request method.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([b7b4ce4](https://github.com/edu2105/imnot/commit/b7b4ce4f51bf63be7d08b49c7a46d62e3227f763))
- Fix: copy README.md before pip install and use non-editable install

hatchling requires README.md to be present at build time.
Editable installs (-e) are for development, not containers.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([98beead](https://github.com/edu2105/imnot/commit/98beead61ee9b6985dbf7151a289c51190e9db1d))
- Fix: return 400 on malformed JSON in admin payload endpoints

Previously request.json() raised an unhandled exception, causing a 500.
Now returns {"detail": "Invalid JSON body"} with status 400.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([259bdc0](https://github.com/edu2105/imnot/commit/259bdc07bc403df200bac7f0a67f2db24bb68b15))
- Fix: smoke test counter arithmetic and global payload fallback assertion

- ((PASS++)) with set -e exits when PASS=0 (arithmetic 0 is falsy); use PASS=$((PASS+1))
- Session flow fallback assertion was wrong: global payload exists from step 2,
  so no-session-header GET correctly returns 200 with the global payload

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([01f29ac](https://github.com/edu2105/imnot/commit/01f29ac6890788ebe809d7adc2f1e2e4517e4588))

### Maintenance

- Chore: update README and gitignore for release tooling

- README: document pre-built ghcr.io image in Docker section
- .gitignore: ignore mirage-collection.json (generated by export postman)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([9ed9129](https://github.com/edu2105/imnot/commit/9ed912980614a8afc2202ff7f4161f439d9fb479))
- Chore: add CHANGELOG, cliff config, and ghcr.io publish workflow

- CHANGELOG.md: Keep a Changelog format, starts with [Unreleased]
- cliff.toml: conventional commits → grouped changelog sections (Added,
  Fixed, Changed, Documentation, Testing, Maintenance)
- publish.yml: builds and pushes ghcr.io/edu2105/mirage on v* tag push,
  tags image with semver version and latest

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([6ff49c5](https://github.com/edu2105/imnot/commit/6ff49c5122c7f1c83bad345c95673c534d3d1928))
- Chore: remove provider-specific references from SECURITY.md scope

Keep the deployment model description cloud-agnostic — users may deploy
on any cloud provider or private infrastructure.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([ef8d034](https://github.com/edu2105/imnot/commit/ef8d034dc9142934939bfc190524535519f97a3f))
- Chore: fix copyright year and broaden SECURITY.md deployment scope

Update LICENSE year to 2026 (actual creation year). Rewrite SECURITY.md
scope section to reflect that Mirage supports cloud and infrastructure
deployments, not just local use.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([e496ae1](https://github.com/edu2105/imnot/commit/e496ae1841b74913ede94c5aa56c047e476de1e4))
- Chore: add CODE_OF_CONDUCT, PR template, and issue templates

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([cd77e07](https://github.com/edu2105/imnot/commit/cd77e0792c23be1a567a2af9e859505aaeb9f252))
- Chore: add LICENSE, SECURITY.md, and CONTRIBUTING.md

- LICENSE: MIT, root-level (required by open source standard)
- SECURITY.md: private vulnerability reporting via GitHub
- CONTRIBUTING.md: fork model, local setup, test instructions, PR expectations

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([2d512c8](https://github.com/edu2105/imnot/commit/2d512c8f5d7114bbae845471e6acb341a9b7dd69))
- Chore: suppress bandit false positives and add bandit to CI

- B105 on oauth.py: static JWT token is an intentional mock placeholder
- B101 on session_store.py: assert is a programmer-error guard, not a security check
- Add `bandit -r mirage/` as a CI step so future regressions are caught on every PR

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([7d88cdf](https://github.com/edu2105/imnot/commit/7d88cdf664f63bbebd69a927f97eaa4453b21cf1))
- Chore: remove apaleo partner (was testing only)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([7b19f4d](https://github.com/edu2105/imnot/commit/7b19f4d66a46c1ef8040afefff5d4327e415b374))
- Chore: add apaleo example partner (oauth + fetch + static)

Demonstrates all three non-stateful patterns in a single partner definition.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([04b9169](https://github.com/edu2105/imnot/commit/04b916939b92d74b2f21555b20cf7140b74d56f5))
- Chore: remove real partner names from README

Replace OHIP-style and Cloudbeds-style labels with neutral descriptive
headings and fictional partner name (ratesync) in async pattern examples.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([6e374a5](https://github.com/edu2105/imnot/commit/6e374a5b4cfafd891cb559e57d83281bf5919de3))
- Chore: remove superpowers plugin output and ignore it

Remove docs/superpowers/ (plugin-generated plans and specs) and add
docs/superpowers/ and superpowers/ to .gitignore to prevent them from
being committed if the plugin is re-enabled.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([84b79fd](https://github.com/edu2105/imnot/commit/84b79fdcb5af67a6f74a0655bf219f736bac92cc))
- Chore: remove poll pattern (replaced by async)

Delete poll.py and test_poll_pattern.py, remove poll import and dispatch
block from router.py, and update stale poll references in comments/docstrings.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([331c610](https://github.com/edu2105/imnot/commit/331c6104df6ec6fe05e0252798d7402b8f6dce11))
- Chore: replace ohip with fictional staylink example partner

Remove Oracle OHIP references (internal company integration) and replace
with a generic StayLink partner demonstrating the same oauth + poll
patterns. Updates all tests, README, smoke script, and loader comments.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([7adba19](https://github.com/edu2105/imnot/commit/7adba19ce3e716b8f037caa0c87aa48c07c44efc))
- Chore: replace leanpms with fictional bookingco example partner

Swap the real LeanPMS partner (internal company API) for a generic
fictional BookingCo partner that demonstrates the same static + fetch
patterns without exposing proprietary endpoint structure.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([d190fa6](https://github.com/edu2105/imnot/commit/d190fa6c14e1ab01345dcc36e320e8bcf641d278))
- Chore: tighten .gitignore

- Add .claude/ (Claude Code local project settings)
- Add .coverage and htmlcov/ (coverage report artefacts)
- Add section comments for clarity
- tests/, scripts/, partners/ remain public — appropriate for open source

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([3a19fff](https://github.com/edu2105/imnot/commit/3a19fff45a1151e9e0504f05829f1f856247677c))
- Chore: exclude CLAUDE.md and PLAN.md from version control

Both files are local session context only and should not be public.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com> ([cdd65c0](https://github.com/edu2105/imnot/commit/cdd65c06a22b9425ea717f6a4f66282e5b1d0844))

