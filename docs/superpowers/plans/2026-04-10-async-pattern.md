# Async Pattern Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded `poll` pattern with a flexible `async` pattern driven entirely by YAML step configuration.

**Architecture:** A new `async_.py` pattern module dispatches per-step handler creation based on two opt-in response flags (`generates_id`, `returns_payload`); all other steps return static responses. The `poll_requests` SQLite table is renamed to `async_requests` with a startup migration. The `poll` pattern is removed from the loader and router after staylink is migrated.

**Tech Stack:** Python 3.11+, FastAPI, SQLite via `SessionStore`, PyYAML, pytest + pytest-asyncio (strict mode)

---

## File map

| File | Action |
|------|--------|
| `mirage/engine/session_store.py` | Rename table (`poll_requests` → `async_requests`) and two methods |
| `mirage/engine/patterns/async_.py` | **Create** — new pattern handler (replaces `poll.py`) |
| `mirage/engine/patterns/poll.py` | **Delete** (Task 7) |
| `mirage/engine/router.py` | Replace `poll` dispatch block with `async` |
| `mirage/loader/yaml_loader.py` | Swap `poll` for `async` in `SUPPORTED_PATTERNS` |
| `partners/staylink/partner.yaml` | Migrate from `poll` to `async` schema |
| `tests/test_session_store.py` | Update method names |
| `tests/test_async_pattern.py` | **Create** — replaces `test_poll_pattern.py` |
| `tests/test_poll_pattern.py` | **Delete** (Task 7) |
| `tests/test_yaml_loader.py` | Update assertion for staylink reservation pattern + schema |
| `tests/test_router.py` | Add async integration tests; update staylink poll tests |

---

## Task 1: Rename session store table and methods

**Files:**
- Modify: `tests/test_session_store.py`
- Modify: `mirage/engine/session_store.py`

- [ ] **Step 1: Update test_session_store.py to use new method names**

Replace the three poll-tracking tests at the bottom of the file:

```python
# ---------------------------------------------------------------------------
# Async request tracking
# ---------------------------------------------------------------------------


def test_register_and_get_async_request(store):
    async_uuid = store.register_async_request("staylink", "reservation", session_id=None)

    assert isinstance(async_uuid, str) and len(async_uuid) == 36

    row = store.get_async_request(async_uuid)
    assert row is not None
    assert row["partner"] == "staylink"
    assert row["datapoint"] == "reservation"
    assert row["session_id"] is None


def test_async_request_with_session(store):
    session_id = store.store_session_payload("staylink", "reservation", {"x": 1})
    async_uuid = store.register_async_request("staylink", "reservation", session_id=session_id)

    row = store.get_async_request(async_uuid)
    assert row["session_id"] == session_id


def test_async_request_not_found(store):
    assert store.get_async_request("nonexistent-uuid") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/edusa/personal/mirage
pytest tests/test_session_store.py -v -k "async_request"
```

Expected: `AttributeError: 'SessionStore' object has no attribute 'register_async_request'`

- [ ] **Step 3: Update session_store.py**

Replace the `_DDL` constant — change `poll_requests` to `async_requests`:

```python
_DDL = """
CREATE TABLE IF NOT EXISTS global_payloads (
    partner     TEXT NOT NULL,
    datapoint   TEXT NOT NULL,
    payload     TEXT NOT NULL,           -- JSON blob
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (partner, datapoint)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    partner     TEXT NOT NULL,
    datapoint   TEXT NOT NULL,
    payload     TEXT NOT NULL,           -- JSON blob
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS async_requests (
    uuid        TEXT PRIMARY KEY,
    partner     TEXT NOT NULL,
    datapoint   TEXT NOT NULL,
    session_id  TEXT,                    -- NULL for global-mode requests
    created_at  TEXT NOT NULL
);
"""
```

Replace the `init` method to add a migration step before running DDL:

```python
def init(self) -> None:
    """Open the database connection and create tables if they don't exist."""
    self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
    self._conn.row_factory = sqlite3.Row
    # Migrate poll_requests → async_requests for existing databases
    old_table = self._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='poll_requests'"
    ).fetchone()
    if old_table:
        self._conn.execute("ALTER TABLE poll_requests RENAME TO async_requests")
        self._conn.commit()
        logger.info("Migrated poll_requests table to async_requests")
    self._conn.executescript(_DDL)
    self._conn.commit()
    logger.info("Session store initialised at %s", self.db_path)
```

Replace the two poll-tracking methods:

