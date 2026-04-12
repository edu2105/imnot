# Design: Postman Collection Generation

**Status:** Pending review  
**Author:** Eduardo Sanhueso

---

## Problem

After running `mirage start`, developers must manually create Postman requests for every
endpoint — typing methods, paths, headers, and bodies from scratch. Mirage already holds
all that information in the partner YAMLs. Generating a Postman collection automatically
eliminates the setup: import the file, set the base URL, and every endpoint is ready.

---

## Goal

Generate a valid Postman collection v2.1 JSON file from the loaded partner definitions,
exposing it via:

1. **`mirage export postman`** — CLI command that writes the collection to a file
2. **`GET /mirage/admin/postman`** — admin endpoint that returns the collection as JSON

Both surfaces share a single generator function. No external dependencies required —
the Postman v2.1 format is plain JSON with a documented schema.

---

## Collection structure

```
Mirage                                  ← top-level collection
└── {Partner}                           ← one folder per partner
    └── {datapoint}                     ← one sub-folder per datapoint
        ├── {METHOD} {path}             ← consumer endpoints
        └── Admin                       ← admin sub-folder (payload patterns only)
            ├── POST .../payload
            ├── GET  .../payload
            ├── POST .../payload/session
            ├── GET  .../payload/session/:session_id
            └── POST .../push/:request_id/retrigger   (push pattern only)
```

### Collection-level variable

| Variable | Default | Purpose |
|---|---|---|
| `baseUrl` | `http://localhost:8000` | Applied to every request URL — change once to point at any Mirage instance |

---

## Request details

### Consumer endpoints

All consumer endpoints are included regardless of pattern. The request is built from
the endpoint definition:

| Field | Value |
|---|---|
| Name | `{METHOD} {path}` |
| Method | From `EndpointDef.method` |
| URL | `{{baseUrl}}{path}` |
| Headers | `Content-Type: application/json` on POST/PUT/PATCH; none otherwise |
| Body | See body strategy below |

### Body strategy

Mirage knows the shape of some request bodies from the YAML:

| Pattern / endpoint | Generated body |
|---|---|
| `push` submit with `callback_url_field` | `{ "<field_name>": "http://your-service/webhook" }` |
| `push` submit with `callback_url_header` | No body; header `<header_name>: http://your-service/webhook` added |
| Admin payload upload (`POST .../payload`) | `{ "example": "replace with your payload" }` |
| Admin session upload (`POST .../payload/session`) | `{ "example": "replace with your payload" }` |
| All other POST/PUT/PATCH | No body (partner-specific shape is unknown) |
| GET / HEAD / DELETE | No body |

### Admin endpoint requests

For every `fetch`, `async`, or `push` datapoint, an **Admin** sub-folder is added
containing the standard payload admin requests plus the retrigger request for `push`.

| Request | Method | Path |
|---|---|---|
| Upload global payload | POST | `/mirage/admin/{partner}/{datapoint}/payload` |
| Get global payload | GET | `/mirage/admin/{partner}/{datapoint}/payload` |
| Upload session payload | POST | `/mirage/admin/{partner}/{datapoint}/payload/session` |
| Get session payload | GET | `/mirage/admin/{partner}/{datapoint}/payload/session/:session_id` |
| Retrigger callback | POST | `/mirage/admin/{partner}/{datapoint}/push/:request_id/retrigger` |

`oauth` and `static` datapoints get no Admin sub-folder — consistent with how
`_PAYLOAD_PATTERNS` gates admin routes in the router.

### Session header

All consumer requests for `fetch`, `async`, and `push` datapoints include an optional
`X-Mirage-Session` header pre-populated but disabled (Postman supports toggling headers
on/off). This makes session-isolated testing a checkbox, not a manual step.

---

## CLI — `mirage export postman`

```
mirage export postman [--out <file>] [--partners-dir <dir>]
```

| Flag | Default | Description |
|---|---|---|
| `--out` | `mirage-collection.json` | Output file path |
| `--partners-dir` | `partners/` (auto-discovered) | Partner YAML directory |

Behaviour:
1. Loads partners from `--partners-dir` (same auto-discovery as `mirage routes`)
2. Builds the collection via `build_postman_collection(partners)`
3. Writes the JSON to `--out`
4. Prints a summary: collection name, number of partners, total requests

Example output:
```
Collection written to mirage-collection.json
  Partners : 2 (staylink, bookingco)
  Requests : 14 (9 consumer, 5 admin)
```

---

## Admin endpoint — `GET /mirage/admin/postman`

Returns the collection as JSON with `Content-Type: application/json`. Protected by
`MIRAGE_ADMIN_KEY` if configured.

The endpoint calls `build_postman_collection(partners)` using the partners already
loaded on `app.state`. No disk read at request time.

---

## Implementation scope

### Files to add or change

| File | Change |
|---|---|
| `mirage/postman.py` | New module — `build_postman_collection(partners) → dict` |
| `mirage/cli.py` | New `export` command group + `postman` subcommand |
| `mirage/engine/router.py` | New `GET /mirage/admin/postman` in `_register_infra_routes`; requires partners list on `app.state` |
| `tests/test_postman.py` | New test file |
| `README.md` | Document CLI command and admin endpoint |
| `PLAN.md` | Mark Postman generation as Done |

### Files that do not change

| File | Reason |
|---|---|
| `mirage/loader/yaml_loader.py` | No new fields needed |
| `mirage/engine/session_store.py` | Generation is stateless — reads only partner definitions |
| `mirage/engine/patterns/` | No pattern changes |

### `app.state` change (detail)

`_register_infra_routes` currently receives `partners` as an argument but does not store
it on `app.state`. The admin endpoint needs it. Add:

```python
app.state.partners = partners
```

at the top of `register_routes`, alongside the existing `app.state.store`,
`app.state.configs`, etc.

---

## Testing plan

### Unit tests (`tests/test_postman.py`)

**Collection structure:**
- Collection has correct name and schema version
- One top-level folder per partner
- One sub-folder per datapoint within each partner folder

**Consumer endpoints:**
- All endpoints present with correct method and URL
- `oauth` and `static` datapoints included (consumer routes, no admin sub-folder)
- `fetch`, `async`, `push` datapoints included with Admin sub-folder

**Body generation:**
- `push` with `callback_url_field` → body contains the field name
- `push` with `callback_url_header` → no body, header present
- Admin payload upload → placeholder body present
- GET endpoints → no body

**Headers:**
- `X-Mirage-Session` present but disabled on `fetch`/`async`/`push` consumer requests
- `Content-Type: application/json` present on POST requests with a body

**`baseUrl` variable:**
- Collection variables include `baseUrl` defaulting to `http://localhost:8000`

**Admin sub-folder:**
- `oauth`/`static` datapoints have no Admin sub-folder
- `fetch`/`async` datapoints have 4 admin requests
- `push` datapoints have 5 admin requests (4 standard + retrigger)

**CLI:**
- `mirage export postman` writes a valid JSON file
- `--out` flag controls output path
- Summary line printed to stdout

**Admin endpoint:**
- `GET /mirage/admin/postman` returns 200 with valid collection JSON

---

## Out of scope

- **Postman environments** — `baseUrl` as a collection variable is sufficient; a separate
  environment file adds complexity with little benefit for a mock server
- **Pre-request scripts** — no dynamic token injection or scripting in v1
- **Example responses** — Postman supports saving example responses; not generated in v1
- **OpenAPI / Swagger export** — different format, different use case; separate feature if needed
- **Importing an existing collection and merging** — generate fresh each time
- **`--format` flag for other tools** (Insomnia, Bruno) — out of scope; those tools can
  import Postman collections natively
