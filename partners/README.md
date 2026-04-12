# Partner YAML Authoring Guide

This guide is the single reference for creating a Mirage partner definition.
Read it fully before writing or generating any `partner.yaml` file.

---

## What is a partner definition?

A partner definition is a YAML file that tells Mirage how to mock an external API.
Mirage reads it at startup and dynamically registers HTTP endpoints — no code changes required.

Each partner lives in its own subdirectory:

```
partners/
└── {partner-name}/
    ├── partner.yaml        ← the definition (required)
    └── payloads/           ← optional example payload files
```

---

## Top-level structure

```yaml
partner: <string>           # unique identifier, lowercase, no spaces (e.g. "ohip", "stripe")
description: <string>       # human-readable description of the partner

datapoints:                 # list of one or more datapoints (see below)
  - ...
```

| Field | Required | Notes |
|-------|----------|-------|
| `partner` | Yes | Used in admin URLs: `/mirage/admin/{partner}/...` |
| `description` | No | Shown in `GET /mirage/admin/partners` |
| `datapoints` | Yes | At least one required |

---

## Datapoints

A datapoint represents one logical capability of the partner API — a resource or
operation that has its own payload and can be mocked independently.

```yaml
datapoints:
  - name: <string>          # unique within the partner, lowercase (e.g. "reservation", "token")
    description: <string>   # human-readable
    pattern: <string>       # interaction pattern — see Patterns section
    endpoints:              # list of HTTP endpoints that implement this datapoint
      - ...
```

| Field | Required | Notes |
|-------|----------|-------|
| `name` | Yes | Used in admin URLs: `/mirage/admin/{partner}/{name}/...` |
| `description` | No | |
| `pattern` | Yes | Must be one of: `oauth`, `async`, `static`, `fetch`, `push` |
| `endpoints` | Yes | At least one required |

**Rule:** one datapoint = one payload stored. If two API resources need separate
payloads, define them as separate datapoints.

---

## Endpoints

Each endpoint maps to one HTTP route registered by Mirage.

```yaml
endpoints:
  - method: <string>        # HTTP verb: GET, POST, HEAD, PUT, PATCH, DELETE
    path: <string>          # URL path, may contain {id} placeholder
    step: <int>             # async pattern only: step number (1, 2, 3, ...)
    response:               # response configuration (fields vary by pattern)
      status: <int>
      ...
```

| Field | Required | Notes |
|-------|----------|-------|
| `method` | Yes | Case-insensitive, stored as uppercase |
| `path` | Yes | Leading `/` required. Use `{id}` for dynamic segments |
| `step` | Async only | Identifies the step number within the async sequence |
| `response` | Yes | At minimum must contain `status` |

---

## Patterns

A pattern defines the interaction model between the consumer and the mock.
Choose the pattern that matches how the real partner API behaves.

---

### Pattern: `oauth`

**Use when:** the partner uses a standard OAuth 2.0 client-credentials token endpoint that
returns a JWT-shaped response (`access_token`, `token_type`, `expires_in`).

**How it works:** Mirage returns a static JWT-shaped response. No payload storage involved.
The `access_token` value is always the same stable token — integration test systems only need
a non-empty Bearer token to proceed.

**If the partner returns custom fields** (e.g. `my_custom_token`, `session_token`) that don't
fit the standard shape, use the `static` pattern with a `body:` block instead.

**Required endpoints:** exactly one `POST` endpoint.

**Response config fields:**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `status` | No | `200` | HTTP status code |
| `token_type` | No | `Bearer` | Value of `token_type` in the response body |
| `expires_in` | No | `3600` | Value of `expires_in` in the response body |

**Example:**

```yaml
- name: token
  description: OAuth 2.0 client credentials token endpoint
  pattern: oauth
  endpoints:
    - method: POST
      path: /oauth/token
      response:
        status: 200
        token_type: Bearer
        expires_in: 3600
```

**Response body returned to consumer:**
```json
{
  "access_token": "<static-jwt>",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

---

### Pattern: `static`

**Use when:** the endpoint always returns a fixed JSON body regardless of input.
Use for non-standard auth endpoints, health checks, or any endpoint with a fully known fixed response.

**How it works:** Mirage returns exactly what is defined under `response.body`. No payload storage.
The response body can be updated without restarting the server: edit the YAML and call
`POST /mirage/admin/reload`.

**Response config fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `status` | Yes | HTTP status code |
| `body` | Yes | JSON body to return verbatim |

**Example — non-standard token endpoint:**

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

**Example — custom token response with non-standard fields** (use this instead of `oauth`):

```yaml
- name: token
  pattern: static
  endpoints:
    - method: POST
      path: /partner/connect/token
      response:
        status: 200
        body:
          access_token: "my-stable-token"
          session_key: "abc123"
          expires_at: 9999999999
