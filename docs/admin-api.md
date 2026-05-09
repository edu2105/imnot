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
