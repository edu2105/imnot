# Design: Push Pattern (Webhooks)

**Status:** Pending review  
**Author:** Eduardo Sanhueso  

---

## Problem

All existing Mirage patterns are inbound-only — the consumer always initiates the
request. Real partner APIs often invert this: the consumer submits a trigger request
and the partner calls back a webhook URL with the result. Without a `push` pattern,
Mirage cannot simulate these flows, forcing teams to either skip the callback leg
in testing or maintain a bespoke fake service.

---

## Goal

Implement the `push` pattern so Mirage can:

1. Receive a submit request from any consumer
2. Return an immediate response (typically `202 Accepted`)
3. Fire an outbound HTTP call to a callback URL with the stored payload — simulating
   the partner calling back the consumer's webhook endpoint
4. Allow the consumer to retrigger that outbound call via an admin endpoint, without
   restarting the whole flow

---

## YAML schema

```yaml
- name: rate-push
  description: Partner calls back with rate confirmation
  pattern: push
  endpoints:
    - method: POST
      path: /partner/rates
      response:
        status: 202
        callback_url_field: callbackUrl        # body JSON field containing the callback URL
        # OR (mutually exclusive)
        callback_url_header: X-Callback-URL   # request header containing the callback URL
        callback_method: POST                  # HTTP method for the outbound call (default: POST)
        callback_delay_seconds: 0              # seconds to wait before firing (default: 0)
```

### New response fields

| Field | Required | Default | Description |
|---|---|---|---|
| `callback_url_field` | One of these two is required | — | JSON body field in the incoming request that contains the callback URL |
| `callback_url_header` | One of these two is required | — | Request header that contains the callback URL |
| `callback_method` | No | `POST` | HTTP method used for the outbound callback |
| `callback_delay_seconds` | No | `0` | Seconds to wait before firing the callback |

Exactly one of `callback_url_field` or `callback_url_header` must be present.
Specifying both is a validation error caught at startup.

---

## Runtime flow

### Normal submit flow

```
Consumer                         Mirage                       Consumer Webhook
    |                               |                                |
    |  POST /admin/.../payload      |                                |
    |------------------------------>|                                |
    |  200 OK                       |                                |
    |<------------------------------|                                |
    |                               |                                |
    |  POST /partner/rates          |                                |
    |  { "callbackUrl": "http://    |                                |
    |    consumer/webhook" }        |                                |
    |------------------------------>|                                |
    |  202 Accepted                 |                                |
    |  { "request_id": "<uuid>" }   |                                |
    |<------------------------------|                                |
    |                               |  [BackgroundTask]              |
    |                               |  resolve payload               |
    |                               |  (optional delay)              |
    |                               |  POST http://consumer/webhook  |
    |                               |  { ...payload... }             |
    |                               |------------------------------->|
    |                               |  2xx                           |
    |                               |<-------------------------------|
```

### Retrigger flow (when callback needs to be re-fired)

```
Consumer                         Mirage                       Consumer Webhook
    |                               |                                |
    |  POST /mirage/admin/          |                                |
    |   {partner}/{datapoint}/      |                                |
    |   push/{request_id}/retrigger |                                |
    |------------------------------>|                                |
    |  200 OK                       |                                |
    |<------------------------------|                                |
    |                               |  [BackgroundTask]              |
    |                               |  look up stored callback_url   |
    |                               |  resolve payload               |
    |                               |  POST http://consumer/webhook  |
    |                               |  { ...payload... }             |
    |                               |------------------------------->|
    |                               |  2xx                           |
    |                               |<-------------------------------|
```

### Step-by-step (normal flow)

1. Consumer uploads a payload via `POST /mirage/admin/{partner}/{datapoint}/payload`
   (or a session payload via `.../payload/session`)
2. Consumer POSTs the submit request to the partner route, including the callback URL
3. Mirage extracts the callback URL from the configured field or header
4. Mirage stores the `request_id`, `session_id`, and `callback_url` in the DB
5. Mirage returns the configured status code and the `request_id` in the response body
6. A FastAPI `BackgroundTask` fires: resolves the stored payload (respecting
   `X-Mirage-Session` from the original request), waits `callback_delay_seconds`,
   then sends the payload to the callback URL using `httpx.AsyncClient`
7. Success or failure is logged; no retry

### Step-by-step (retrigger)

1. Consumer calls `POST /mirage/admin/{partner}/{datapoint}/push/{request_id}/retrigger`
2. Mirage looks up the stored `callback_url` and `session_id` by `request_id`
3. Mirage re-fires the callback using the same URL and session — with the **current**
   payload (allows updating the payload between retrigger attempts)
4. Returns `200` if the callback was dispatched, `404` if `request_id` is unknown