```python
def register_async_request(
    self, partner: str, datapoint: str, session_id: str | None
) -> str:
    """Record a new async request (submit step). Returns the generated UUID."""
    async_uuid = _new_id()
    now = _now()
    with self._cursor() as cur:
        cur.execute(
            """
            INSERT INTO async_requests (uuid, partner, datapoint, session_id, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (async_uuid, partner, datapoint, session_id, now),
        )
    logger.debug("Registered async request %s for %s/%s", async_uuid, partner, datapoint)
    return async_uuid

def get_async_request(self, async_uuid: str) -> sqlite3.Row | None:
    """Return the async_requests row for a UUID, or None if not found."""
    with self._cursor() as cur:
        cur.execute("SELECT * FROM async_requests WHERE uuid = ?", (async_uuid,))
        return cur.fetchone()
```

Also update the module docstring — change "poll UUIDs" to "async request UUIDs":

```python
"""
Session store: SQLite-backed persistence for payloads and sessions.

Responsibilities:
- Initialize and migrate the SQLite schema on startup.
- Store and retrieve global payloads keyed by (partner, datapoint).
- Create sessions and store per-session payloads keyed by (session_id, partner, datapoint).
- Look up the correct payload for an incoming request given an optional session_id.
- Map async request UUIDs to their originating session so fetch steps can resolve the right payload.
- List active sessions for the admin API.
"""
```

- [ ] **Step 4: Run all session store tests**

```bash
pytest tests/test_session_store.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add mirage/engine/session_store.py tests/test_session_store.py
git commit -m "refactor: rename poll_requests table and methods to async_requests"
```

---

## Task 2: Implement async_.py — submit handler

**Files:**
- Create: `tests/test_async_pattern.py`
- Create: `mirage/engine/patterns/async_.py`

- [ ] **Step 1: Write failing tests for the submit handler**

Create `tests/test_async_pattern.py`:

```python
"""Tests for the async pattern handler."""

import json
from pathlib import Path

import pytest
from fastapi import Request

from mirage.engine.patterns.async_ import make_async_handlers
from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import DatapointDef, EndpointDef


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = SessionStore(db_path=tmp_path / "test.db")
    s.init()
    yield s
    s.close()


def _make_datapoint(endpoints: list[EndpointDef]) -> DatapointDef:
    return DatapointDef(
        name="job",
        description="",
        pattern="async",
        endpoints=endpoints,
    )


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    return Request({"type": "http", "headers": headers or []})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def test_factory_returns_one_handler_per_step(store):
    endpoints = [
        EndpointDef(method="POST", path="/jobs", step=1,
                    response={"status": 202, "generates_id": True,
                              "id_header": "Location", "id_header_value": "/jobs/{id}"}),
        EndpointDef(method="GET", path="/jobs/{id}", step=2,
                    response={"status": 200, "returns_payload": True}),
    ]
    handlers = make_async_handlers("partner", _make_datapoint(endpoints), store)
    assert set(handlers.keys()) == {1, 2}
    assert all(callable(h) for h in handlers.values())


def test_handler_names_are_unique(store):
    endpoints = [
        EndpointDef(method="POST", path="/jobs", step=1,
                    response={"status": 202, "generates_id": True,
                              "id_header": "Location", "id_header_value": "/jobs/{id}"}),
        EndpointDef(method="GET", path="/jobs/{id}", step=2,
                    response={"status": 200, "returns_payload": True}),
    ]
    handlers = make_async_handlers("partner", _make_datapoint(endpoints), store)
    names = [h.__name__ for h in handlers.values()]
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Submit handler — id_header delivery
# ---------------------------------------------------------------------------


@pytest.fixture
def header_submit_handler(store):
    ep = EndpointDef(
        method="POST", path="/jobs", step=1,
        response={
            "status": 202,
            "generates_id": True,
            "id_header": "Location",
            "id_header_value": "/jobs/{id}",
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[1]


@pytest.mark.asyncio
async def test_submit_header_returns_configured_status(header_submit_handler):
    response = await header_submit_handler(_request())
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_submit_header_injects_uuid_into_header(header_submit_handler):
    response = await header_submit_handler(_request())
    location = response.headers.get("Location")
    assert location is not None
    assert location.startswith("/jobs/")
    uuid_part = location.split("/")[-1]
    assert len(uuid_part) == 36  # UUID


@pytest.mark.asyncio
async def test_submit_header_persists_uuid(header_submit_handler, store):
    response = await header_submit_handler(_request())
    uuid = response.headers["Location"].split("/")[-1]
    row = store.get_async_request(uuid)
    assert row is not None
    assert row["partner"] == "partner"
    assert row["datapoint"] == "job"
    assert row["session_id"] is None


@pytest.mark.asyncio
async def test_submit_header_persists_session_id(header_submit_handler, store):
    headers = [(b"x-mirage-session", b"test-session-abc")]
    response = await header_submit_handler(_request(headers))
    uuid = response.headers["Location"].split("/")[-1]
    row = store.get_async_request(uuid)
    assert row["session_id"] == "test-session-abc"


# ---------------------------------------------------------------------------
# Submit handler — id_body_field delivery
# ---------------------------------------------------------------------------


@pytest.fixture
def body_submit_handler(store):
    ep = EndpointDef(
        method="POST", path="/jobs", step=1,
        response={
            "status": 200,
            "generates_id": True,
            "id_body_field": "JobReferenceID",
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[1]


@pytest.mark.asyncio
async def test_submit_body_returns_configured_status(body_submit_handler):
    response = await body_submit_handler(_request())
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_submit_body_injects_uuid_into_body(body_submit_handler):
    response = await body_submit_handler(_request())
    body = json.loads(response.body)
    assert "JobReferenceID" in body
    assert len(body["JobReferenceID"]) == 36  # UUID


@pytest.mark.asyncio
async def test_submit_body_persists_uuid(body_submit_handler, store):
    response = await body_submit_handler(_request())
    uuid = json.loads(response.body)["JobReferenceID"]
    row = store.get_async_request(uuid)
    assert row is not None
    assert row["partner"] == "partner"
    assert row["datapoint"] == "job"


@pytest.mark.asyncio
async def test_submit_body_merges_static_body_fields(store):
    ep = EndpointDef(
        method="POST", path="/jobs", step=1,
        response={
            "status": 200,
            "generates_id": True,
            "id_body_field": "JobReferenceID",
            "body": {"extraField": "extraValue"},
        },
    )
    handler = make_async_handlers("partner", _make_datapoint([ep]), store)[1]
    response = await handler(_request())
    body = json.loads(response.body)
    assert body["extraField"] == "extraValue"
    assert len(body["JobReferenceID"]) == 36
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_async_pattern.py -v
```

