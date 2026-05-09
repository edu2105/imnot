# CLI & Configuration Reference

## CLI commands

| Command | Description |
|---------|-------------|
| `imnot init` | Scaffold a new project with example partners and `imnot.toml` |
| `imnot init --dir <path>` | Scaffold into a specific directory (created if it does not exist) |
| `imnot start` | Load partner YAMLs and start the server. Starts with zero partners if no `partners/` exists. Auto-creates `imnot.toml` on first run. |
| `imnot start --reload` | Start with auto-restart on any YAML change (recommended for development) |
| `imnot stop` | Stop the running server (sends SIGTERM to PID in `imnot.pid`) |
| `imnot stop --pid-file <path>` | Stop using an explicit PID file path |
| `imnot generate --file <path>` | Validate and scaffold a partner YAML into `partners/` |
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

---

## Configuration — `imnot.toml`

`imnot.toml` is created automatically by `imnot start` on first run. All settings are optional.

```toml
[server]
# host = "127.0.0.1"                   # bind host
# port = 8000                          # bind port
# partners_dir = "partners"            # path to partner YAML directory
# db = "imnot.db"                      # path to SQLite database file
# base_url = "http://localhost:8000"   # used in generated Postman collections
# stop_timeout_seconds = 5             # seconds to wait for graceful shutdown

[logging]
# log_dir = "."                           # directory for log files
# max_bytes = 10485760                    # rotate at this size (10 MB)
# backup_name_format = "date"             # "date" (2026-04-20) or "epoch" (1745789123)
# archived_logs_dir = "./archived-logs"   # rotated backups, relative to log_dir
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

imnot writes two log files alongside `imnot.db`:

- `imnot.cli.log` — CLI operations (start, stop, generate, etc.)
- `imnot.http.log` — all HTTP traffic except `/healthz`

When a log file reaches `max_bytes`, it is moved to `archived-logs/` with a timestamp in the filename and a new file starts. `IMNOT_ADMIN_KEY` is never written to logs.

---

## Partner auto-discovery

`imnot start`, `imnot routes`, and other commands all walk up from the current working directory to find `partners/`, `imnot.db`, and `imnot.pid`. You can run any command from any subdirectory of your project.
