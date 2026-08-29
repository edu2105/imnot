# Partner YAML Authoring Guide

This guide is the single reference for creating a imnot partner definition.
Read it fully before writing or generating any `partner.yaml` file.

---

## What is a partner definition?

A partner definition is a YAML file that tells imnot how to mock an external API.
imnot reads it at startup and dynamically registers HTTP endpoints — no code changes required.

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
partner: <string>           # unique identifier — letters, digits, hyphens, underscores only; max 64 chars (e.g. "staylink", "bookingco")
description: <string>       # human-readable description of the partner

datapoints:                 # list of one or more datapoints (see below)
  - ...
```

| Field | Required | Notes |
|-------|----------|-------|
| `partner` | Yes | Used in admin URLs: `/imnot/admin/{partner}/...`; must match `^[a-zA-Z0-9_-]{1,64}$` |
| `description` | No | Shown in `GET /imnot/admin/partners` |
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
| `name` | Yes | Used in admin URLs: `/imnot/admin/{partner}/{name}/...` |
| `description` | No | |
| `pattern` | Yes | Must be one of: `oauth`, `polling`, `static`, `fetch`, `callback`, `paginated` |
| `endpoints` | Yes | At least one required |

**Rule:** one datapoint = one payload stored. If two API resources need separate
payloads, define them as separate datapoints.

---

## Endpoints

Each endpoint maps to one HTTP route registered by imnot.

```yaml
endpoints:
  - method: <string>        # HTTP verb: GET, POST, HEAD, PUT, PATCH, DELETE
    path: <string>          # URL path, may contain {id} placeholder
    step: <int>             # polling pattern only: step number (1, 2, 3, ...)
    response:               # response configuration (fields vary by pattern)
      status: <int>
      ...
    validate:               # optional; see Request validation section
      body:
        <field>: {required: true, type: string}
      query:
        <param>: {required: true, type: integer, min: 1}
      headers:
        <header>: {required: true, pattern: '^prefix-'}
```

| Field | Required | Notes |
|-------|----------|-------|
| `method` | Yes | Case-insensitive, stored as uppercase |
| `path` | Yes | Leading `/` required. Use `{id}` for dynamic segments |
| `step` | Polling only | Identifies the step number within the polling sequence |
| `response` | Yes | At minimum must contain `status` |
| `validate` | No | Request validation rules — see [Request validation](#request-validation) section |
| `rate_limit` | No | Requests-per-minute ceiling — `fetch` pattern only, see [Rate limiting](#rate-limiting) section |

---

## Patterns

A pattern defines the interaction model between the consumer and the mock.
Choose the pattern that matches how the real partner API behaves.

---

### Pattern: `oauth`

**Use when:** the partner uses a standard OAuth 2.0 client-credentials token endpoint that
returns a JWT-shaped response (`access_token`, `token_type`, `expires_in`).

**How it works:** imnot returns a static JWT-shaped response. No payload storage involved.
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

**How it works:** imnot returns exactly what is defined under `response.body`. No payload storage.
The response body can be updated without restarting the server: edit the YAML and call
`POST /imnot/admin/reload`.

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
Supports session isolation via `X-Imnot-Session`.

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

### Pattern: `polling`

**Use when:** the partner API is asynchronous — the consumer submits a request and later
fetches the result, with any number of steps in between.

**How it works:** steps are defined as an ordered list in YAML. Behavior is opt-in via
two response-level flags. imnot never simulates a "not ready yet" state — every status
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

#### StayLink-style example (header delivery, 3 steps)

```yaml
- name: reservation
  description: Polling-based reservation flow
  pattern: polling
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

#### BookingCo-style example (body delivery, 3 steps)

```yaml
- name: rate-push
  description: Polling-based rate push to BookingCo
  pattern: polling
  endpoints:
    - step: 1
      method: POST
      path: /bookingco/rates
      response:
        status: 200
        generates_id: true
        id_body_field: JobReferenceID

    - step: 2
      method: GET
      path: /bookingco/jobs/{id}/status
      response:
        status: 200
        body:
          status: COMPLETED

    - step: 3
      method: GET
      path: /bookingco/jobs/{id}/results
      response:
        status: 200
        returns_payload: true
```

#### 2-step example (no status check)