Expected: `ModuleNotFoundError: No module named 'mirage.engine.patterns.async_'`

- [ ] **Step 3: Create mirage/engine/patterns/async_.py with submit handler**

```python
"""
Async pattern handler.

Responsibilities:
- Expose a factory function `make_async_handlers` that accepts a partner name,
  a DatapointDef, and a SessionStore instance, and returns a dict mapping
  step number → FastAPI route coroutine for each async step.

Handler types are determined at startup from response config flags:
  generates_id: true  → submit handler (generates UUID, persists it, returns it)
  returns_payload: true → fetch handler (validates UUID, returns stored payload)
  neither flag         → static handler (returns status/headers/body verbatim)

ID delivery (submit handler):
  id_header + id_header_value  → UUID injected into a response header
  id_body_field                → UUID injected into a JSON response body field
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import DatapointDef, EndpointDef


def make_async_handlers(
    partner: str,
    datapoint: DatapointDef,
    store: SessionStore,
) -> dict[int, Callable]:
    """Return {step: handler} for all async endpoints in *datapoint*."""
    handlers: dict[int, Callable] = {}
    for endpoint in datapoint.endpoints:
        if endpoint.response.get("generates_id"):
            handler = _make_submit_handler(partner, datapoint, endpoint, store)
        elif endpoint.response.get("returns_payload"):
            handler = _make_fetch_handler(partner, datapoint, endpoint, store)
        else:
            handler = _make_static_handler(datapoint, endpoint)
        handlers[endpoint.step] = handler
    return handlers


# ---------------------------------------------------------------------------
# Submit handler
# ---------------------------------------------------------------------------


def _make_submit_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 202)
    id_header: str | None = endpoint.response.get("id_header")
    id_header_value: str | None = endpoint.response.get("id_header_value")
    id_body_field: str | None = endpoint.response.get("id_body_field")
    static_body: dict[str, Any] = endpoint.response.get("body") or {}

    async def handler(request: Request) -> Response:
        session_id: str | None = request.headers.get("X-Mirage-Session")
        async_uuid = store.register_async_request(
            partner=partner,
            datapoint=dp_name,
            session_id=session_id,
        )
        if id_header and id_header_value:
            header_val = id_header_value.replace("{id}", async_uuid)
            return Response(
                status_code=status_code,
                headers={id_header: header_val},
            )
        # id_body_field delivery
        body = {**static_body, id_body_field: async_uuid}
        return JSONResponse(status_code=status_code, content=body)

    handler.__name__ = f"async_submit_{partner}_{dp_name}"
    return handler


# ---------------------------------------------------------------------------
# Static handler  (placeholder — implemented in Task 3)
# ---------------------------------------------------------------------------


def _make_static_handler(
    datapoint: DatapointDef,
    endpoint: EndpointDef,
) -> Callable:
    raise NotImplementedError("static handler not yet implemented")


# ---------------------------------------------------------------------------
# Fetch handler  (placeholder — implemented in Task 3)
# ---------------------------------------------------------------------------


def _make_fetch_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    raise NotImplementedError("fetch handler not yet implemented")
```