```

---

### Pattern: `fetch`

**Use when:** the endpoint is a synchronous GET that returns the stored payload for the datapoint.

**How it works:** consumer uploads a payload via the admin API, then GET returns it.
Supports session isolation via `X-Mirage-Session`.

**Required endpoints:** exactly one `GET` endpoint.

**Example:**

```yaml
- name: charges
  pattern: fetch
  endpoints:
    - method: GET
      path: /bookingco/v1/charges
      response:
        status: 200
```

---

### Pattern: `async`

**Use when:** the partner API is asynchronous — the consumer submits a request and later
fetches the result, with any number of steps in between.

**How it works:** steps are defined as an ordered list in YAML. Behavior is opt-in via
two response-level flags. Mirage never simulates a "not ready yet" state — every status
step responds as completed immediately.

**Required endpoints:** two or more, each with a `step` number.

#### Response flags

| Flag | Step type | Behavior |
|------|-----------|----------|
| `generates_id: true` | Submit | Generate UUID, persist to store, deliver via header or body |
| `returns_payload: true` | Fetch | Validate `{id}` in store (404 if unknown), return session/global payload |
| *(neither)* | Static | Return configured status, headers, and body verbatim |

#### ID delivery (submit step)

**Header delivery** — UUID returned in a response header:

```yaml
response:
  status: 202
  generates_id: true
  id_header: Location
  id_header_value: /partner/resources/{id}
```

`{id}` in `id_header_value` is replaced with the generated UUID at request time.

**Body delivery** — UUID returned as a JSON field in the response body:

```yaml
response:
  status: 200
  generates_id: true
  id_body_field: JobReferenceID
```

One of `id_header` or `id_body_field` is required when `generates_id: true`.

#### Path parameter

Use `{id}` as the dynamic segment in paths for steps that reference the generated UUID.
The same `{id}` token appears in the submit step's `id_header_value` and in subsequent step paths.

---

#### OHIP-style example (header delivery, 3 steps)

```yaml
- name: reservation
  description: Async reservation flow
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

#### Cloudbeds-style example (body delivery, 3 steps)

```yaml
- name: rate-push
  description: Async rate push to Cloudbeds
  pattern: async
  endpoints:
    - step: 1
      method: POST
      path: /cloudbeds/rates
      response:
        status: 200
        generates_id: true
        id_body_field: JobReferenceID

    - step: 2
      method: GET
      path: /cloudbeds/jobs/{id}/status
      response:
        status: 200
        body:
          status: COMPLETED

    - step: 3
      method: GET
      path: /cloudbeds/jobs/{id}/results
      response:
        status: 200
        returns_payload: true
```

#### 2-step example (no status check)

```yaml
- name: booking
  pattern: async
  endpoints:
    - step: 1
      method: POST
      path: /partner/bookings
      response:
        status: 202
        generates_id: true
        id_header: Location
        id_header_value: /partner/bookings/{id}

    - step: 2
      method: GET
      path: /partner/bookings/{id}
      response:
        status: 200
        returns_payload: true
```

**Session behaviour on fetch step:**
- If the request includes `X-Mirage-Session: {session_id}` → returns the session payload
- If no header → returns the global payload
- If the matching payload is not found → returns `404`
- If the path `{id}` was not registered by a prior submit → returns `404`

---

### Pattern: `push`

**Use when:** the partner API calls back your webhook endpoint with a result instead of
waiting for you to poll. You submit a request, the partner returns immediately, and later
POSTs the result to a URL you provided.

**How it works:** Mirage receives the submit request, extracts the callback URL (from a
body field or header), stores the request, returns the configured status code with a
`request_id`, then fires an outbound HTTP call to the callback URL with the stored payload.

**Required endpoints:** exactly one endpoint (the submit).

**Response config fields:**

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `status` | No | `202` | HTTP status code returned to the submitter |
| `callback_url_field` | One of these two | — | JSON body field in the submit request that contains the callback URL |
| `callback_url_header` | One of these two | — | Request header that contains the callback URL |
| `callback_method` | No | `POST` | HTTP method used for the outbound callback |
| `callback_delay_seconds` | No | `0` | Seconds to wait before firing the callback |

Exactly one of `callback_url_field` or `callback_url_header` must be present — specifying
both or neither is a validation error caught at startup.

**Example — callback URL in request body:**

```yaml
- name: rate-push
  description: Partner confirms rate update via webhook
  pattern: push
  endpoints:
    - method: POST
      path: /partner/rates
      response:
        status: 202
        callback_url_field: callbackUrl
        callback_method: POST
        callback_delay_seconds: 0
```

