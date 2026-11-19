# Admin API Reference

All admin endpoints are available at `/imnot/admin/`. They are auth-gated when `IMNOT_ADMIN_KEY` is set.

---

## Payload endpoints

A payload-backed route with nothing uploaded returns `404` with `detail` plus a `hint` field (and an
`X-Imnot-Hint` header) saying exactly which admin call or `payloads/` file fixes it. Uploads are
checked against the datapoint: a `paginated` payload must be a JSON array, and a `fetch` datapoint
with `payload_by` needs a JSON object; anything else is rejected with `422` at upload time.

For every `fetch`, `polling`, `callback`, or `paginated` datapoint, imnot auto-generates payload endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload` | Upload global payload |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload` | Inspect current global payload |
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload/session` | Upload session payload → returns `session_id`. Send an existing id in `X-Imnot-Session` (or `?session=<id>`) to add this datapoint to that session — one id can cover every datapoint a test touches. The id can be your own (1–128 of `A-Z a-z 0-9 . _ : -`), e.g. the test name |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload/session/{session_id}` | Inspect a session payload |
| `POST` | `/imnot/admin/{partner}/{datapoint}/callback/{request_id}/retrigger` | Re-fire callback for a prior submit (`callback` pattern only) |

`oauth` and `static` datapoints do **not** get payload endpoints — their responses are fully defined by the YAML and never use the payload store.

---

## Infrastructure endpoints

Always available regardless of which partners are loaded:

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/healthz` | Health check — always returns `{"status":"ok","version":"…","auth_required":bool,"stateless":bool,"instance":"…"}`, no auth required. `auth_required` tells the admin UI whether to ask for a key; `stateless` is true under `imnot start --stateless`; `instance` is the `--instance-name` label, or `null` |
| `GET`  | `/imnot/admin/partners` | List all loaded partners and their datapoints |
| `POST` | `/imnot/admin/partners` | Validate and register a new partner from a raw YAML body — routes go live immediately. `?force=true` overwrites; `&merge_from=<name>` first copies over that partner's fields the admin UI Builder never writes (`validate`, `fail`, `delay_ms`, `headers`, `payload_by`, `pending`, `callback_method`, descriptions); `&compare_to=<name>` returns `409` with a `dropped` list instead of writing if anything would still be lost. `403` if the partners directory is read-only. In stateless mode nothing is written: the partner is kept in memory (replacing one of the same name loaded from disk) until a reload or restart, and `file`/`directory` in the response are `null` |
| `POST` | `/imnot/admin/partners/examples` | Load the three example partners of `imnot init` (`staylink`, `bookingco`, `ratesync`) with their example payloads; their routes answer immediately. No body. Classic mode writes them to the partners directory like `imnot init`; stateless mode keeps them in memory until a reload or restart. All or nothing: `409` with an `existing` list if any of the three already exists, `403` if the partners directory is read-only. Returns `201 {"status":"ok","partners":[…],"persisted":true|false,"routes_added":[…],"routes_conflicts":[…]}`. Used by the admin UI's empty state |
| `GET`  | `/imnot/admin/partners/{partner_name}` | The partner's full `partner.yaml` as JSON (used by the Builder to pre-fill every field) — `404` if not found. `?format=yaml` returns the YAML text itself as a download |
| `DELETE` | `/imnot/admin/partners/{partner_name}` | Delete the partner's directory and unregister its routes immediately — returns `200 {"status":"ok","partner":"…"}` or `404`; `403` if the directory is read-only. In stateless mode the file stays: the partner is removed from memory and comes back on reload or restart |
| `GET`    | `/imnot/admin/sessions` | List all active sessions with `session_id`, `partner`, `datapoint`, `created_at`, `last_used` |
| `DELETE` | `/imnot/admin/sessions/{session_id}` | Delete a session with all its datapoints — returns `200 {"status":"ok","session_id":"…"}` or `404` |
| `GET`    | `/imnot/admin/requests` | Request journal: what consumers sent to the mock routes, newest first. Filters: `partner`, `datapoint`, `session`, `method`; `limit` 1–1000 (default 50). See [Request journal](#request-journal) |
| `DELETE` | `/imnot/admin/requests` | Clear the journal, or one session's entries with `?session=<id>` — returns `{"status":"ok","deleted":N}` |
| `DELETE` | `/imnot/admin/faults` | Reset every `fail.first_n` counter, so failing endpoints fail again from the first call — returns `{"status":"ok","cleared":N}` |
| `POST` | `/imnot/admin/reload` | Hot-reload partner YAMLs without restarting: updates static bodies and pagination in place, registers new routes, and unregisters routes whose endpoint, datapoint or partner was removed. In stateless mode it first drops every partner created, edited or deleted over HTTP, going back to what the partners directory holds. Returns `added`, `updated`, `removed`, `skipped` (partners whose YAML exists but fails to load keep their current routes; status `partial`) and `conflicts` |
| `GET`  | `/imnot/admin/postman` | Download a Postman collection v2.1 JSON for all loaded partners |
| `GET`  | `/imnot/admin/ui` | Admin web UI (auth-gated, see [Admin UI](#admin-ui)) |

### `GET /imnot/admin/partners` — response shape

Each datapoint in the response includes:
```json
{
  "name": "reservation",
  "pattern": "polling",
  "endpoints": [
    { "method": "POST", "path": "/staylink/reservations", "step": 1 },
    { "method": "HEAD", "path": "/staylink/reservations/{id}", "step": 2 },
    { "method": "GET",  "path": "/staylink/reservations/{id}", "step": 3 }
  ],
  "callback_delay_seconds": null
}
```

`step` is an integer for polling endpoints, `null` otherwise. `callback_delay_seconds` is an integer for callback pattern, `null` otherwise.

### `POST /imnot/admin/partners`

Accepts a raw YAML body (same format as `partner.yaml` files). Use `?force=true` to overwrite an existing partner.

| Status | Meaning |
|--------|---------|
| `201` | Partner created |
| `200` | Partner overwritten (with `?force=true`) |
| `409` | Partner already exists without `?force` |
| `422` | Invalid YAML |

```bash
curl -X POST http://localhost:8000/imnot/admin/partners \
     -H "Authorization: Bearer $IMNOT_ADMIN_KEY" \
     --data-binary @/path/to/partner.yaml