- [ ] **Step 4: Run submit tests only**

```bash
pytest tests/test_async_pattern.py -v -k "submit"
```

Expected: all submit tests pass.

- [ ] **Step 5: Commit**

```bash
git add mirage/engine/patterns/async_.py tests/test_async_pattern.py
git commit -m "feat: add async pattern submit handler (header and body ID delivery)"
```

---

## Task 3: Implement async_.py — static and fetch handlers

**Files:**
- Modify: `tests/test_async_pattern.py`
- Modify: `mirage/engine/patterns/async_.py`

- [ ] **Step 1: Add failing tests for static and fetch handlers**

Append to `tests/test_async_pattern.py`:

```python
# ---------------------------------------------------------------------------
# Static handler
# ---------------------------------------------------------------------------


@pytest.fixture
def static_handler_headers_only(store):
    ep = EndpointDef(
        method="HEAD", path="/jobs/{id}", step=2,
        response={
            "status": 201,
            "headers": {"Status": "COMPLETED"},
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[2]


@pytest.fixture
def static_handler_with_body(store):
    ep = EndpointDef(
        method="GET", path="/jobs/{id}/status", step=2,
        response={
            "status": 200,
            "body": {"status": "COMPLETED"},
        },
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[2]


@pytest.mark.asyncio
async def test_static_returns_configured_status(static_handler_headers_only):
    response = await static_handler_headers_only(_request())
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_static_returns_configured_headers(static_handler_headers_only):
    response = await static_handler_headers_only(_request())
    assert response.headers.get("Status") == "COMPLETED"


@pytest.mark.asyncio
async def test_static_with_body_returns_body(static_handler_with_body):
    response = await static_handler_with_body(_request())
    assert response.status_code == 200
    body = json.loads(response.body)
    assert body == {"status": "COMPLETED"}


# ---------------------------------------------------------------------------
# Fetch handler
# ---------------------------------------------------------------------------


@pytest.fixture
def fetch_handler(store):
    ep = EndpointDef(
        method="GET", path="/jobs/{id}", step=3,
        response={"status": 200, "returns_payload": True},
    )
    return make_async_handlers("partner", _make_datapoint([ep]), store)[3]


def _request_with_id(async_uuid: str, session_id: str | None = None) -> Request:
    headers = []
    if session_id:
        headers.append((b"x-mirage-session", session_id.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "path_params": {"id": async_uuid},
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_fetch_unknown_uuid_returns_404(fetch_handler):
    response = await fetch_handler(_request_with_id("nonexistent-uuid"))
    assert response.status_code == 404
    assert "nonexistent-uuid" in json.loads(response.body)["detail"]


@pytest.mark.asyncio
async def test_fetch_returns_global_payload(fetch_handler, store):
    async_uuid = store.register_async_request("partner", "job", session_id=None)
    store.store_global_payload("partner", "job", {"result": "ok"})

    response = await fetch_handler(_request_with_id(async_uuid))
    assert response.status_code == 200
    assert json.loads(response.body) == {"result": "ok"}


@pytest.mark.asyncio
async def test_fetch_returns_session_payload(fetch_handler, store):
    session_id = store.store_session_payload("partner", "job", {"result": "session-ok"})
    async_uuid = store.register_async_request("partner", "job", session_id=session_id)

    response = await fetch_handler(_request_with_id(async_uuid, session_id=session_id))
    assert response.status_code == 200
    assert json.loads(response.body) == {"result": "session-ok"}


@pytest.mark.asyncio
async def test_fetch_no_payload_returns_404(fetch_handler, store):
    async_uuid = store.register_async_request("partner", "job", session_id=None)
    response = await fetch_handler(_request_with_id(async_uuid))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_fetch_session_header_but_no_session_payload_returns_404(fetch_handler, store):
    store.store_global_payload("partner", "job", {"source": "global"})
    async_uuid = store.register_async_request("partner", "job", session_id=None)

    response = await fetch_handler(_request_with_id(async_uuid, session_id="ghost-session"))
    assert response.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_async_pattern.py -v -k "static or fetch"
```