Submit request your consumer sends:
```json
{ "callbackUrl": "http://your-service/webhook", "rates": [...] }
```

Mirage returns:
```json
{ "request_id": "<uuid>" }
```

Then fires `POST http://your-service/webhook` with the stored payload.

**Example — callback URL in request header:**

```yaml
- name: rate-push
  description: Partner confirms rate update via webhook
  pattern: push
  endpoints:
    - method: POST
      path: /partner/rates
      response:
        status: 202
        callback_url_header: X-Callback-URL
```

**Retrigger admin endpoint:**

For every `push` datapoint, Mirage registers an additional admin route:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mirage/admin/{partner}/{datapoint}/push/{request_id}/retrigger` | Re-fire the callback for a prior submit |

Use this when the callback failed or you need to test how your service handles a repeated
delivery, without restarting the whole flow. The retrigger always uses the **current**
stored payload, so you can update the payload between attempts.

```bash
curl -X POST http://localhost:8000/mirage/admin/partner/rate-push/push/<request_id>/retrigger
```

**Session behaviour:**
- `X-Mirage-Session` on the submit request → session payload used for the callback
- No session header → global payload used
- No payload found → callback is skipped (warning logged); submit still returns the configured status
- The retrigger uses the `session_id` from the original submit — no need to re-specify it

---

## Auto-generated admin endpoints

For every `fetch`, `async`, or `push` datapoint, Mirage automatically registers these
admin endpoints — no extra YAML required:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mirage/admin/{partner}/{datapoint}/payload` | Upload global payload (last write wins) |
| `GET`  | `/mirage/admin/{partner}/{datapoint}/payload` | Inspect current global payload |
| `POST` | `/mirage/admin/{partner}/{datapoint}/payload/session` | Upload session payload → returns `session_id` |
| `GET`  | `/mirage/admin/{partner}/{datapoint}/payload/session/{session_id}` | Inspect a session payload |

`oauth` and `static` datapoints do **not** get these endpoints. Their responses are fully
defined by the YAML and never use the payload store.

Fixed infra endpoints (always available regardless of partners loaded):

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/mirage/admin/partners` | List all loaded partners and their datapoints |
| `GET`  | `/mirage/admin/sessions` | List all active sessions |
| `POST` | `/mirage/admin/reload`   | Hot-reload partner YAMLs — updates static response bodies in place, registers new partners/datapoints |

---

## Checklist before saving a partner.yaml

- [ ] `partner` value is lowercase with no spaces or special characters
- [ ] Each datapoint has a unique `name` within the file
- [ ] `pattern` is one of `oauth`, `async`, `static`, `fetch`, `push`
- [ ] If the token endpoint returns non-standard fields, use `static` not `oauth`
- [ ] Every `oauth` datapoint has exactly one `POST` endpoint
- [ ] Every `async` datapoint has at least two endpoints, each with a unique `step` number
- [ ] The async submit step has `generates_id: true` with either `id_header` or `id_body_field`
- [ ] If `id_header` is used, `id_header_value` contains `{id}`
- [ ] Async steps that reference the generated UUID use `{id}` in their path
- [ ] The async fetch step has `returns_payload: true`
- [ ] Every `push` datapoint has exactly one endpoint with exactly one of `callback_url_field` or `callback_url_header` set (not both, not neither)
- [ ] All `response` blocks are nested inside their endpoint, not at the datapoint level
- [ ] No two endpoints across the whole file share the same `method` + `path` combination
- [ ] No endpoint in this file shares `method` + `path` with an endpoint in any other partner file — Mirage enforces this at startup and will refuse to start if a conflict is detected
- [ ] After saving, call `POST /mirage/admin/reload` or restart the server to pick up changes

---

## Guidance for AI-assisted YAML generation

When generating a `partner.yaml` from a Swagger/OpenAPI spec, Confluence page,
or API documentation, follow this process:

1. **Identify authentication** — if the API uses OAuth 2.0 client credentials and returns
   the standard `access_token / token_type / expires_in` shape, use the `oauth` pattern.
   If the token response contains **any custom fields**, use `static` with a `body:` block.

2. **Identify async resources** — if an endpoint submits work and the result is fetched
   later (by polling a status endpoint or following a location header), map the full
   sequence to the `async` pattern. Define as many steps as the real API uses.

3. **Identify sync resources** — if an endpoint simply returns the current state of a
   resource, use the `fetch` pattern.

4. **One datapoint per independent resource** — if the API has `/reservations` and
   `/guests` as separate resources with separate payloads, define two datapoints.

5. **Do not invent patterns** — only use patterns listed in this guide. If the API
   behaviour does not fit any listed pattern, flag it rather than forcing a fit.

6. **Use the checklist above** before finalising the output.
