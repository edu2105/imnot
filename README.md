# Mirage

<p align="center">
  <img src="assets/logo.svg" alt="Mirage logo" width="320"/>
</p>

[![CI](https://github.com/edu2105/mirage/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/edu2105/mirage/actions/workflows/ci.yml)

Mirage is a stateful API mock server for integration testing.

Define a partner's API as a YAML file, run `mirage start`, and you get a fully functional
mock server — no code changes required to add new partners or endpoints.

## How it works

- **Partner definitions** live in `partners/<name>/partner.yaml`. Each file declares the
  partner's endpoints, the interaction pattern each endpoint follows, and the expected
  response shape.
- **Patterns** capture common API interaction models:
  - `oauth` — client-credentials token endpoint that returns a static JWT.
  - `static` — endpoint that always returns a fixed JSON body defined in the YAML.
  - `fetch` — synchronous GET that returns the stored payload for a datapoint, with optional session isolation.
  - `poll` — three-step async flow: submit (POST) → poll for readiness (HEAD) → fetch result (GET).
  - `push` — Mirage proactively delivers a payload to a callback URL (future).
- **Payload storage** supports two modes:
  - *Global* — one payload per datapoint, last write wins.
  - *Session* — isolated payload per test run, selected via `X-Mirage-Session` header.
- **Admin API** is always available at `/mirage/admin/` for uploading payloads and
  inspecting sessions.

## Quick start

**With Docker (recommended):**
```bash
git clone https://github.com/edu2105/mirage.git
cd mirage
docker compose up
```

**Without Docker:**
```bash
pip install -e .
mirage start
```

See what endpoints are available (no server needed):
```bash
mirage routes
```

## Patterns

### `oauth`

Returns a static JWT-shaped response. Use for standard OAuth 2.0 client-credentials token endpoints.

```yaml
- name: token
  pattern: oauth
  endpoints:
    - method: POST
      path: /oauth/token
      response:
        status: 200
        token_type: Bearer
        expires_in: 3600
```

Response body:
```json
{ "access_token": "<static-jwt>", "token_type": "Bearer", "expires_in": 3600 }
```

### `static`

Returns whatever JSON body is defined under `response.body` in the YAML. Use for
non-standard auth endpoints, health checks, or any fixed response.

```yaml
- name: token
  pattern: static
  endpoints:
    - method: POST
      path: /bookingco/auth/token
      response:
        status: 200
        body:
          token: "static-token-replace-in-real-use"
```

### `fetch`

Single GET endpoint that returns the stored payload for the datapoint. Supports
`X-Mirage-Session` for test isolation. Use for synchronous read endpoints.

```yaml
- name: charges
  pattern: fetch
  endpoints:
    - method: GET
      path: /bookingco/v1/charges
      response:
        status: 200
```

Upload a payload first, then GET returns it:
```bash
curl -X POST http://localhost:8000/mirage/admin/bookingco/charges/payload \
     -H "Content-Type: application/json" \
     -d '{"charges": [{"id": "C1", "amount": 150}]}'

curl http://localhost:8000/api/v2/charges
```

### `poll`

Three-step async flow: submit → poll for readiness → fetch result. Use for partners
that return `202 Accepted` and require polling.

```yaml
- name: reservation
  pattern: poll
  endpoints:
    - step: 1
      method: POST
      path: /staylink/reservations
      response:
        status: 202
        location_template: /staylink/reservations/{uuid}
    - step: 2
      method: HEAD
      path: /staylink/reservations/{uuid}
      response:
        status: 201
        headers:
          Status: COMPLETED
    - step: 3
      method: GET
      path: /staylink/reservations/{uuid}
      response:
        status: 200
```

## Session-isolated testing

Any `fetch` or `poll` endpoint supports session isolation via `X-Mirage-Session`.

```bash
# Upload a session-scoped payload — returns a session_id
SESSION=$(curl -s -X POST http://localhost:8000/mirage/admin/bookingco/charges/payload/session \
               -H "Content-Type: application/json" \
               -d '{"charges": [{"id": "S1"}]}' | jq -r .session_id)

# Use the session in your request
curl http://localhost:8000/api/v2/charges -H "X-Mirage-Session: $SESSION"
```

Multiple test users can run in parallel with isolated payloads — each gets their own `session_id`.

## Admin endpoints

For every datapoint, Mirage auto-generates:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mirage/admin/{partner}/{datapoint}/payload` | Upload global payload |
| `GET`  | `/mirage/admin/{partner}/{datapoint}/payload` | Inspect current global payload |
| `POST` | `/mirage/admin/{partner}/{datapoint}/payload/session` | Upload session payload → returns `session_id` |
| `GET`  | `/mirage/admin/{partner}/{datapoint}/payload/session/{session_id}` | Inspect a session payload |

Fixed infra endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mirage/admin/partners` | List all loaded partners and their datapoints |
| `GET` | `/mirage/admin/sessions` | List all active sessions |

## CLI

| Command | Description |
|---------|-------------|
| `mirage start` | Load all partner YAMLs and start the server |
| `mirage status` | Show active sessions in the store |
| `mirage routes` | List all consumer and admin endpoints per partner (no server needed) |
| `mirage payload get <partner> <datapoint>` | Print the current global payload |
| `mirage payload set <partner> <datapoint> <file>` | Upload a global payload from a JSON file |
| `mirage sessions clear` | Delete all sessions from the store |

## Docker

The `partners/` directory and `data/` (SQLite db) are volume-mounted — partners
can be added without rebuilding the image, and state persists across restarts.

```bash
docker compose up                   # start
docker compose restart              # reload after adding a partner YAML
docker compose down                 # stop (data persists in ./data/)
docker compose down -v              # stop and wipe all state
```

## Adding a new partner

Create a directory under `partners/` with a `partner.yaml` file — no code changes required.
See `partners/README.md` for the full authoring guide.

```
partners/
└── mypartner/
    ├── partner.yaml
    └── payloads/       # optional example payload files
```

Restart `mirage start` and the new partner's endpoints are live.

## Project structure

```
mirage/
├── mirage/
│   ├── api/           # FastAPI app factory
│   ├── engine/
│   │   ├── patterns/  # oauth / static / fetch / poll handlers
│   │   ├── router.py  # dynamic route registration
│   │   └── session_store.py  # SQLite persistence
│   ├── loader/        # YAML partner definition parser
│   └── cli.py         # mirage CLI
├── partners/
│   ├── staylink/      # StayLink example (oauth + poll)
│   │   ├── partner.yaml
│   │   └── payloads/
│   └── bookingco/       # BookingCo example (static token + fetch charges)
│       └── partner.yaml
└── tests/
```