---

## Error handling

| Condition | Behavior |
|---|---|
| Callback URL field not present in request body | Return `400 Bad Request` with detail |
| Callback URL header not present in request | Return `400 Bad Request` with detail |
| No payload stored for the datapoint | Log warning, do not fire callback |
| Callback HTTP call fails (connection error, non-2xx) | Log error, no retry |
| Retrigger with unknown `request_id` | Return `404 Not Found` |

Returning `400` when the callback URL is missing is intentional — a push submit
without a callback URL is a malformed request in the real-world protocol being mocked.

---

## Session isolation

The push handler reads `X-Mirage-Session` from the incoming submit request and passes
it to `store.resolve_payload()`. The `session_id` is stored alongside the `callback_url`
so the retrigger endpoint can resolve the same session payload without the consumer
needing to re-specify it.

Behaviour:

- Session header present → resolve session payload
- No session header → resolve global payload
- No matching payload found → log warning, skip callback

---

## Implementation scope

### Files to add or change

| File | Change |
|---|---|
| `mirage/engine/patterns/push.py` | Full implementation (currently an empty stub) |
| `mirage/engine/session_store.py` | Add `callback_url` column to `async_requests`; add `store_push_request()` and `get_push_request()` methods |
| `mirage/engine/router.py` | Register retrigger admin route: `POST /mirage/admin/{partner}/{datapoint}/push/{request_id}/retrigger` |
| `mirage/loader/yaml_loader.py` | Parse new response fields: `callback_url_field`, `callback_url_header`, `callback_method`, `callback_delay_seconds` |
| `pyproject.toml` | Add `httpx` to `dependencies` |
| `tests/test_push.py` | New test file (see Testing section) |
| `partners/README.md` | Document the `push` pattern |
| `README.md` | Remove `push` from Limitations; add to patterns table; add retrigger to Admin endpoints table |
| `PLAN.md` | Mark push as Done |

### Files that do not change

| File | Reason |
|---|---|
| `mirage/cli.py` | `mirage routes` already handles push via `_PAYLOAD_PATTERNS` |

### Session store changes (detail)

The existing `async_requests` table gains a `callback_url` column:

```sql
ALTER TABLE async_requests ADD COLUMN callback_url TEXT;
```

New public methods on `SessionStore`:

| Method | Signature | Description |
|---|---|---|
| `store_push_request` | `(partner, datapoint, session_id, callback_url) → uuid` | Persists a push submit; returns the generated UUID |
| `get_push_request` | `(uuid) → Row \| None` | Returns the stored row including `callback_url` and `session_id` |

The existing `register_async_request` and `get_async_request` methods are unchanged —
push uses its own dedicated methods to make the separation explicit.

### New admin route (detail)

```
POST /mirage/admin/{partner}/{datapoint}/push/{request_id}/retrigger
```

- Protected by `MIRAGE_ADMIN_KEY` if configured
- Looks up `request_id` → returns `404` if unknown
- Dispatches the callback as a `BackgroundTask` using the stored `callback_url` and `session_id`
- Returns `200 { "status": "dispatched", "request_id": "..." }`

---

## Testing plan

### Unit tests (`tests/test_push.py`)

- Callback URL extracted from body field → correct URL passed to outbound call
- Callback URL extracted from header → correct URL passed to outbound call
- Both `callback_url_field` and `callback_url_header` set → startup raises `ValueError`
- Neither field set → startup raises `ValueError`
- Missing callback URL in request body → handler returns `400`
- Missing callback URL header → handler returns `400`
- No payload stored → submit returns configured status, callback not fired (warning logged)
- Global payload present → callback POST body matches uploaded payload
- Session payload present → callback POST body matches session payload
- `callback_delay_seconds > 0` → callback fires after delay
- Retrigger with valid `request_id` → callback re-fired with current payload
- Retrigger with unknown `request_id` → returns `404`
- Retrigger after payload update → callback delivers updated payload

### Integration tests

- Full push flow: upload payload → submit with callback URL → assert callback received correct payload
- Session-isolated push flow: upload session payload → submit with session header → assert correct payload delivered
- Retrigger flow: submit → retrigger → assert callback fired twice with same URL

---

## Out of scope

- **Retry logic** — a mock server does not need retry; test failures are self-evident
- **Callback auth** — no Bearer token or mTLS on the outbound call in v1
- **Storing callback attempt history** — no DB table for callback audit trail
- **Multiple callbacks per submit** — one submit fires exactly one callback
- **Non-JSON callback bodies** — callback payload is always JSON (consistent with all other patterns)
- **XML/SOAP** — explicitly out of scope for all of Mirage, not just push