Expected: `NotImplementedError: static handler not yet implemented` and similar.

- [ ] **Step 3: Implement static and fetch handlers in async_.py**

Replace the two placeholder functions:

```python
# ---------------------------------------------------------------------------
# Static handler
# ---------------------------------------------------------------------------


def _make_static_handler(
    datapoint: DatapointDef,
    endpoint: EndpointDef,
) -> Callable:
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 200)
    extra_headers: dict[str, str] = endpoint.response.get("headers") or {}
    static_body: dict[str, Any] | None = endpoint.response.get("body")

    if static_body is not None:
        async def handler(request: Request) -> Response:
            return JSONResponse(
                status_code=status_code,
                content=static_body,
                headers=extra_headers,
            )
    else:
        async def handler(request: Request) -> Response:
            return Response(status_code=status_code, headers=extra_headers)

    handler.__name__ = f"async_static_{dp_name}_{endpoint.method.lower()}_step{endpoint.step}"
    return handler


# ---------------------------------------------------------------------------
# Fetch handler
# ---------------------------------------------------------------------------


def _make_fetch_handler(
    partner: str,
    datapoint: DatapointDef,
    endpoint: EndpointDef,
    store: SessionStore,
) -> Callable:
    dp_name = datapoint.name
    status_code: int = endpoint.response.get("status", 200)

    async def handler(request: Request) -> Response:
        async_uuid: str | None = request.path_params.get("id")
        row = store.get_async_request(async_uuid)
        if row is None:
            return JSONResponse(
                status_code=404,
                content={"detail": f"Unknown request ID: {async_uuid}"},
            )

        session_id: str | None = request.headers.get("X-Mirage-Session")
        payload: dict[str, Any] | None = store.resolve_payload(
            partner=partner,
            datapoint=dp_name,
            session_id=session_id,
        )

        if payload is None:
            detail = (
                f"No session payload found for session '{session_id}'"
                if session_id
                else f"No global payload found for {partner}/{dp_name}"
            )
            return JSONResponse(status_code=404, content={"detail": detail})

        return JSONResponse(status_code=status_code, content=payload)

    handler.__name__ = f"async_fetch_{partner}_{dp_name}"
    return handler
```

- [ ] **Step 4: Run all async pattern tests**

```bash
pytest tests/test_async_pattern.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add mirage/engine/patterns/async_.py tests/test_async_pattern.py
git commit -m "feat: complete async pattern with static and fetch handlers"
```

---

## Task 4: Update yaml_loader to support async pattern

**Files:**
- Modify: `mirage/loader/yaml_loader.py`
- Modify: `tests/test_yaml_loader.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_yaml_loader.py`:

```python
def test_async_pattern_is_valid(tmp_path):
    partner_dir = tmp_path / "testpartner"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: testpartner\n"
        "datapoints:\n"
        "  - name: job\n"
        "    pattern: async\n"
        "    endpoints:\n"
        "      - step: 1\n"
        "        method: POST\n"
        "        path: /jobs\n"
        "        response:\n"
        "          status: 202\n"
        "          generates_id: true\n"
        "          id_header: Location\n"
        "          id_header_value: /jobs/{id}\n"
    )
    result = load_partners(tmp_path)
    assert len(result) == 1
    assert result[0].datapoints[0].pattern == "async"
```

- [ ] **Step 2: Run to verify it fails**

```bash
pytest tests/test_yaml_loader.py::test_async_pattern_is_valid -v
```

Expected: empty list returned (partner skipped due to unsupported pattern).

- [ ] **Step 3: Update SUPPORTED_PATTERNS in yaml_loader.py**

```python
SUPPORTED_PATTERNS = {"oauth", "async", "push", "static", "fetch"}
```

- [ ] **Step 4: Run all yaml loader tests**

```bash
pytest tests/test_yaml_loader.py -v
```

Expected: all tests pass (note: `test_staylink_reservation_datapoint` still passes because staylink still uses `poll` — it will be updated in Task 6).

