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
| `pattern` | Yes | Must be one of: `oauth`, `poll`, `push` |
| `endpoints` | Yes | At least one required |

**Rule:** one datapoint = one payload stored. If two API resources need separate
payloads, define them as separate datapoints.

---

## Endpoints

Each endpoint maps to one HTTP route registered by Mirage.

```yaml
endpoints:
  - method: <string>        # HTTP verb: GET, POST, HEAD, PUT, PATCH, DELETE
    path: <string>          # URL path, may contain {uuid} placeholder
    step: <int>             # poll pattern only: 1, 2, or 3
    response:               # response configuration (fields vary by pattern)
      status: <int>
      ...
```

| Field | Required | Notes |
|-------|----------|-------|
| `method` | Yes | Case-insensitive, stored as uppercase |
| `path` | Yes | Leading `/` required. Use `{uuid}` for dynamic segments |
| `step` | Poll only | Identifies which step of the poll sequence this endpoint handles |
| `response` | Yes | At minimum must contain `status` |

---

## Patterns

A pattern defines the interaction model between the consumer and the mock.
Choose the pattern that matches how the real partner API behaves.

---

### Pattern: `oauth`

**Use when:** the partner requires a token endpoint that returns an access token.

**How it works:** Mirage returns a static JWT-shaped response. No payload storage involved.

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

### Pattern: `poll`

**Use when:** the partner API is asynchronous — the consumer submits a request,
polls to check if it's ready, then fetches the result.

**How it works:** three coordinated endpoints implement a POST → HEAD → GET sequence.
The consumer drives the sequence; Mirage handles state internally.

**Required endpoints:** exactly three, with `step: 1`, `step: 2`, and `step: 3`.

#### Step 1 — Submit (POST)

Consumer sends a request. Mirage registers it and returns a `Location` header
pointing to the polling URL.

| Response field | Required | Description |
|----------------|----------|-------------|
| `status` | No (default `202`) | HTTP status code |
| `location_template` | Yes | URL template for the Location header. Must contain `{uuid}` |

```yaml
- step: 1
  method: POST
  path: /partner/resources
  response:
    status: 202
    location_template: /partner/resources/{uuid}
```

#### Step 2 — Poll (HEAD)

Consumer checks whether the result is ready. Mirage always signals completion immediately.

| Response field | Required | Description |
|----------------|----------|-------------|
| `status` | No (default `201`) | HTTP status code |
| `headers` | No | Extra response headers as key-value pairs |

```yaml
- step: 2
  method: HEAD
  path: /partner/resources/{uuid}
  response:
    status: 201
    headers:
      Status: COMPLETED
```

#### Step 3 — Fetch (GET)

Consumer retrieves the result. Mirage resolves and returns the stored payload.

| Response field | Required | Description |
|----------------|----------|-------------|
| `status` | No (default `200`) | HTTP status code |

```yaml
- step: 3
  method: GET
  path: /partner/resources/{uuid}
  response:
    status: 200
```

**Session behaviour on step 3:**
- If the request includes `X-Mirage-Session: {session_id}` → returns the session payload
- If no header → returns the global payload
- If the matching payload is not found → returns `404`

**Full poll example:**

```yaml
- name: reservation
  description: Async reservation creation and retrieval
  pattern: poll
  endpoints:
    - step: 1
      method: POST
      path: /ohip/reservations
      response:
        status: 202
        location_template: /ohip/reservations/{uuid}
    - step: 2
      method: HEAD
      path: /ohip/reservations/{uuid}
      response:
        status: 201
        headers:
          Status: COMPLETED
    - step: 3
      method: GET
      path: /ohip/reservations/{uuid}
      response:
        status: 200
```

---

### Pattern: `push`

> **Not yet implemented.** Reserved for future use when Mirage needs to proactively
> deliver a payload to a callback URL after receiving an initial request.

---

## Auto-generated admin endpoints

For every datapoint defined in a partner YAML, Mirage automatically registers these
admin endpoints — no extra YAML required:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mirage/admin/{partner}/{datapoint}/payload` | Upload global payload (last write wins) |
| `GET`  | `/mirage/admin/{partner}/{datapoint}/payload` | Inspect current global payload |
| `POST` | `/mirage/admin/{partner}/{datapoint}/payload/session` | Upload session payload → returns `session_id` |
| `GET`  | `/mirage/admin/{partner}/{datapoint}/payload/session/{session_id}` | Inspect a session payload |

Fixed infra endpoints (always available regardless of partners loaded):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mirage/admin/partners` | List all loaded partners and their datapoints |
| `GET` | `/mirage/admin/sessions` | List all active sessions |

---

## Path parameter rules

- Use `{uuid}` as the dynamic segment in paths for poll steps 2 and 3.
- The same `{uuid}` used in `location_template` (step 1) must appear in the paths
  of steps 2 and 3.
- Do not introduce other path parameters — Mirage currently only resolves `{uuid}`.

**Correct:**
```yaml
location_template: /partner/bookings/{uuid}
# step 2 and 3 path:
path: /partner/bookings/{uuid}
```

**Incorrect:**
```yaml
location_template: /partner/bookings/{id}   # ← wrong placeholder name
```

---

## Checklist before saving a partner.yaml

- [ ] `partner` value is lowercase with no spaces or special characters
- [ ] Each datapoint has a unique `name` within the file
- [ ] `pattern` is one of `oauth`, `poll` (push is reserved)
- [ ] Every `oauth` datapoint has exactly one `POST` endpoint
- [ ] Every `poll` datapoint has exactly three endpoints with `step: 1`, `2`, and `3`
- [ ] Poll step 1 has a `location_template` containing `{uuid}`
- [ ] Poll steps 2 and 3 paths contain `{uuid}`
- [ ] All `response` blocks are nested inside their endpoint, not at the datapoint level
- [ ] No two endpoints across the whole file share the same `method` + `path` combination

---

## Guidance for AI-assisted YAML generation

When generating a `partner.yaml` from a Swagger/OpenAPI spec, Confluence page,
or API documentation, follow this process:

1. **Identify authentication** — if the API uses OAuth 2.0 client credentials,
   map the token endpoint to the `oauth` pattern.

2. **Identify async resources** — if an endpoint returns `202 Accepted` with a
   `Location` header and requires polling, map the full sequence (submit / poll / fetch)
   to the `poll` pattern. All three steps must be defined even if the real API uses
   different status codes — use the actual codes in the `response.status` fields.

3. **One datapoint per independent resource** — if the API has `/reservations` and
   `/guests` as separate async resources with separate payloads, define two datapoints.

4. **Do not invent patterns** — only use patterns listed in this guide. If the API
   behaviour does not fit `oauth` or `poll`, flag it rather than forcing a fit.

5. **Use the checklist above** before finalising the output.
