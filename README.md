# Mirage

<p align="center">
  <img src="assets/imnot-logo.png" alt="imnot" width="600"/>
</p>

[![CI](https://github.com/edu2105/imnot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/edu2105/imnot/actions/workflows/ci.yml)

Mirage is a stateful API mock server for integration testing.

Define a partner's API as a YAML file, run `imnot start`, and you get a fully functional
mock server — no code changes required to add new partners or endpoints.

## Why Mirage?

Tools like WireMock, Postman, and Mockoon mock individual HTTP responses. Real partner APIs
don't work that way: they require a specific call sequence, return `202 Accepted` before data
is available, and expect you to poll or wait before fetching a result. Testing against a
stateless stub hides these interaction bugs until you hit production. Mirage models the full
interaction sequence — submit, poll, fetch — so your integration tests reflect what actually
happens when your code talks to a real partner API.

## How it works

- **Partner definitions** live in `partners/<name>/partner.yaml`. Each file declares the
  partner's endpoints, the interaction pattern each endpoint follows, and the expected
  response shape.
- **Patterns** capture common API interaction models:
  - `oauth` — client-credentials token endpoint that returns a static JWT.
  - `static` — endpoint that always returns a fixed JSON body defined in the YAML.
  - `fetch` — synchronous GET that returns the stored payload for a datapoint, with optional session isolation.
  - `async` — flexible N-step async flow defined in YAML: submit → optional status check(s) → fetch result.
  - `push` — Mirage proactively delivers a payload to a callback URL after receiving a submit request.
- **Payload storage** supports two modes:
  - *Global* — one payload per datapoint, last write wins.
  - *Session* — isolated payload per test run, selected via `X-Imnot-Session` header.
- **Admin API** is always available at `/imnot/admin/` for uploading payloads and
  inspecting sessions.

### Interaction sequence (async pattern)

```
Test Harness                       Mirage
     |                               |
     |  POST /admin/.../payload      |   (upload the response payload)
     |------------------------------>|
     |  200 OK                       |
     |<------------------------------|
     |                               |
     |  POST /partner/resource       |   step 1 — submit
     |------------------------------>|
     |  202 Accepted                 |
     |  Location: .../resource/{id}  |
     |<------------------------------|
     |                               |
     |  HEAD /partner/resource/{id}  |   step 2 — status check (optional)
     |------------------------------>|
     |  201  Status: COMPLETED       |
     |<------------------------------|
     |                               |
     |  GET  /partner/resource/{id}  |   step 3 — fetch result
     |------------------------------>|
     |  200  { ...payload }          |
     |<------------------------------|
```

The number and shape of steps is configurable per partner — 2-step, 3-step, and
body-delivered IDs are all supported. See the `async` pattern documentation below.

## Quick start

Requires Python 3.11 or later.

```bash
git clone https://github.com/edu2105/imnot.git
cd imnot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
imnot start
```

Expected output:
```
Starting Mirage on http://127.0.0.1:8000
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

See what endpoints are available (no server needed):
```bash
imnot routes
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

Use `static` instead of `oauth` when the partner token endpoint returns **custom fields**
that don't match the standard `access_token / token_type / expires_in` shape:

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
          my_custom_field: "some-value"
```

Static responses can be updated without restarting the server: edit the YAML, then call
`POST /imnot/admin/reload`.

### `fetch`

Single GET endpoint that returns the stored payload for the datapoint. Supports
`X-Imnot-Session` for test isolation. Use for synchronous read endpoints.

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
curl -X POST http://localhost:8000/imnot/admin/bookingco/charges/payload \
     -H "Content-Type: application/json" \
     -d '{"charges": [{"id": "C1", "amount": 150}]}'

curl http://localhost:8000/bookingco/v1/charges
```

### `async`

Flexible N-step async flow. Use for partners that submit work asynchronously and
return the result via a separate endpoint. Step count and HTTP methods are fully
configurable. Behavior is opt-in via two response flags:

- `generates_id: true` — generate a UUID and deliver it via header or body field
- `returns_payload: true` — return the stored payload for this datapoint

**Header delivery (3 steps):**

```yaml
- name: reservation
  pattern: async
  endpoints:
    - step: 1
      method: POST
      path: /staylink/reservations
      response:
        status: 202
        generates_id: true
        id_header: Location
        id_header_value: /staylink/reservations/{id}
    - step: 2
      method: HEAD
      path: /staylink/reservations/{id}
      response:
        status: 201
        headers:
          Status: COMPLETED
    - step: 3
      method: GET
      path: /staylink/reservations/{id}
      response:
        status: 200
        returns_payload: true
```

**Body delivery (separate status and results endpoints):**

```yaml
- name: rate-push
  pattern: async
  endpoints:
    - step: 1
      method: POST
      path: /ratesync/rates
      response:
        status: 200
        generates_id: true
        id_body_field: JobReferenceID
    - step: 2
      method: GET
      path: /ratesync/jobs/{id}/status
      response:
        status: 200
        body:
          status: COMPLETED
    - step: 3
      method: GET
      path: /ratesync/jobs/{id}/results
      response:
        status: 200
        returns_payload: true
```

### `push`

Mirage receives a submit request, returns immediately, then fires an outbound HTTP call
to a callback URL with the stored payload — simulating the partner calling back your
webhook endpoint.

**Callback URL from request body field:**

```yaml
- name: rate-push
  pattern: push
  endpoints:
    - method: POST
      path: /partner/rates
      response:
        status: 202
        callback_url_field: callbackUrl     # body JSON field containing the callback URL
        callback_method: POST               # default: POST
        callback_delay_seconds: 0           # default: 0 (immediate)
```

**Callback URL from request header:**

```yaml
- name: rate-push
  pattern: push
  endpoints:
    - method: POST
      path: /partner/rates
      response:
        status: 202
        callback_url_header: X-Callback-URL
```

Exactly one of `callback_url_field` or `callback_url_header` is required. The submit
response body always includes a `request_id` (UUID) that can be used with the retrigger
admin endpoint.

**Interaction sequence:**

```
Test Harness                    Mirage                    Test Harness Webhook
     |                             |                               |
     |  POST /admin/.../payload    |                               |
     |---------------------------->|                               |
     |  POST /partner/rates        |                               |
     |  { "callbackUrl": "..." }   |                               |
     |---------------------------->|                               |
     |  202 { "request_id": "..." }|                               |
     |<----------------------------|                               |
     |                             |  POST http://.../webhook      |
     |                             |  { ...payload... }            |
     |                             |------------------------------>|
```

To re-fire the callback without restarting the flow:
```bash
curl -X POST http://localhost:8000/imnot/admin/{partner}/{datapoint}/push/{request_id}/retrigger
```

The retrigger always uses the **current** stored payload, so you can update the payload
between attempts.

## Session-isolated testing

Any `fetch` or `async` endpoint supports session isolation via `X-Imnot-Session`.

```bash
# Upload a session-scoped payload — returns a session_id
SESSION=$(curl -s -X POST http://localhost:8000/imnot/admin/bookingco/charges/payload/session \
               -H "Content-Type: application/json" \
               -d '{"charges": [{"id": "S1"}]}' | jq -r .session_id)

# Use the session in your request
curl http://localhost:8000/bookingco/v1/charges -H "X-Imnot-Session: $SESSION"
```

Multiple test users can run in parallel with isolated payloads — each gets their own `session_id`.

## Admin endpoints

For every `fetch`, `async`, or `push` datapoint, Mirage auto-generates payload endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload` | Upload global payload |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload` | Inspect current global payload |
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload/session` | Upload session payload → returns `session_id` |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload/session/{session_id}` | Inspect a session payload |
| `POST` | `/imnot/admin/{partner}/{datapoint}/push/{request_id}/retrigger` | Re-fire callback for a prior push submit (`push` pattern only) |

`oauth` and `static` datapoints do **not** get payload endpoints — their responses are
fully defined by the YAML and never use the payload store.

Fixed infra endpoints (always available regardless of which partners are loaded):

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/imnot/admin/partners` | List all loaded partners and their datapoints |
| `POST` | `/imnot/admin/partners` | Validate and register a new partner from a raw YAML body — routes go live immediately |
| `GET`  | `/imnot/admin/sessions` | List all active sessions |
| `POST` | `/imnot/admin/reload`   | Hot-reload partner YAMLs without restarting the server |
| `GET`  | `/imnot/admin/postman`  | Download a Postman collection v2.1 JSON for all loaded partners |

`POST /imnot/admin/partners` accepts a raw YAML body (same format as `partner.yaml` files).
Use `?force=true` to overwrite an existing partner. Returns `201` on create, `200` on overwrite,
`409` if the partner already exists without `force`, and `422` for invalid YAML.

> **Note — ephemeral storage:** partners written at runtime are stored on the server's local
> filesystem. In a containerised deployment (Docker, Kubernetes), they will be lost if the pod
> restarts unless the partners directory is backed by a persistent volume. This is an
> infrastructure concern — Mirage does not manage persistence.

Docs endpoints (public, no auth required):

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/imnot/docs` | Serve `README.md` as plain text |
| `GET`  | `/imnot/docs/partners` | Serve `partners/README.md` as plain text |

### Securing admin endpoints

By default admin endpoints are open — suitable for local development only.
When deploying on a shared network, protect them with a Bearer token:

```bash
# via environment variable (recommended)
IMNOT_ADMIN_KEY=your-secret-key imnot start

# or as a CLI flag
imnot start --admin-key your-secret-key
```

All `/imnot/admin/*` requests then require:
```
Authorization: Bearer your-secret-key
```

Consumer endpoints (`/oauth/token`, partner routes, etc.) are never affected.
Set `IMNOT_ADMIN_KEY` in `docker-compose.yml` for Docker deployments.

## CLI

| Command | Description |
|---------|-------------|
| `imnot start` | Load all partner YAMLs and start the server |
| `imnot start --reload` | Start with auto-restart on any YAML change (recommended for development) |
| `imnot generate --file <path>` | Validate and scaffold a partner YAML into `partners/` |
| `imnot generate --file <path> --dry-run --json` | Validate only — print structured result, write nothing |
| `imnot export postman` | Generate a Postman collection v2.1 JSON from all loaded partners |
| `imnot export postman --out <file>` | Write the collection to a specific file (default: `imnot-collection.json`) |
| `imnot export postman --partner <name>` | Include only the named partner (repeatable: `--partner a --partner b`) |
| `imnot status` | Show active sessions in the store |
| `imnot routes` | List all consumer and admin endpoints per partner (works from any subdirectory) |
| `imnot payload get <partner> <datapoint>` | Print the current global payload |
| `imnot payload set <partner> <datapoint> <file>` | Upload a global payload from a JSON file |
| `imnot sessions clear` | Delete all sessions from the store |

`imnot start` accepts `--admin-key` / `IMNOT_ADMIN_KEY` to protect all `/imnot/admin/*` endpoints with a Bearer token.

## Docker

Use Docker when you want to run Mirage as a persistent background service — for example,
on a shared dev server, in CI, or alongside other containers. For local development,
the local install above is simpler.

A pre-built image is published at `ghcr.io/edu2105/imnot:latest`. To use it without
building locally, set the image in `docker-compose.yml`:

```yaml
image: ghcr.io/edu2105/imnot:latest
```

The `partners/` directory and `data/` (SQLite db) are volume-mounted — partners
can be added without rebuilding the image, and state persists across restarts.

```bash
docker compose up                   # start
docker compose restart              # reload after adding a partner YAML
docker compose down                 # stop (data persists in ./data/)
docker compose down -v              # stop and wipe all state
```

The container binds to `127.0.0.1` by default. To expose it on the network,
update `docker-compose.yml` and set an admin key:

```yaml
ports:
  - "0.0.0.0:8000:8000"
environment:
  IMNOT_ADMIN_KEY: "your-secret-key"
```

## Deploy to the cloud

The published Docker image (`ghcr.io/edu2105/imnot`) runs on any container platform.
How you get that container running in your cloud is your domain — the specifics depend
on your provider, infrastructure, and team setup. What Mirage does require, regardless
of where it runs:

- **Persistent storage** — mount a volume at `/app/data` so the SQLite database
  survives container restarts. Without it, all session state is lost on redeploy.
- **Admin key** — set `IMNOT_ADMIN_KEY` via environment variable. Required for
  any deployment reachable outside localhost.
- **Host binding** — pass `--host 0.0.0.0` as the start command so the container
  port is reachable from outside. The default `127.0.0.1` binding blocks external traffic.
- **Partner YAMLs** — either commit them to the repo (included in the image build)
  or mount a volume at `/app/partners` to manage them independently.

## Adding a new partner

### From the CLI (local / development)

Use `imnot generate` to validate and scaffold a partner YAML in one step — no need to know
the directory layout or manually create files.

```bash
# Write your partner.yaml (see partners/README.md for the schema), then:
imnot generate --file /path/to/partner.yaml

# Dry-run first to validate without writing anything:
imnot generate --dry-run --file /path/to/partner.yaml --json
```

`imnot generate` validates the YAML, creates `partners/<name>/` if needed, writes the file,
and prints a summary of all consumer and admin endpoints.

**With `--reload` (recommended for development):** the server picks up the new file and restarts automatically.

**Without `--reload`:** call `POST /imnot/admin/reload` or restart `imnot start`.

### Over HTTP (containerised deployment)

When Mirage runs as a pod or container, use `POST /imnot/admin/partners` to register a new
partner without exec-ing into the container. The endpoint validates the YAML, writes it to
the partners directory, and registers its routes immediately — no restart required.

```bash
curl -X POST http://localhost:8000/imnot/admin/partners \
     -H "Authorization: Bearer $IMNOT_ADMIN_KEY" \
     --data-binary @/path/to/partner.yaml

# Overwrite an existing partner definition:
curl -X POST "http://localhost:8000/imnot/admin/partners?force=true" \
     -H "Authorization: Bearer $IMNOT_ADMIN_KEY" \
     --data-binary @/path/to/partner.yaml
```

`imnot generate` and `POST /imnot/admin/partners` use identical validation — both write the
same `partners/<name>/partner.yaml` file and produce the same JSON result shape.

> **Persistence reminder:** partners written at runtime live on the container's local filesystem.
> Mount a persistent volume at `/app/partners` if you need them to survive restarts.

You can also write the YAML manually. Either way, the directory structure is:

```
partners/
└── mypartner/
    ├── partner.yaml
    └── payloads/       # optional example payload files
```

## Project structure

```
imnot/
├── imnot/
│   ├── api/           # FastAPI app factory
│   ├── engine/
│   │   ├── patterns/  # oauth / static / fetch / async handlers
│   │   ├── router.py  # dynamic route registration
│   │   └── session_store.py  # SQLite persistence
│   ├── loader/        # YAML partner definition parser
│   ├── partners.py    # register_partner() — shared by CLI and HTTP admin endpoint
│   └── cli.py         # imnot CLI
├── partners/
│   ├── staylink/      # StayLink example (oauth + async)
│   │   ├── partner.yaml
│   │   └── payloads/
│   └── bookingco/     # BookingCo example (static token + fetch charges)
│       └── partner.yaml
└── tests/
```

## Limitations & Roadmap

- `push` callbacks have no retry logic — if the callback URL is unreachable, the failure is logged and the retrigger endpoint can be used to re-fire.
- No native HTTPS support — use a reverse proxy (Nginx, Caddy) to terminate TLS.
- No web UI — all admin interactions are via the REST API or CLI.
- XML response bodies are not supported — responses are always JSON.
- No built-in mTLS support.
- Single-node only — the SQLite session store is not shared across instances.

## Contributing

**Run the test suite:**
```bash
pip install -e ".[dev]"
pytest
```

**Add a new pattern:**
Patterns live in `imnot/engine/patterns/`. Each pattern is a module that registers one or
more FastAPI route handlers given an `EndpointDef`. Look at `fetch.py` or `async_.py` for the
interface — the router calls the pattern's handler factory for each datapoint whose pattern
matches. Add your module there and wire it into `router.py`.

**Add a new partner:**
No code required — write a `partner.yaml` under `partners/<name>/`. The full schema and
field reference is in `partners/README.md`.

**Looking for where to start?**
Open issues are tracked at [github.com/edu2105/imnot/issues](https://github.com/edu2105/imnot/issues).