- [ ] **Step 5: Commit**

```bash
git add mirage/loader/yaml_loader.py tests/test_yaml_loader.py
git commit -m "feat: add async to supported YAML patterns"
```

---

## Task 5: Update router to dispatch async pattern

**Files:**
- Modify: `mirage/engine/router.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: Write failing integration tests using a tmp_path async partner**

Add to `tests/test_router.py` (after the existing fixtures):

```python
@pytest.fixture
def async_client(tmp_path, store):
    partner_dir = tmp_path / "asyncpartner"
    partner_dir.mkdir()
    (partner_dir / "partner.yaml").write_text(
        "partner: asyncpartner\n"
        "description: Async test partner\n"
        "datapoints:\n"
        "  - name: job\n"
        "    description: Async job\n"
        "    pattern: async\n"
        "    endpoints:\n"
        "      - step: 1\n"
        "        method: POST\n"
        "        path: /asyncpartner/jobs\n"
        "        response:\n"
        "          status: 202\n"
        "          generates_id: true\n"
        "          id_header: Location\n"
        "          id_header_value: /asyncpartner/jobs/{id}\n"
        "      - step: 2\n"
        "        method: HEAD\n"
        "        path: /asyncpartner/jobs/{id}\n"
        "        response:\n"
        "          status: 201\n"
        "          headers:\n"
        "            Status: COMPLETED\n"
        "      - step: 3\n"
        "        method: GET\n"
        "        path: /asyncpartner/jobs/{id}\n"
        "        response:\n"
        "          status: 200\n"
        "          returns_payload: true\n"
    )
    app = FastAPI()
    partners = load_partners(tmp_path)
    register_routes(app, partners, store)
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Async consumer routes
# ---------------------------------------------------------------------------


def test_async_step1_returns_202_and_location(async_client):
    r = async_client.post("/asyncpartner/jobs")
    assert r.status_code == 202
    assert "Location" in r.headers
    assert "/asyncpartner/jobs/" in r.headers["Location"]


def test_async_step2_returns_201_and_status_header(async_client):
    r1 = async_client.post("/asyncpartner/jobs")
    uuid = r1.headers["Location"].split("/")[-1]

    r2 = async_client.head(f"/asyncpartner/jobs/{uuid}")
    assert r2.status_code == 201
    assert r2.headers.get("Status") == "COMPLETED"


def test_async_step3_returns_global_payload(async_client):
    async_client.post("/mirage/admin/asyncpartner/job/payload", json={"result": "ok"})
    r1 = async_client.post("/asyncpartner/jobs")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = async_client.get(f"/asyncpartner/jobs/{uuid}")
    assert r3.status_code == 200
    assert r3.json() == {"result": "ok"}


def test_async_step3_unknown_uuid_returns_404(async_client):
    r = async_client.get("/asyncpartner/jobs/nonexistent-uuid")
    assert r.status_code == 404


def test_async_step3_no_payload_returns_404(async_client):
    r1 = async_client.post("/asyncpartner/jobs")
    uuid = r1.headers["Location"].split("/")[-1]
    r3 = async_client.get(f"/asyncpartner/jobs/{uuid}")
    assert r3.status_code == 404


def test_async_full_session_flow(async_client):
    session_id = async_client.post(
        "/mirage/admin/asyncpartner/job/payload/session",
        json={"result": "session-ok"},
    ).json()["session_id"]

    r1 = async_client.post("/asyncpartner/jobs", headers={"X-Mirage-Session": session_id})
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = async_client.get(f"/asyncpartner/jobs/{uuid}", headers={"X-Mirage-Session": session_id})
    assert r3.status_code == 200
    assert r3.json() == {"result": "session-ok"}
```

- [ ] **Step 2: Run to verify they fail**

```bash
pytest tests/test_router.py -v -k "async"
```

Expected: `FAIL` — routes return 404 because the router doesn't handle `async` pattern yet.

- [ ] **Step 3: Update router.py**

Add the import at the top of `mirage/engine/router.py`:

```python
from mirage.engine.patterns.async_ import make_async_handlers
```

Add the `async` dispatch block inside `_register_consumer_routes`, after the `elif datapoint.pattern == "fetch":` block:

```python
    elif datapoint.pattern == "async":
        step_map: dict[int, EndpointDef] = {ep.step: ep for ep in datapoint.endpoints}
        handlers = make_async_handlers(
            partner=partner.partner,
            datapoint=datapoint,
            store=store,
        )
        for step_num, handler in handlers.items():
            endpoint = step_map[step_num]
            app.add_api_route(endpoint.path, handler, methods=[endpoint.method])
            logger.debug(
                "Registered async step %d route %s %s",
                step_num, endpoint.method, endpoint.path,
            )
