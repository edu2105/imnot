# Pattern Reference

This document covers all six imnot interaction patterns. For the top-level YAML schema see [partners/README.md](../partners/README.md).

---

## `oauth`

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

---

## `static`

Returns whatever JSON body is defined under `response.body`. Use for non-standard auth endpoints, health checks, or any fixed response.

Use `static` instead of `oauth` when the partner token endpoint returns **custom fields** that don't match the standard `access_token / token_type / expires_in` shape:

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

Static responses can be updated without restarting: edit the YAML, then call `POST /imnot/admin/reload`.

---

## `fetch`

Single GET endpoint that returns the stored payload for the datapoint. Supports `X-Imnot-Session` for test isolation.

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

---

## `polling`

Flexible N-step async flow. Step count and HTTP methods are fully configurable. Behavior is opt-in via two response flags:

- `generates_id: true` — generate a UUID and deliver it via header or body field
- `returns_payload: true` — return the stored payload for this datapoint

**Header delivery (3 steps):**

```yaml
- name: reservation
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

**Body delivery (separate status and results endpoints):**

```yaml
- name: rate-push
  pattern: polling
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

**Interaction sequence:**

```
Test Harness                       imnot
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

The number and shape of steps is configurable per partner — 2-step, 3-step, and body-delivered IDs are all supported.

---

## `callback`

imnot receives a submit request, returns immediately, then fires an outbound HTTP call to a callback URL with the stored payload — simulating the external service calling back your webhook endpoint.

**Callback URL from request body field:**

```yaml
- name: rate-push
  pattern: callback
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
  pattern: callback
  endpoints:
    - method: POST
      path: /partner/rates
      response:
        status: 202
        callback_url_header: X-Callback-URL
```

Exactly one of `callback_url_field` or `callback_url_header` is required. The submit response body always includes a `request_id` (UUID) usable with the retrigger endpoint.

**Interaction sequence:**

```
Test Harness                    imnot                     Test Harness Webhook
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
curl -X POST http://localhost:8000/imnot/admin/{partner}/{datapoint}/callback/{request_id}/retrigger
```

The retrigger always uses the **current** stored payload, so you can update the payload between attempts.

---

## `paginated`

Upload a full array of items once; imnot slices the array at request time. Three pagination styles are supported via the `style` field.

---

### Style: `offset_limit`

Consumers page using `offset` and `limit` query parameters. Use `offset_echo_field` and `limit_echo_field` to mirror those values back in the response — many real APIs include them alongside the total count.

```yaml
- name: reservations
  pattern: paginated
  endpoints:
    - method: GET
      path: /staylink/reservations
      response:
        status: 200
  pagination:
    style: offset_limit
    items_field: reservations
    total_field: count
    offset_echo_field: offset
    limit_echo_field: limit
    has_more_field: hasMore
```

Upload the full dataset (a JSON array):
```bash
curl -X POST http://localhost:8000/imnot/admin/staylink/reservations/payload \
  -H "Content-Type: application/json" \
  -d '[
    {"id": "RES-001", "guestName": "John Smith",   "roomType": "Deluxe",   "checkIn": "2026-06-01", "checkOut": "2026-06-03"},
    {"id": "RES-002", "guestName": "Maria Garcia", "roomType": "Suite",    "checkIn": "2026-06-02", "checkOut": "2026-06-05"},
    {"id": "RES-003", "guestName": "Lucas Brown",  "roomType": "Standard", "checkIn": "2026-06-03", "checkOut": "2026-06-04"}
  ]'
```

First page:
```
GET /staylink/reservations?offset=0&limit=2
```
```json
{
  "count": 3,
  "offset": 0,
  "limit": 2,
  "hasMore": true,
  "reservations": [
    {"id": "RES-001", "guestName": "John Smith",   "roomType": "Deluxe", "checkIn": "2026-06-01", "checkOut": "2026-06-03"},
    {"id": "RES-002", "guestName": "Maria Garcia", "roomType": "Suite",  "checkIn": "2026-06-02", "checkOut": "2026-06-05"}
  ]
}
```

Second page:
```
GET /staylink/reservations?offset=2&limit=2
```
```json
{
  "count": 3,
  "offset": 2,
  "limit": 2,
  "hasMore": false,
  "reservations": [
    {"id": "RES-003", "guestName": "Lucas Brown", "roomType": "Standard", "checkIn": "2026-06-03", "checkOut": "2026-06-04"}
  ]
}
```

`next_offset_field` is also available if the API explicitly returns the next page's offset value.

---

### Style: `cursor`

imnot issues opaque cursor tokens (UUID v4) stored server-side. Consumers pass `cursor=<token>` to fetch the next page; the response always includes a `cursor_field` key (`null` on the last page).

```yaml
- name: rates
  pattern: paginated
  endpoints:
    - method: GET
      path: /ratesync/rates
      response:
        status: 200
  pagination:
    style: cursor
    items_field: data
    cursor_field: nextCursor
    cursor_ttl_seconds: 3600
    has_more_field: hasMore
