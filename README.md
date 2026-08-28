# imnot

<p align="center">
  <img src="assets/imnot-logo.svg" alt="imnot — stateful API mock server" width="400" height="300"/>
</p>

[![CI](https://github.com/edu2105/imnot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/edu2105/imnot/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/edu2105/imnot/branch/main/graph/badge.svg)](https://codecov.io/gh/edu2105/imnot)
[![PyPI version](https://badge.fury.io/py/imnot.svg)](https://badge.fury.io/py/imnot)

**YAML in. Mock server out.** Define external APIs in a single file, run `imnot start`, and get a fully functional local mock server — stateful flows, session isolation, and an Admin UI included. No code required.

<!-- Screenshot: add assets/admin-ui.png once available -->

---

## Why imnot?

- **Zero code.** One YAML file per external API. No JVM, no framework, no boilerplate.
- **Stateful, not just stubbed.** OAuth, polling, callbacks, paginated lists, and per-test session isolation — all modeled in YAML.
- **Validation-aware.** Declare field rules in YAML — imnot rejects malformed requests with realistic 422 errors before returning a mock response.
- **Rate-limit aware.** Declare a `requests_per_minute` ceiling on `fetch` endpoints — imnot enforces it with a token bucket and returns realistic `429` responses with a `Retry-After` header.
- **Ships with your tests.** Partner definitions are version-controlled alongside the integration they test and run anywhere Docker runs.

---

## Quick start

Requires Python 3.11+.

```bash
pipx install imnot
imnot init
imnot start
```

> `pipx` installs CLI tools into isolated environments. Alternatively: `pip install imnot` inside an existing virtual environment.

`imnot init` creates a `partners/` directory with two working example partners (`staylink` and `bookingco`) that cover all six patterns. Edit or replace them whenever you're ready.

---

## Patterns

| Pattern | What it mocks |
|---------|--------------|
| `oauth` | Client-credentials token endpoint — returns a standard JWT |
| `static` | Any fixed-response endpoint — health checks, custom auth, lookup tables |
| `fetch` | Synchronous GET that returns an uploaded payload |
| `polling` | N-step async flow: submit → status check(s) → fetch result |
| `callback` | Webhook simulation — imnot fires the outbound call after receiving a submit |
| `paginated` | Paginated list endpoints (offset/limit, cursor, or page-number) sliced from an uploaded array at request time |

All `fetch`, `polling`, and `paginated` endpoints support `X-Imnot-Session` for per-test isolation — parallel test runs stay independent.

→ [Full pattern reference with YAML examples](docs/patterns.md)

---

## Admin UI

imnot ships an embedded Admin UI at `GET /imnot/admin/ui`. No setup required — it's enabled by default and auth-gated by the same Bearer token as the rest of the admin API.

From the browser you can:

- Browse loaded partners and their datapoints
- Upload and inspect payloads (global or session-scoped)
- Run end-to-end endpoint tests — including full polling flows
- Manage active sessions
- Hot-reload YAML without restarting the server
- Run load tests against any HTTP endpoint (standalone or partner-bound)

→ [Load Test reference](docs/load-test.md)

---

## AI-ready

Don't want to write the YAML yourself? Paste one of these into Claude, ChatGPT, or your AI assistant:

**From a description:**
```
I use imnot to mock external APIs for integration testing.
Generate a partner.yaml file in imnot format for [service name].
Schema reference: https://github.com/edu2105/imnot/blob/main/partners/README.md
Endpoints to mock: [describe them]
Output only the YAML — no code, no explanation.
```

**From an OpenAPI spec:**
```
I use imnot to mock external APIs for integration testing.
Convert this OpenAPI spec into a partner.yaml file in imnot format.
Schema: https://github.com/edu2105/imnot/blob/main/partners/README.md
Output only the YAML — no code, no explanation.
[paste your spec here]
```

---

## Learn more

| Topic | Doc |
|-------|-----|
| Pattern reference | [docs/patterns.md](docs/patterns.md) |
| Admin API reference | [docs/admin-api.md](docs/admin-api.md) |
| Load Test | [docs/load-test.md](docs/load-test.md) |
| CLI & configuration | [docs/cli.md](docs/cli.md) |
| Docker & deployment | [docs/deployment.md](docs/deployment.md) |
| Partner YAML schema | [partners/README.md](partners/README.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |

---

## Limitations

- **Callback retries** — no built-in retry logic; use the retrigger endpoint to re-fire.
- **JSON only** — response bodies are always JSON, no XML support.
- **Single-node** — SQLite session store is not shared across instances.
- **Admin UI** — desktop layout only; no mobile breakpoints.
- **No native TLS** — use a reverse proxy (Nginx, Caddy) to terminate HTTPS.