```

- [ ] **Step 4: Run all router tests**

```bash
pytest tests/test_router.py -v
```

Expected: all tests pass (existing poll tests still pass; new async tests pass too).

- [ ] **Step 5: Commit**

```bash
git add mirage/engine/router.py tests/test_router.py
git commit -m "feat: add async pattern dispatch to router"
```

---

## Task 6: Migrate staylink partner YAML to async schema

**Files:**
- Modify: `partners/staylink/partner.yaml`
- Modify: `tests/test_yaml_loader.py`
- Modify: `tests/test_router.py`

- [ ] **Step 1: Update partners/staylink/partner.yaml**

Replace the file content entirely:

```yaml
partner: staylink
description: StayLink fictional partner — demonstrates oauth and async patterns

datapoints:

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

  - name: reservation
    description: Async reservation creation and retrieval
    pattern: async
    endpoints:
      # Step 1 — submit reservation request
      - step: 1
        method: POST
        path: /staylink/reservations
        response:
          status: 202
          generates_id: true
          id_header: Location
          id_header_value: /staylink/reservations/{id}
      # Step 2 — poll for completion status
      - step: 2
        method: HEAD
        path: /staylink/reservations/{id}
        response:
          status: 201
          headers:
            Status: COMPLETED
      # Step 3 — retrieve stored payload
      - step: 3
        method: GET
        path: /staylink/reservations/{id}
        response:
          status: 200
          returns_payload: true
```

- [ ] **Step 2: Update test_staylink_reservation_datapoint in test_yaml_loader.py**

Replace the `test_staylink_reservation_datapoint` test:

```python
def test_staylink_reservation_datapoint():
    staylink = next(p for p in load_partners(PARTNERS_DIR) if p.partner == "staylink")
    reservation = next(dp for dp in staylink.datapoints if dp.name == "reservation")

    assert reservation.pattern == "async"
    assert len(reservation.endpoints) == 3

    steps = {ep.step: ep for ep in reservation.endpoints}
    assert set(steps.keys()) == {1, 2, 3}

    assert steps[1].method == "POST"
    assert steps[1].response["status"] == 202
    assert steps[1].response["generates_id"] is True
    assert steps[1].response["id_header"] == "Location"
    assert steps[1].response["id_header_value"] == "/staylink/reservations/{id}"

    assert steps[2].method == "HEAD"
    assert steps[2].response["status"] == 201
    assert steps[2].response["headers"]["Status"] == "COMPLETED"

    assert steps[3].method == "GET"
    assert steps[3].response["status"] == 200
    assert steps[3].response["returns_payload"] is True
```

- [ ] **Step 3: Rename the poll consumer route tests in test_router.py**

Rename the six poll test functions to async equivalents (staylink now uses the async pattern):

```python
def test_staylink_step1_returns_202_and_location(client):
    r = client.post("/staylink/reservations")
    assert r.status_code == 202
    assert "Location" in r.headers
    assert "/staylink/reservations/" in r.headers["Location"]


def test_staylink_step2_returns_201_and_status(client):
    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r2 = client.head(f"/staylink/reservations/{uuid}")
    assert r2.status_code == 201
    assert r2.headers.get("Status") == "COMPLETED"


def test_staylink_step3_returns_global_payload(client):
    client.post("/mirage/admin/staylink/reservation/payload", json={"reservationId": "RES001"})

    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "RES001"}


def test_staylink_step3_unknown_uuid_returns_404(client):
    r = client.get("/staylink/reservations/nonexistent-uuid")
    assert r.status_code == 404


def test_staylink_step3_no_payload_returns_404(client):
    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]
    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 404


def test_staylink_full_session_flow(client):
    r = client.post(
        "/mirage/admin/staylink/reservation/payload/session",
        json={"reservationId": "SES001"},
    )
    session_id = r.json()["session_id"]

    r1 = client.post("/staylink/reservations", headers={"X-Mirage-Session": session_id})
    assert r1.status_code == 202
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}", headers={"X-Mirage-Session": session_id})
    assert r3.status_code == 200
    assert r3.json() == {"reservationId": "SES001"}