# Overwrite:
curl -X POST "http://localhost:8000/imnot/admin/partners?force=true" \
     -H "Authorization: Bearer $IMNOT_ADMIN_KEY" \
     --data-binary @/path/to/partner.yaml
```

> **Ephemeral storage:** partners registered at runtime live on the container's local filesystem. Mount a persistent volume at `/app/partners` if you need them to survive restarts.

---

## Request journal

imnot records every request sent to a mock route so a test can assert what the integration sent:

```bash
curl -s "http://localhost:8000/imnot/admin/requests?partner=bookingco&session=$SESSION&limit=5"
```

```json
[
  {
    "id": 42, "received_at": "2026-11-17T22:00:00+00:00",
    "partner": "bookingco", "datapoint": "charges", "session_id": "…",
    "method": "POST", "path": "/bookingco/v1/charges", "query": "property=P1",
    "headers": {"content-type": "application/json", "authorization": "[redacted]"},
    "body": "{\"amount\": 100}", "body_truncated": false, "status": 200
  }
]
```

- Recorded: every request outside `/imnot/*`, `/healthz` and FastAPI's docs — including requests
  that match no mock route (`partner: null`, usually a 404), which helps spot a wrong URL.
- Secret headers are saved as `[redacted]`: `Authorization`, `Proxy-Authorization`, `Cookie`,
  `X-Api-Key` and any header whose name contains `token`, `secret`, `password` or `api-key`.
- In the query string, JSON bodies and form bodies (`application/x-www-form-urlencoded`), the value of
  any field whose name contains `token`, `secret`, `password` or `api-key`/`api_key` is saved as
  `[redacted]` (e.g. `client_secret` in a token request). The rest of the body is kept byte for byte;
  other body types and non-string JSON values are stored as sent.
- `body` is the raw request body as text, cut at 64 KB (`body_truncated: true`).
- The newest 1000 entries are kept in `imnot.db`; older ones are dropped automatically.

---

## Docs endpoints

Public, no auth required:

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/imnot/docs` | Serve `README.md` as plain text |
| `GET`  | `/imnot/docs/partners` | Serve `partners/README.md` as plain text |

---

## Securing admin endpoints

By default admin endpoints are open — suitable for local development only. On any shared network, protect them with a Bearer token:

```bash
# Via environment variable (recommended)
IMNOT_ADMIN_KEY=your-secret-key imnot start

# Or as a CLI flag
imnot start --admin-key your-secret-key
```

All `/imnot/admin/*` requests then require:
```
Authorization: Bearer your-secret-key
```

Consumer endpoints (partner routes, `/healthz`) are never affected. Set `IMNOT_ADMIN_KEY` in `docker-compose.yml` for Docker deployments.

- Use a long random key (`openssl rand -hex 32`): a key shorter than 16 characters starts with a warning.
- Failed attempts wait in one shared queue, 0.5 s each, before their `401`, so the key can be tried about twice a second no matter how many clients try at once. Requests with the right key never wait. When the queue is more than 10 s long, a failed attempt gets `429` with `Retry-After` straight away. Nobody is locked out by IP: behind an ingress every client has the same IP.
- `--require-admin-key` / `IMNOT_REQUIRE_ADMIN_KEY=1` makes `imnot start` exit 1 when no key is set, so a shared deployment never comes up with an open admin API.

---

## Load Test endpoints

> **Security warning:** The stress endpoints allow firing high-volume HTTP requests at an arbitrary target URL. Unlike a local tool (`hey`, `wrk`), imnot runs as a persistent server — if exposed to the internet without a strong `IMNOT_ADMIN_KEY`, these endpoints can be used to launch HTTP floods against third-party systems from your host's IP address. **Never expose imnot's admin port publicly without authentication.** Set `IMNOT_ADMIN_KEY` in production and restrict network access to the admin port at the infrastructure level.

All routes under `/imnot/admin/stress/` are auth-gated by the same Bearer token as the rest of the admin API.

### `POST /imnot/admin/stress/run`

Start a new stress run. Returns immediately with a `run_id`; poll `GET /{run_id}` for live progress.

**Standalone mode:**
```json
{
  "mode": "standalone",
  "target_url": "https://api.example.com/webhook",
  "method": "POST",
  "headers": { "X-API-Key": "abc123" },
  "payload_template": "{\"id\": \"{{vary}}\"}",
  "vary_values": ["P001", "P002", "P003"],
  "rate_per_second": 100,
  "total_count": 1000
}
```

**Partner-bound mode** (requires an uploaded global payload for the selected partner/datapoint):
```json
{
  "mode": "partner",
  "partner": "staylink",
  "datapoint": "rate-push",
  "target_url": "https://ingest.example.test/webhook",
  "rate_per_second": 500,
  "total_count": 5000
}
```

Rules:
- Exactly one of `total_count` or `duration_seconds` must be non-null (422 otherwise).
- `rate_per_second` must be a positive number.
- `vary_values`: if provided, values are cycled (`i % len(vary_values)`) and substituted for `{{vary}}` in `payload_template`.
- Partner-bound mode returns 422 immediately if no global payload is uploaded for the selected partner/datapoint.

**Response `201`:**
```json
{ "run_id": "<uuid>", "status": "pending" }
```

### `GET /imnot/admin/stress/{run_id}`

Poll a run for live progress (while running) or final results (after completion).

**While running:**
```json
{
  "run_id": "...",
  "status": "running",
  "fired": 342,
  "success_count": 338,
  "error_count": 4,
  "elapsed_seconds": 3.42,
  "error_breakdown": { "500": 3, "timeout": 1 }
}
```

**Completed:**
```json
{
  "run_id": "...",
  "status": "done",
  "fired": 1000,
  "success_count": 997,
  "error_count": 3,
  "elapsed_seconds": 10.01,
  "p50_ms": 45,
  "p95_ms": 132,
  "p99_ms": 287,
  "actual_rate_per_second": 99.7,
  "duration_seconds": 10.01,
  "error_breakdown": { "500": 2, "timeout": 1 }
}
```

Returns `404` if the run ID is not found. `status` values: `pending | running | done | cancelled | error`.

### `DELETE /imnot/admin/stress/{run_id}`

Cancel a running job. In-flight requests complete normally; the producer loop exits at the next dispatch check.

- `200 {"status": "cancelled", "run_id": "..."}` — cancellation triggered
- `404` — run not found
- `409` — run already in terminal state (`done`, `error`, `cancelled`)

### `GET /imnot/admin/stress/runs`

List the last 50 completed runs from the database. Running jobs are not included; access them via `GET /{run_id}`.

**Response:** array of `{run_id, status, config, results, ran_at}`.

### `GET /imnot/admin/stress/templates`

List all saved templates.

**Response:**
```json
[
  {
    "template_id": "...",
    "name": "My template",
    "config": { ... },
    "created_at": "2026-05-11T..."
  }
]
```

### `POST /imnot/admin/stress/templates`

Save a standalone-mode config as a named template.

```json
{ "name": "My template", "config": { ... } }
```

**Response `201`:** `{ "template_id": "...", "name": "...", "created_at": "..." }`

### `DELETE /imnot/admin/stress/templates/{template_id}`

Delete a saved template. Returns `200 {"status": "ok", "template_id": "..."}` or `404`.

---

## Admin UI

The embedded Admin UI is served at `GET /imnot/admin/ui`. It provides:

- Browse all loaded partners and their datapoints
- Upload and inspect payloads (global or session-scoped)
- Run end-to-end endpoint tests including full polling flows
- Manage active sessions (view and delete)
- Hot-reload YAML without restarting

The UI is enabled by default. Configure under `[ui]` in `imnot.toml`:

```toml
[ui]
# enabled = true                  # set to false to disable (→ 404)
# default_theme = "dark"          # "light", "dark", or "system"
```
