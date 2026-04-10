# Design: `async` Pattern (replaces `poll`)

**Date:** 2026-04-10
**Status:** Approved

---

## Problem

The existing `poll` pattern hardcodes a three-step POST→HEAD→GET sequence based on the OHIP
integration. This sequence is specific to OHIP and does not generalize to other real-world
async partner APIs. Naming it `poll` implies a client behavior (polling) rather than an API
style, and the hardcoded step roles (step 1 = submit, step 2 = HEAD status check, step 3 =
payload fetch) cannot accommodate partners that use different sequences, different HTTP
methods, different ID delivery mechanisms, or a different number of steps.

A second real example (Cloudbeds) confirms the pattern is too narrow:
- Submit returns `200 OK` with a `JobReferenceID` in the response body (not `202` + `Location` header)
- Status check is a `GET` with a body field indicating completion (not a `HEAD` with an HTTP status code)
- Status check is optional — consumers may skip it entirely if they receive a webhook instead

---

## Design decisions

### 1. Always-immediate completion
Mirage never simulates a "not ready yet" state. Status steps always respond as completed.
There is no pending/in-progress state machine. This is correct for a mock server — the
goal is to let integration code run its full sequence, not to test retry logic.

### 2. Ordered steps, declarative behavior
Steps are defined as an ordered list in YAML. Each step is a full endpoint definition
(method, path, response config). Mirage does not infer meaning from step number or HTTP
method. Behavior is opt-in via two response-level flags:

- `generates_id: true` — this step generates a UUID and returns it to the consumer
- `returns_payload: true` — this step returns the uploaded payload for this datapoint

Everything else (status code, headers, static body fields) is returned exactly as written
in the YAML. Any number of steps is supported (2, 3, 4, N).

### 3. ID delivery: header or body, configurable
The step with `generates_id: true` exposes the generated UUID via one of two mechanisms:

**Header delivery** (e.g. OHIP `Location` header):
```yaml
generates_id: true
id_header: Location
id_header_value: /staylink/reservations/{id}
```

**Body delivery** (e.g. Cloudbeds `JobReferenceID` field):
```yaml
generates_id: true
id_body_field: JobReferenceID
```

The `{id}` placeholder in `id_header_value` is replaced with the generated UUID at request
time. The same `{id}` token is used as the path parameter name in subsequent step paths.

### 4. ID persistence is always on
Mirage always persists generated IDs to the store. Steps with `returns_payload: true`
validate the path ID against the store and return 404 for unknown IDs. This is not
configurable — it makes integration test failures debuggable (a wrong/stale ID returns
a clear 404 rather than silently returning a payload).

### 5. Session isolation unchanged
Session isolation works the same as today. The consumer sends `X-Mirage-Session` on each
request independently. No session association is stored per async request.

---

## YAML schema

Pattern name: `async` (replaces `poll`).

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

Cloudbeds example (200 + body ID, GET status, separate results endpoint):
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

2-step example (no status check):
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

---

## Internal design

### Handler types (determined at startup)

Three handler types, selected per-step when Mirage reads the YAML:

| Condition | Handler type | Behavior |
|-----------|-------------|----------|
| `generates_id: true` | Submit | Generate UUID, persist to store, return configured status + ID in header or body |
| `returns_payload: true` | Fetch | Validate ID in store (404 if missing), resolve and return session or global payload |
| Neither flag set | Static | Return configured status, headers, and body verbatim |

### New file: `mirage/engine/patterns/async_.py`
(Cannot be named `async.py` — Python reserved word.)

Exports `make_async_handlers(partner, datapoint, store) -> dict[int, Callable]`.
Iterates `datapoint.endpoints`, selects handler type per step, returns `{step_number: handler}`.

The submit handler merges `id_body_field` into any static `body` fields defined in the YAML.
If `id_header` is set, the UUID is injected into the response header only (response body
is empty unless static `body` fields are also defined).

### Session store
The `poll_requests` table is renamed to `async_requests`. Same columns:
`(id, partner, datapoint, request_uuid, session_id, created_at)`.

Methods renamed:
- `register_poll_request` → `register_async_request`
- `get_poll_request` → `get_async_request`

Schema migration runs on first startup via `ALTER TABLE RENAME TO`.

### YAML loader
`SUPPORTED_PATTERNS` updated: `poll` removed, `async` added.
`EndpointDef` dataclass is unchanged — `generates_id`, `id_header`, `id_header_value`,
`id_body_field`, and `returns_payload` are read from the `response: dict[str, Any]` field
at handler-creation time, requiring no dataclass changes.

### Router
`_register_consumer_routes` replaces the `elif datapoint.pattern == "poll":` block with
`elif datapoint.pattern == "async":` pointing to `make_async_handlers`. Route registration
loop is identical.

---

## Files changed

| File | Change |
|------|--------|
| `mirage/engine/patterns/async_.py` | New — replaces `poll.py` |
| `mirage/engine/patterns/poll.py` | Deleted |
| `mirage/engine/session_store.py` | Rename table + methods |
| `mirage/engine/router.py` | Replace `poll` dispatch with `async` |
| `mirage/loader/yaml_loader.py` | Update `SUPPORTED_PATTERNS` |
| `partners/staylink/partner.yaml` | Migrate from `poll` to `async` schema |
| `tests/` | Update all poll-related tests to async |

---

## What is not changing

- `fetch`, `oauth`, `static` patterns — untouched
- `push.py` stub — stays as-is
- Admin endpoints — untouched
- Session isolation mechanism — untouched
- `EndpointDef`, `DatapointDef`, `PartnerDef` dataclasses — untouched
