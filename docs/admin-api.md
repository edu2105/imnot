# Admin API Reference

All admin endpoints are available at `/imnot/admin/`. They are auth-gated when `IMNOT_ADMIN_KEY` is set.

---

## Payload endpoints

For every `fetch`, `polling`, `callback`, or `paginated` datapoint, imnot auto-generates payload endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload` | Upload global payload |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload` | Inspect current global payload |
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload/session` | Upload session payload → returns `session_id` |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload/session/{session_id}` | Inspect a session payload |
| `POST` | `/imnot/admin/{partner}/{datapoint}/callback/{request_id}/retrigger` | Re-fire callback for a prior submit (`callback` pattern only) |

`oauth` and `static` datapoints do **not** get payload endpoints — their responses are fully defined by the YAML and never use the payload store.

---

## Infrastructure endpoints

Always available regardless of which partners are loaded:

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/healthz` | Health check — always returns `{"status":"ok","version":"…"}`, no auth required |
| `GET`  | `/imnot/admin/partners` | List all loaded partners and their datapoints |
| `POST` | `/imnot/admin/partners` | Validate and register a new partner from a raw YAML body — routes go live immediately |
| `GET`    | `/imnot/admin/sessions` | List all active sessions with `session_id`, `partner`, `datapoint`, `created_at`, `last_used` |
| `DELETE` | `/imnot/admin/sessions/{session_id}` | Delete a single session — returns `200 {"status":"ok","session_id":"…"}` or `404` |
| `POST` | `/imnot/admin/reload` | Hot-reload partner YAMLs without restarting |
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

---

## Load Test endpoints

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
  "target_url": "https://nifi.internal/webhook",
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