```

Upload the full dataset:
```bash
curl -X POST http://localhost:8000/imnot/admin/ratesync/rates/payload \
  -H "Content-Type: application/json" \
  -d '[
    {"id": "RATE-001", "name": "Standard Rate", "amount": 120.00, "currency": "USD"},
    {"id": "RATE-002", "name": "Weekend Rate",  "amount": 150.00, "currency": "USD"},
    {"id": "RATE-003", "name": "Promo Rate",    "amount":  89.00, "currency": "USD"}
  ]'
```

First page (no cursor):
```bash
curl "http://localhost:8000/ratesync/rates?limit=2"
```
```json
{
  "data": [
    {"id": "RATE-001", "name": "Standard Rate", "amount": 120.00, "currency": "USD"},
    {"id": "RATE-002", "name": "Weekend Rate",  "amount": 150.00, "currency": "USD"}
  ],
  "nextCursor": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "hasMore": true
}
```

Next page (pass the cursor from the previous response):
```bash
curl "http://localhost:8000/ratesync/rates?limit=2&cursor=a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```
```json
{
  "data": [
    {"id": "RATE-003", "name": "Promo Rate", "amount": 89.00, "currency": "USD"}
  ],
  "nextCursor": null,
  "hasMore": false
}
```

Expired or unknown cursor returns `400 {"detail": "Cursor expired or not found"}`.

---

### Style: `page_number`

Consumers send a 1-indexed page number instead of a raw offset. Use `page_param` / `size_param` when the real API uses non-default names.

```yaml
- name: properties
  pattern: paginated
  endpoints:
    - method: GET
      path: /bookingco/properties
      response:
        status: 200
  pagination:
    style: page_number
    items_field: properties
    total_field: total
    has_more_field: hasMore
    page_param: page
    size_param: size
```

Upload the full dataset:
```bash
curl -X POST http://localhost:8000/imnot/admin/bookingco/properties/payload \
  -H "Content-Type: application/json" \
  -d '[
    {"id": "PROP-001", "name": "The Grand Hotel", "city": "Miami", "rooms": 120},
    {"id": "PROP-002", "name": "Seaside Resort",  "city": "Miami", "rooms":  85},
    {"id": "PROP-003", "name": "Downtown Suites", "city": "Miami", "rooms":  60}
  ]'
```

First page:
```
GET /bookingco/properties?page=1&size=2
```
```json
{
  "total": 3,
  "hasMore": true,
  "properties": [
    {"id": "PROP-001", "name": "The Grand Hotel", "city": "Miami", "rooms": 120},
    {"id": "PROP-002", "name": "Seaside Resort",  "city": "Miami", "rooms":  85}
  ]
}
```

Second page:
```
GET /bookingco/properties?page=2&size=2
```
```json
{
  "total": 3,
  "hasMore": false,
  "properties": [
    {"id": "PROP-003", "name": "Downtown Suites", "city": "Miami", "rooms": 60}
  ]
}
```

Pages are 1-indexed — `page=1` is the first page. `page=0` is clamped to `page=1`.

---

Default page size when the size param is absent is configured in `imnot.toml`:
```toml
[pagination]
default_limit = 50
```

Session isolation (`X-Imnot-Session`) is supported for all three styles — two sessions can hold different datasets and page through them independently.

---

## Session isolation

Any `fetch`, `polling`, or `paginated` endpoint supports per-test session isolation via `X-Imnot-Session`.

```bash
# Upload a session-scoped payload — returns a session_id
SESSION=$(curl -s -X POST http://localhost:8000/imnot/admin/bookingco/charges/payload/session \
               -H "Content-Type: application/json" \
               -d '{"charges": [{"id": "S1"}]}' | jq -r .session_id)

# Use the session in your request
curl http://localhost:8000/bookingco/v1/charges -H "X-Imnot-Session: $SESSION"
```

Multiple test users can run in parallel with isolated payloads — each gets their own `session_id`.
