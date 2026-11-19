# CLI & Configuration Reference

## CLI commands

| Command | Description |
|---------|-------------|
| `imnot init` | Scaffold a new project with three example partners covering all six patterns (`ratesync` ships example payloads) and `imnot.toml` |
| `imnot init --dir <path>` | Scaffold into a specific directory (created if it does not exist) |
| `imnot init --empty` | Scaffold without the example partners: an empty `partners/` and `imnot.toml`. The admin UI then offers to create your first partner or load the examples |
| `imnot start` | Load partner YAMLs and start the server. On first run it creates what is missing next to the database: `imnot.toml`, and an empty `partners/` if none is found here or in a parent directory (so the admin UI can create a partner or load the examples). An explicit `--partners-dir` / `IMNOT_PARTNERS_DIR` that does not exist is never created: the server warns and starts with zero partners. |
| `imnot start --stateless` | Write nothing to disk: in-memory database, logs to stdout only, no `imnot.pid`, no `imnot.toml`. For containers; see [deployment.md](deployment.md#containers-without-storage-stateless-mode) |
| `imnot start --strict` | Exit 1 unless the partners directory passes `imnot validate` (same rule for an empty one, see below) |
| `imnot start --reload` | Start with auto-restart on any YAML change (recommended for development) |
| `imnot stop` | Stop the running server (sends SIGTERM to PID in `imnot.pid`) |
| `imnot stop --pid-file <path>` | Stop using an explicit PID file path |
| `imnot validate` | Check every `partner.yaml` strictly (schema, unknown keys, payload files, route conflicts across partners); exits 1 on any problem. Good for CI. With no `partner.yaml` at all: a completely empty directory passes (zero partners is valid; dotfiles such as `.gitkeep` do not count), a directory with files or subfolders but no `<partner>/partner.yaml` fails (wrong layout), and a missing directory fails |
| `imnot generate --file <path>` | Validate (strictly, like `imnot validate`) and scaffold a partner YAML into `partners/` |
| `imnot generate --file <path> --dry-run --json` | Validate only — print structured result, write nothing |
| `imnot export postman` | Generate a Postman collection v2.1 JSON from all loaded partners |
| `imnot export postman --out <file>` | Write the collection to a specific file (default: `imnot-collection.json`) |
| `imnot export postman --partner <name>` | Include only the named partner (repeatable: `--partner a --partner b`) |
| `imnot status` | Show active sessions in the store |
| `imnot routes` | List all consumer and admin endpoints per partner (works from any subdirectory) |
| `imnot payload get <partner> <datapoint>` | Print the current global payload |
| `imnot payload set <partner> <datapoint> <file>` | Upload a global payload from a JSON file |
| `imnot sessions clear` | Delete all sessions from the store |

`imnot start` accepts `--admin-key` / `IMNOT_ADMIN_KEY` to protect all `/imnot/admin/*` endpoints with a Bearer token. CLI flags always override `imnot.toml` values.

### Environment variables

Every `imnot start` option can also come from the environment. Precedence: flag, then variable, then `imnot.toml`, then the default.

| Variable | Flag | Notes |
|----------|------|-------|
| `IMNOT_PARTNERS_DIR` | `--partners-dir` | |
| `IMNOT_DB_PATH` | `--db` | Ignored in stateless mode |
| `IMNOT_BIND_HOST` | `--host` | |
| `IMNOT_BIND_PORT` | `--port` | Not `IMNOT_PORT`: Kubernetes sets that one itself for a Service named `imnot` |
| `IMNOT_BASE_URL` | `--base-url` | Public URL used in `page_number_url` links and Postman collections |
| `IMNOT_INSTANCE_NAME` | `--instance-name` | Optional label (a team, an environment), up to 64 characters. Shown in the admin UI header and tab title, in `/healthz` (`instance`) and in the startup summary |
| `IMNOT_STATELESS` | `--stateless` | `1`, `true`, `yes` or `on` |
| `IMNOT_STRICT` | `--strict` | `1`, `true`, `yes` or `on` |
| `IMNOT_ADMIN_KEY` | `--admin-key` | A key shorter than 16 characters starts with a warning |
| `IMNOT_REQUIRE_ADMIN_KEY` | `--require-admin-key` | Exit 1 when no admin key is set. For shared deployments |
| `IMNOT_CALLBACK_ALLOWED_HOSTS` | `--callback-allowed-hosts` | Comma-separated host names, `*.` suffixes and CIDRs (`orders.team-a,*.team-a.svc.cluster.local,10.20.0.0/16`). When set, a `callback` submit to anything else gets `422`. Link-local and cloud metadata addresses are refused with or without it |

Every key of the `[logging]`, `[pagination]`, `[ui]` and `[metrics]` sections of `imnot.toml` can also be set as `IMNOT_<SECTION>_<KEY>`, and the variable wins over the file:

| Variable | `imnot.toml` key | Values |
|---|---|---|
| `IMNOT_LOGGING_FORMAT` | `[logging] format` | `text` (default) or `json` |
| `IMNOT_LOGGING_DEBUG` | `[logging] debug` | `1`/`0`, `true`/`false`, `yes`/`no`, `on`/`off` |
| `IMNOT_LOGGING_STDOUT` | `[logging] stdout` | same as above |
| `IMNOT_LOGGING_LOG_DIR`, `IMNOT_LOGGING_MAX_BYTES`, `IMNOT_LOGGING_BACKUP_NAME_FORMAT`, `IMNOT_LOGGING_ARCHIVED_LOGS_DIR` | the `[logging]` key of the same name | |
| `IMNOT_PAGINATION_DEFAULT_LIMIT` | `[pagination] default_limit` | a number |
| `IMNOT_UI_ENABLED` | `[ui] enabled` | true/false as above |
| `IMNOT_UI_DEFAULT_THEME` | `[ui] default_theme` | `light`, `dark` or `system` |
| `IMNOT_METRICS_ENABLED` | `[metrics] enabled` | true/false; Prometheus metrics at `/imnot/metrics` ([below](#metrics)) |

An unknown `IMNOT_LOGGING_*` / `IMNOT_PAGINATION_*` / `IMNOT_UI_*` / `IMNOT_METRICS_*` name or a value of the wrong type stops `imnot` with an error. `[server]` keys use the names in the table above (`IMNOT_BIND_HOST`, `IMNOT_DB_PATH`…), not `IMNOT_SERVER_*`. The variables Kubernetes adds for a Service named `imnot-ui`, `imnot-logging`… (`IMNOT_UI_PORT`, `IMNOT_UI_SERVICE_HOST`…) are ignored.

---

## Configuration — `imnot.toml`

`imnot.toml` is created automatically by `imnot start` on first run (never with `--stateless`, which still reads one if it finds it). All settings are optional.

```toml
[server]
# host = "127.0.0.1"                   # bind host
# port = 8000                          # bind port
# partners_dir = "partners"            # path to partner YAML directory
# db = "imnot.db"                      # path to SQLite database file
# base_url = "http://localhost:8000"   # public URL: Postman collections and page_number_url links
# stop_timeout_seconds = 5             # seconds to wait for graceful shutdown

[logging]
# log_dir = "logs"                        # directory for log files, relative to the DB directory
# max_bytes = 10485760                    # rotate at this size (10 MB)
# backup_name_format = "date"             # "date" (2026-04-20) or "epoch" (1745789123)
# archived_logs_dir = "./archived"        # rotated backups, relative to log_dir
# debug = false                           # enable DEBUG-level logs
# stdout = false                          # also emit to stdout (useful for Docker/ECS)
# format = "text"                         # "text" or "json" (one JSON object per line)

[pagination]
# default_limit = 50                      # default page size for paginated endpoints

[ui]
# enabled = true                          # set to false to disable the admin UI (→ 404)
# default_theme = "dark"                  # "light", "dark", or "system"

# [metrics]
# enabled = false                         # Prometheus metrics at GET /imnot/metrics (no auth)
```

`IMNOT_ADMIN_KEY` is environment-variable only — never written to `imnot.toml`.

---

## Logging

imnot writes two log files to `logs/` next to `imnot.db` (`[logging] log_dir`):

- `imnot.cli.log` — CLI operations (start, stop, generate, etc.) and server events: partners loaded or skipped, unknown YAML keys, callback deliveries
- `imnot.http.log` — all HTTP traffic except `/healthz`

Warnings are also printed to the console. With `--stateless` no log file is written: both streams go to stdout. When a log file reaches `max_bytes`, it is moved to `logs/archived/` (`archived_logs_dir`) with a timestamp in the filename and a new file starts. `IMNOT_ADMIN_KEY` is never written to logs.

### JSON logs

`[logging] format = "json"` (or `IMNOT_LOGGING_FORMAT=json`) writes one JSON object per line, to the files and to stdout alike, for log platforms that parse JSON:

```json
{"time": "2026-11-19T16:28:28.806+00:00", "level": "INFO", "logger": "imnot.http", "message": "GET /staylink/x 404 0ms session=s1", "method": "GET", "path": "/staylink/x", "status": 404, "duration_ms": 0, "request_id": "587c6746-…", "session": "s1"}
```

- Every line has `time` (UTC), `level`, `logger` and `message`; `imnot.http` lines add `method`, `path`, `status`, `duration_ms`, `request_id` and, when present, `partner`, `datapoint` and `session`; errors add `exception`.
- uvicorn's own lines (`uvicorn.error`, `uvicorn.access`) are JSON too.
- `imnot start` skips its human-readable startup summary so stdout stays JSON only; the same facts are logged (`Starting imnot host=…`, partners loaded, warnings).

---

## Metrics

Off by default. With `[metrics] enabled = true` (or `IMNOT_METRICS_ENABLED=1`), `GET /imnot/metrics` serves Prometheus metrics in the text format. It needs no admin key, like `/healthz`, and is not written to the HTTP log.

| Metric | Type | Labels |
|---|---|---|
| `imnot_http_requests_total` | counter | `partner`, `datapoint`, `method`, `status` |
| `imnot_http_request_duration_seconds` | histogram | `partner`, `datapoint` |
| `imnot_callback_deliveries_total` | counter | `partner`, `datapoint`, `result`: `delivered`, `failed` (after the last retry), `refused` (callback policy) or `skipped` (no payload) |
| `imnot_admin_auth_failures_total` | counter | |
| `imnot_partners_loaded` | gauge | |
| `imnot_info` | gauge, always 1 | `version` |

- Only requests to mock routes are counted (not `/imnot/*` or `/healthz`). A path that matches no route counts with `partner=""` and `datapoint=""`; raw paths, payloads and headers never become labels. Unusual HTTP methods count as `OTHER`.
- The duration ends when the response is sent: a callback delivery that runs afterwards is not part of it.
- Counters live in the process and start from zero at every restart.

---

## Partner auto-discovery

`imnot start`, `imnot routes`, and other commands all walk up from the current working directory to find `partners/`, `imnot.db`, and `imnot.pid`. You can run any command from any subdirectory of your project.

The search for `imnot.db` and `imnot.pid` stops at the project root — the first directory with an `imnot.toml` (created by `imnot init` and `imnot start`) — so a project nested inside another one never uses the outer project's database.

`imnot start` prints a short summary: the admin UI URL, the partners loaded, the ones skipped (run `imnot validate` for why), and the payload-backed datapoints that have no payload yet.