```yaml
- name: booking
  pattern: polling
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
- If the request includes `X-Imnot-Session: {session_id}` → returns the session payload
- If no header → returns the global payload
- If the matching payload is not found → returns `404`
- If the path `{id}` was not registered by a prior submit → returns `404`

---

### Pattern: `callback`

**Use when:** the partner API calls back your webhook endpoint with a result instead of
waiting for you to poll. You submit a request, the partner returns immediately, and later
POSTs the result to a URL you provided.

**How it works:** imnot receives the submit request, extracts the callback URL (from a
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
  pattern: callback
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

imnot returns:
```json
{ "request_id": "<uuid>" }
```

Then fires `POST http://your-service/webhook` with the stored payload.

**Example — callback URL in request header:**

```yaml
- name: rate-push
  description: Partner confirms rate update via webhook
  pattern: callback
  endpoints:
    - method: POST
      path: /partner/rates
      response:
        status: 202
        callback_url_header: X-Callback-URL
```

**Retrigger admin endpoint:**

For every `callback` datapoint, imnot registers an additional admin route:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/imnot/admin/{partner}/{datapoint}/callback/{request_id}/retrigger` | Re-fire the callback for a prior submit |

Use this when the callback failed or you need to test how your service handles a repeated
delivery, without restarting the whole flow. The retrigger always uses the **current**
stored payload, so you can update the payload between attempts.

```bash
curl -X POST http://localhost:8000/imnot/admin/partner/rate-push/callback/<request_id>/retrigger
```

**Session behaviour:**
- `X-Imnot-Session` on the submit request → session payload used for the callback
- No session header → global payload used
- No payload found → callback is skipped (warning logged); submit still returns the configured status
- The retrigger uses the `session_id` from the original submit — no need to re-specify it

---

### Pattern: `paginated`

**Use when:** the endpoint returns a list of items that consumers page through. Supports
`offset/limit`, `cursor`, `page-number`, and `page-number-URL` (DRF-style `next`/`previous`
links) styles.

**How it works:** you upload an array payload (the full dataset) via the admin API; imnot
slices it at request time and wraps the slice in an envelope whose field names you define in
the `pagination:` block. Supports session isolation via `X-Imnot-Session` — two test sessions
can hold independent datasets.

**Required endpoints:** at least one endpoint (typically a `GET`).

**Required YAML block:** `pagination:` must be present alongside `endpoints:`.

**Pagination config fields:**

| Field | Required | Style | Description |
|-------|----------|-------|-------------|
| `style` | Yes | all | Must be `offset_limit`, `cursor`, `page_number`, or `page_number_url` |
| `items_field` | Yes | all | Top-level response key that holds the item array (e.g. `items`, `results`, `data`) |
| `total_field` | No | all | Top-level response key for total dataset count |
| `has_more_field` | No | all | Top-level response key for boolean "more pages exist" flag |
| `next_offset_field` | No | `offset_limit` | Top-level response key for the next page's offset value (null when no more pages); silently ignored for `page_number` |
| `cursor_field` | Yes (cursor only) | `cursor` | Response key that carries the next-page cursor token (e.g. `nextCursor`); always present, `null` on last page |
| `cursor_ttl_seconds` | No | `cursor` | Seconds before a cursor expires (default 3600); `0` means never expires |
| `page_param` | No | `page_number`, `page_number_url` | Query parameter name for the page number (default `"page"`) |
| `size_param` | No | `page_number`, `page_number_url` | Query parameter name for the page size (default `"size"`) |
| `next_url_field` | Yes (`page_number_url` only) | `page_number_url` | Top-level response key for the absolute URL to the next page (null on last page) |
| `previous_url_field` | Yes (`page_number_url` only) | `page_number_url` | Top-level response key for the absolute URL to the previous page (null on first page) |
| `total_pages` | No | `page_number_url` | Report a fixed total page count independent of the uploaded array length; `has_more`/`next` become `page < total_pages` instead of being derived from array length. Recognized (inert) on other styles. |

**Query parameters — `offset_limit` style:**

| Param | Default | Behavior |
|-------|---------|----------|
| `offset` | `0` | Start position (0-based). Negative values treated as 0 |
| `limit` | `default_limit` (50) | Page size. Values ≤ 0 fall back to `default_limit` |

**Query parameters — `cursor` style:**

| Param | Default | Behavior |
|-------|---------|----------|
| `cursor` | (absent = first page) | Opaque cursor token returned by the previous response |
| `limit` | `default_limit` (50) | Page size |

**Query parameters — `page_number` style:**

| Param | Default | Behavior |
|-------|---------|----------|
| `page` (or `page_param` value) | `1` | 1-indexed page number. Values < 1 clamped to 1 |
| `size` (or `size_param` value) | `default_limit` (50) | Page size |

`default_limit` is configurable via `imnot.toml` `[pagination] default_limit`.

**Out-of-bounds:** if the requested page or offset is past the end of the dataset, the
response returns an empty array and `hasMore: false` — no error.

**Payload validation:** the uploaded payload must be a JSON **array**. If it is not, the
handler returns `422` with `"Payload must be a JSON array for the paginated pattern"`.

**Example — `offset_limit`:**

```yaml
- name: listing
  description: Paginated property listings (offset/limit)
  pattern: paginated
  endpoints:
    - method: GET
      path: /ratesync/listings
      response:
        status: 200
  pagination:
    style: offset_limit
    items_field: results
    total_field: total
    has_more_field: hasMore
    next_offset_field: nextOffset
