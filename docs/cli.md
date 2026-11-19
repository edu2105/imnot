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
| `IMNOT_ADMIN_KEY` | `--admin-key` | |

The other settings (log level, UI, page size) live in `imnot.toml`.

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

[pagination]
# default_limit = 50                      # default page size for paginated endpoints

[ui]
# enabled = true                          # set to false to disable the admin UI (→ 404)
# default_theme = "dark"                  # "light", "dark", or "system"
```

`IMNOT_ADMIN_KEY` is environment-variable only — never written to `imnot.toml`.

---

## Logging

imnot writes two log files to `logs/` next to `imnot.db` (`[logging] log_dir`):

- `imnot.cli.log` — CLI operations (start, stop, generate, etc.) and server events: partners loaded or skipped, unknown YAML keys, callback deliveries
- `imnot.http.log` — all HTTP traffic except `/healthz`

Warnings are also printed to the console. With `--stateless` no log file is written: both streams go to stdout. When a log file reaches `max_bytes`, it is moved to `logs/archived/` (`archived_logs_dir`) with a timestamp in the filename and a new file starts. `IMNOT_ADMIN_KEY` is never written to logs.

---

## Partner auto-discovery

`imnot start`, `imnot routes`, and other commands all walk up from the current working directory to find `partners/`, `imnot.db`, and `imnot.pid`. You can run any command from any subdirectory of your project.

The search for `imnot.db` and `imnot.pid` stops at the project root — the first directory with an `imnot.toml` (created by `imnot init` and `imnot start`) — so a project nested inside another one never uses the outer project's database.

`imnot start` prints a short summary: the admin UI URL, the partners loaded, the ones skipped (run `imnot validate` for why), and the payload-backed datapoints that have no payload yet.