def test_staylink_session_does_not_leak_to_global(client):
    r = client.post(
        "/mirage/admin/staylink/reservation/payload/session",
        json={"reservationId": "SES001"},
    )
    session_id = r.json()["session_id"]

    r1 = client.post("/staylink/reservations")
    uuid = r1.headers["Location"].split("/")[-1]

    r3 = client.get(f"/staylink/reservations/{uuid}")
    assert r3.status_code == 404


def test_staylink_two_sessions_are_isolated(client):
    s1 = client.post(
        "/mirage/admin/staylink/reservation/payload/session", json={"user": "alice"}
    ).json()["session_id"]
    s2 = client.post(
        "/mirage/admin/staylink/reservation/payload/session", json={"user": "bob"}
    ).json()["session_id"]

    uuid1 = client.post("/staylink/reservations", headers={"X-Mirage-Session": s1}).headers["Location"].split("/")[-1]
    uuid2 = client.post("/staylink/reservations", headers={"X-Mirage-Session": s2}).headers["Location"].split("/")[-1]

    assert client.get(f"/staylink/reservations/{uuid1}", headers={"X-Mirage-Session": s1}).json() == {"user": "alice"}
    assert client.get(f"/staylink/reservations/{uuid2}", headers={"X-Mirage-Session": s2}).json() == {"user": "bob"}
```

- [ ] **Step 4: Run the full test suite**

```bash
pytest -v
```

Expected: all tests pass except those in `test_poll_pattern.py` (which still import from `poll.py` — those are removed in Task 7).

- [ ] **Step 5: Commit**

```bash
git add partners/staylink/partner.yaml tests/test_yaml_loader.py tests/test_router.py
git commit -m "feat: migrate staylink partner from poll to async pattern"
```

---

## Task 7: Remove poll pattern

**Files:**
- Delete: `mirage/engine/patterns/poll.py`
- Delete: `tests/test_poll_pattern.py`
- Modify: `mirage/loader/yaml_loader.py`
- Modify: `mirage/engine/router.py`

- [ ] **Step 1: Delete poll.py and test_poll_pattern.py**

```bash
rm mirage/engine/patterns/poll.py
rm tests/test_poll_pattern.py
```

- [ ] **Step 2: Remove poll from yaml_loader.py SUPPORTED_PATTERNS**

`SUPPORTED_PATTERNS` is already `{"oauth", "async", "push", "static", "fetch"}` from Task 4 — no change needed here. Verify it does not contain `"poll"`:

```bash
grep "poll" mirage/loader/yaml_loader.py
```

Expected: no output.

- [ ] **Step 3: Remove poll import and dispatch block from router.py**

Remove this line from the imports at the top:

```python
from mirage.engine.patterns.poll import make_poll_handlers
```

Remove this block from `_register_consumer_routes`:

```python
    elif datapoint.pattern == "poll":
        step_map: dict[int, EndpointDef] = {ep.step: ep for ep in datapoint.endpoints}
        handlers = make_poll_handlers(
            partner=partner.partner,
            datapoint=datapoint,
            store=store,
        )
        for step_num, handler in handlers.items():
            endpoint = step_map[step_num]
            app.add_api_route(endpoint.path, handler, methods=[endpoint.method])
            logger.debug(
                "Registered poll step %d route %s %s",
                step_num, endpoint.method, endpoint.path,
            )
```

- [ ] **Step 4: Run the full test suite**

```bash
pytest -v
```

Expected: all tests pass, `test_poll_pattern.py` is gone.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove poll pattern (replaced by async)"
```

---

## Self-review

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|------------|
| Rename `poll` → `async` | Tasks 4, 5, 6, 7 |
| Steps defined as ordered list | Task 2 (factory iterates `endpoint.step`) |
| `generates_id: true` flag | Task 2 |
| `id_header` + `id_header_value` delivery | Task 2 |
| `id_body_field` delivery | Task 2 |
| `id_body_field` merges static body fields | Task 2 |
| `returns_payload: true` flag | Task 3 |
| Static handler (neither flag) | Task 3 |
| ID always persisted | Tasks 2, 3 |
| 404 for unknown ID on fetch | Task 3 |
| Session isolation unchanged | Tasks 3, 5, 6 |
| `poll_requests` → `async_requests` migration | Task 1 |
| `SUPPORTED_PATTERNS` update | Task 4 |
| staylink YAML migration | Task 6 |
| poll.py deleted | Task 7 |
| test_poll_pattern.py deleted | Task 7 |

All spec requirements covered. No gaps.