```

Upload the dataset:
```bash
curl -X POST http://localhost:8000/imnot/admin/ratesync/listing/payload \
  -H "Content-Type: application/json" \
  -d '[{"id":1,"name":"Apt A"},{"id":2,"name":"Apt B"},{"id":3,"name":"Apt C"}]'
```

Request the first page:
```bash
curl "http://localhost:8000/ratesync/listings?offset=0&limit=2"
```

Response:
```json
{
  "results": [{"id":1,"name":"Apt A"},{"id":2,"name":"Apt B"}],
  "total": 3,
  "hasMore": true,
  "nextOffset": 2
}
```

**Example — `cursor`:**

```yaml
- name: listing
  description: Paginated property listings (cursor)
  pattern: paginated
  endpoints:
    - method: GET
      path: /ratesync/listings
      response:
        status: 200
  pagination:
    style: cursor
    items_field: results
    cursor_field: nextCursor
    cursor_ttl_seconds: 1800
    has_more_field: hasMore
```

Upload the dataset:
```bash
curl -X POST http://localhost:8000/imnot/admin/ratesync/listing/payload \
  -H "Content-Type: application/json" \
  -d '[{"id":1,"name":"Apt A"},{"id":2,"name":"Apt B"},{"id":3,"name":"Apt C"}]'
```

First request (no cursor):
```bash
curl "http://localhost:8000/ratesync/listings?limit=2"
```

Response:
```json
{
  "results": [{"id": 1, "name": "Apt A"}, {"id": 2, "name": "Apt B"}],
  "nextCursor": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "hasMore": true
}
```

Next page (pass the cursor from the previous response):
```bash
curl "http://localhost:8000/ratesync/listings?limit=2&cursor=a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

Response:
```json
{
  "results": [{"id": 3, "name": "Apt C"}],
  "nextCursor": null,
  "hasMore": false
}
```

**Example — `page_number`:**

```yaml
- name: listing
  description: Paginated property listings (page number)
  pattern: paginated
  endpoints:
    - method: GET
      path: /ratesync/listings
      response:
        status: 200
  pagination:
    style: page_number
    items_field: results
    page_param: pageNum
    size_param: perPage
    total_field: total
    has_more_field: hasMore
```

Upload the dataset:
```bash
curl -X POST http://localhost:8000/imnot/admin/ratesync/listing/payload \
  -H "Content-Type: application/json" \
  -d '[{"id":1,"name":"Apt A"},{"id":2,"name":"Apt B"},{"id":3,"name":"Apt C"}]'
```

First page:
```bash
curl "http://localhost:8000/ratesync/listings?pageNum=1&perPage=2"
```

Response:
```json
{
  "results": [{"id": 1, "name": "Apt A"}, {"id": 2, "name": "Apt B"}],
  "total": 3,
  "hasMore": true
}
```

Second page:
```bash
curl "http://localhost:8000/ratesync/listings?pageNum=2&perPage=2"
```

Response:
```json
{
  "results": [{"id": 3, "name": "Apt C"}],
  "total": 3,
  "hasMore": false
}
```

**Example — `page_number_url`:**

Reproduces Django REST Framework's `PageNumberPagination` envelope: absolute `next`/`previous`
URL strings instead of an opaque cursor or a `hasMore` boolean. URLs are built from
`app.state.base_url` (not the incoming request's `Host` header), so they stay externally
reachable even when imnot runs behind Docker or EKS.

```yaml
- name: listing
  description: Paginated property listings (DRF-style page-number URLs)
  pattern: paginated
  endpoints:
    - method: GET
      path: /ratesync/listings
      response:
        status: 200
  pagination:
    style: page_number_url
    items_field: results
    total_field: count
    next_url_field: next
    previous_url_field: previous
```

Upload the dataset:
```bash
curl -X POST http://localhost:8000/imnot/admin/ratesync/listing/payload \
  -H "Content-Type: application/json" \
  -d '[{"id":1,"name":"Apt A"},{"id":2,"name":"Apt B"},{"id":3,"name":"Apt C"}]'
```

First page:
```bash
curl "http://localhost:8000/ratesync/listings?page=1&size=2"
```

Response:
```json
{
  "count": 3,
  "next": "http://localhost:8000/ratesync/listings?page=2&size=2",
  "previous": null,
  "results": [{"id": 1, "name": "Apt A"}, {"id": 2, "name": "Apt B"}]
}
```

Follow the `next` URL:
```bash
curl "http://localhost:8000/ratesync/listings?page=2&size=2"
```

Response (last page — `next` is now `null`, `previous` points back at page 1):
```json
{
  "count": 3,
  "next": null,
  "previous": "http://localhost:8000/ratesync/listings?page=1&size=2",
  "results": [{"id": 3, "name": "Apt C"}]
}
```

**Fixed page count independent of uploaded data (`total_pages`):**

```yaml
  pagination:
    style: page_number_url
    items_field: results
    next_url_field: next
    previous_url_field: previous
    total_pages: 5
```

With `total_pages: 5`, every request (page 1 through page 5) returns the full uploaded array as
`results`, and `next` stays populated through page 4, becoming `null` only at `page=5` —
regardless of how many items were actually uploaded. Useful for testing "does my consumer stop
after N pages" without uploading N pages of realistic data. Requests for `page=6` and beyond are
tolerated the same as any other out-of-range page (full array still returned, `next: null`, no
error).

---

## Request validation

Any endpoint can declare a `validate:` block. imnot checks the request at the configured endpoint before returning the mock response; any violation produces a `422` with a list of error strings — no mock response is returned.

Validation is **opt-in**: absence of `validate:` means no validation is applied.

### Structure

```yaml
validate:
  body:                     # checks JSON request body fields (parsed as dict)
    <field-name>:
      required: true        # missing field → error
      type: string          # type mismatch → error
      allowed: [a, b, c]   # value not in list → error
      pattern: '^[A-Z]+'   # string not matching regex → error
      min: 1               # numeric value below min → error
      max: 100             # numeric value above max → error
  query:                    # checks URL query parameters (always strings; coerced for type checks)
    <param-name>:
      <same rule attributes as body>
  headers:                  # checks request headers (always strings; coerced for type checks)
    <header-name>:
      <same rule attributes as body>
```

### Rule attributes

| Attribute | Applies to | Description |
|-----------|-----------|-------------|
| `required` | body / query / headers | `true` → missing field is an error. Default: `false` |
| `type` | body / query / headers | Expected type: `string`, `integer`, `number`, `boolean`, `array`, `object`. Query and header values (always strings) are coerced before the type check |
| `allowed` | body / query / headers | List of permitted values. Value not in the list → error |
| `pattern` | string fields | Python-style regex. Applied only when value is a string; non-strings produce a type error first |
| `min` | numeric fields | Minimum value (inclusive) |
| `max` | numeric fields | Maximum value (inclusive) |

All violations are collected before returning — the `detail` list contains every error found, not just the first one.

### 422 response shape

```json
{
  "detail": [
    "body.reservation_id: required",
    "body.nights: must be at least 1",
    "headers.X-Partner-ID: does not match pattern '^P-[0-9]+'"
  ]
}
```

Error message format: `"<section>.<field>: <reason>"` where `section` is `body`, `query`, or `headers`.

### Example

```yaml
- name: reservation
  pattern: fetch
  endpoints:
    - method: POST
      path: /partner/reservations
      validate:
        body:
          reservation_id:
            required: true
            type: string
          nights:
            required: true
            type: integer
            min: 1
            max: 365
          status:
            type: string
            allowed: [pending, confirmed, cancelled]
        query:
          currency:
            type: string
            allowed: [USD, EUR, GBP]
        headers:
          X-Partner-ID:
            required: true
            pattern: '^P-[0-9]+'
      response:
        status: 200
```

### Notes

- `validate:` is per-endpoint, not per-datapoint. Different endpoints within a polling datapoint (submit POST vs. fetch GET) can have independent rule sets.
- `static` endpoints support `validate:`. If validation rules change, a server restart is required — `POST /imnot/admin/reload` updates the response body only.
- Unknown top-level keys under `validate:` (anything other than `body`, `query`, `headers`) raise a `ValueError` at startup.
- Unknown rule attributes under a field raise a `ValueError` at startup.

---

## Rate limiting

`fetch`-pattern endpoints can declare a `rate_limit:` block. imnot enforces a requests-per-minute ceiling with a token bucket; once exceeded, it returns `429` with a `Retry-After` header instead of the mock response — checked before `validate:` and before any payload/session work.

Rate limiting is **opt-in**: absence of `rate_limit:` means no limit is applied.

### Structure

```yaml
rate_limit:
  requests_per_minute: <positive integer>
```

`requests_per_minute` is the only recognized key. The bucket is shared across all callers of the endpoint — the key is `(partner, datapoint, method, path)`, not the caller's session — the same way a real partner enforces a ceiling per API credential, not per individual test.

### 429 response shape

```json
{
  "detail": "Rate limit exceeded: 60 requests per minute"
}
```

The response also includes a `Retry-After` header (seconds, integer) telling the caller how long to wait before the bucket refills enough to allow another request.

### Example

```yaml
- name: quotes
  pattern: fetch
  endpoints:
    - method: GET
      path: /partner/quotes
      rate_limit:
        requests_per_minute: 60
      response:
        status: 200
```

### Notes

- **v1 scope: `fetch` pattern, plus `paginated` endpoints using `pagination.style: page_number_url`.** Declaring `rate_limit:` on any other pattern, or on a `paginated` endpoint using any other pagination style (`offset_limit`, `cursor`, plain `page_number`), raises a `ValueError` at startup.
- Bucket state is in-memory only — it resets on every server restart (including `--reload` dev-mode restarts) and is not shared across multiple imnot instances.
- `rate_limit:` is not hot-reloadable via `POST /imnot/admin/reload` — changing `requests_per_minute` requires a restart, matching `validate:`.
- `rate_limit:` is per-endpoint, not per-datapoint, the same as `validate:`.

---

## Auto-generated admin endpoints

For every `fetch`, `polling`, `callback`, or `paginated` datapoint, imnot automatically registers these
admin endpoints — no extra YAML required:

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload` | Upload global payload (last write wins) |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload` | Inspect current global payload |
| `POST` | `/imnot/admin/{partner}/{datapoint}/payload/session` | Upload session payload → returns `session_id` |
| `GET`  | `/imnot/admin/{partner}/{datapoint}/payload/session/{session_id}` | Inspect a session payload |

`oauth` and `static` datapoints do **not** get these endpoints. Their responses are fully
defined by the YAML and never use the payload store. `paginated` follows the same admin
routes as `fetch` — upload the full array once; the handler slices at request time.

Fixed infra endpoints (always available regardless of partners loaded):

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/imnot/admin/partners` | List all loaded partners and their datapoints |
| `POST` | `/imnot/admin/partners` | Register a new partner from a raw YAML body — routes go live immediately |
| `GET`  | `/imnot/admin/sessions` | List all active sessions |
| `POST` | `/imnot/admin/reload`   | Hot-reload partner YAMLs — updates static response bodies in place, registers new partners/datapoints |

`POST /imnot/admin/partners` is the HTTP equivalent of `imnot generate` — use it when imnot
runs in a container and you cannot exec in to run the CLI. See the main README for usage examples.

---

## Checklist before saving a partner.yaml

- [ ] `partner` value is lowercase with no spaces or special characters
- [ ] Each datapoint has a unique `name` within the file
- [ ] `pattern` is one of `oauth`, `polling`, `static`, `fetch`, `callback`, `paginated`
- [ ] If the token endpoint returns non-standard fields, use `static` not `oauth`
- [ ] Every `oauth` datapoint has exactly one `POST` endpoint
- [ ] Every `polling` datapoint has at least two endpoints, each with a unique `step` number
- [ ] The polling submit step has `generates_id: true` with either `id_header` or `id_body_field`
- [ ] If `id_header` is used, `id_header_value` contains `{id}`
- [ ] Polling steps that reference the generated UUID use `{id}` in their path
- [ ] The polling fetch step has `returns_payload: true`
- [ ] Every `callback` datapoint has exactly one endpoint with exactly one of `callback_url_field` or `callback_url_header` set (not both, not neither)
- [ ] Every `paginated` datapoint has a `pagination:` block with `style` (`offset_limit`, `cursor`, `page_number`, or `page_number_url`) and `items_field` set
- [ ] If `style: cursor`, `cursor_field` is also set in the `pagination:` block
- [ ] If `style: page_number_url`, `next_url_field` and `previous_url_field` are both set in the `pagination:` block
- [ ] The `pagination:` block contains only recognized keys: `style`, `items_field`, `total_field`, `has_more_field`, `next_offset_field`, `cursor_field`, `cursor_ttl_seconds`, `page_param`, `size_param`, `next_url_field`, `previous_url_field`, `total_pages`
- [ ] The payload uploaded for a `paginated` datapoint is a JSON array (not an object)
- [ ] All `response` blocks are nested inside their endpoint, not at the datapoint level
- [ ] No two endpoints across the whole file share the same `method` + `path` combination
- [ ] No endpoint in this file shares `method` + `path` with an endpoint in any other partner file — imnot enforces this at startup and will refuse to start if a conflict is detected
- [ ] If `validate:` is declared on an endpoint, only `body`, `query`, and `headers` are valid top-level keys — unknown keys raise an error at startup
- [ ] Field rules under `validate:` use only recognized attributes: `required`, `type`, `allowed`, `pattern`, `min`, `max` — unknown attributes raise an error at startup
- [ ] `rate_limit:` is only declared on `fetch`-pattern endpoints, or on `paginated` endpoints using `pagination.style: page_number_url` — declaring it on any other pattern, or on a `paginated` endpoint using any other pagination style, raises an error at startup
- [ ] `rate_limit.requests_per_minute` must be a positive integer; unknown keys under `rate_limit:` raise an error at startup
- [ ] After saving, call `POST /imnot/admin/reload` or restart the server to pick up changes

---

## Guidance for AI-assisted YAML generation

When generating a `partner.yaml` from a Swagger/OpenAPI spec, Confluence page,
or API documentation, follow this process:

1. **Identify authentication** — if the API uses OAuth 2.0 client credentials and returns
   the standard `access_token / token_type / expires_in` shape, use the `oauth` pattern.
   If the token response contains **any custom fields**, use `static` with a `body:` block.

2. **Identify polling resources** — if an endpoint submits work and the result is fetched
   later (by polling a status endpoint or following a location header), map the full
   sequence to the `polling` pattern. Define as many steps as the real API uses.

3. **Identify paginated list endpoints** — if an endpoint returns a list of items with
   `offset`/`limit` query parameters, use `paginated` with `style: offset_limit`. If it uses
   cursor tokens, use `style: cursor`. If it uses a page number (e.g. `page=1`), use
   `style: page_number`. Upload the full dataset as an array; imnot handles slicing at request time.

4. **Identify sync resources** — if an endpoint simply returns the current state of a
   single resource (not a list), use the `fetch` pattern.

5. **One datapoint per independent resource** — if the API has `/reservations` and
   `/guests` as separate resources with separate payloads, define two datapoints.

6. **Do not invent patterns** — only use patterns listed in this guide. If the API
   behaviour does not fit any listed pattern, flag it rather than forcing a fit.

7. **Use the checklist above** before finalising the output.
