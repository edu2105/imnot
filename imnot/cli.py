"""
CLI entry point for imnot.

Responsibilities:
- Provide the `imnot` command group via Click.
- `imnot start`:         load partner YAMLs, build the FastAPI app, launch Uvicorn.
- `imnot status`:        show active sessions in the store.
- `imnot routes`:        list all consumer and admin endpoints for loaded partners.
- `imnot payload get`:   print the current global payload for a datapoint.
- `imnot payload set`:   upload a global payload for a datapoint from a JSON file.
- `imnot sessions clear`: wipe all sessions from the store.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from importlib.resources import files
from pathlib import Path

import click
import uvicorn
import yaml

from imnot.api.server import create_app
from imnot.config import load_config
from imnot.engine.router import _PAYLOAD_PATTERNS
from imnot.engine.session_store import SessionStore
from imnot.loader.yaml_loader import load_partners
from imnot.logging_setup import configure_logging
from imnot.partners import register_partner
from imnot.postman import build_postman_collection, collection_stats

DEFAULT_PARTNERS_DIR = "partners"
DEFAULT_DB = Path("imnot.db")

_IMNOT_TOML_TEMPLATE = """\
# imnot.toml — runtime configuration for imnot
# All values shown are defaults. Uncomment and change what you need.

[server]
# host = "127.0.0.1"                   # bind host
# port = 8000                          # bind port
# partners_dir = "partners"            # path to partner YAML directory
# db = "imnot.db"                      # path to SQLite database file
# base_url = "http://localhost:8000"   # used in generated Postman collections
# stop_timeout_seconds = 5             # seconds to wait for graceful shutdown

[logging]
# log_dir = "."                           # directory for log files (default: current dir)
# max_bytes = 10485760                    # rotate when log file reaches this size (10 MB)
# backup_name_format = "date"             # "date" (2026-04-20) or "epoch" (1745789123)
# archived_logs_dir = "./archived-logs"   # rotated backups, relative to log_dir
# debug = false                           # enable DEBUG-level logs
# stdout = false                          # also emit to stdout (useful for Docker/ECS)

# [pagination]
# default_limit = 50                      # default page size for paginated pattern endpoints

[ui]
# enabled = true                          # set to false to disable the admin UI entirely
# default_theme = "light"                 # "light", "dark", or "system"
"""


def _resolve_config(db_path: Path | None = None) -> Path | None:
    """Walk up from CWD looking for imnot.toml. Returns path if found, None otherwise.

    If *db_path* is provided, its parent directory is checked first — this handles
    deployments where the DB lives in a writable subdirectory (e.g. /app/data in Docker)
    while CWD is a read-only parent (e.g. /app).
    """
    if db_path is not None:
        candidate = db_path.parent / "imnot.toml"
        if candidate.exists():
            return candidate
    current = Path.cwd()
    while True:
        candidate = current / "imnot.toml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _setup_logging(log_dir: Path | None = None) -> logging.Logger:
    """Configure logging from imnot.toml (if found) and return the imnot.cli logger."""
    config = load_config(_resolve_config())
    resolved = Path(config.logging.log_dir)
    if not resolved.is_absolute():
        # Prefer the DB directory (guaranteed writable) over CWD, which may be read-only
        # in container environments.  Fall back to CWD if the DB can't be located.
        if log_dir is None:
            try:
                log_dir = _resolve_db(config.server.db).parent
            except (FileNotFoundError, Exception):
                log_dir = Path.cwd()
        resolved = (log_dir / resolved).resolve()
    configure_logging(config.logging, resolved)
    return logging.getLogger("imnot.cli")


def _resolve_partners_dir(given: str) -> Path:
    """Resolve the partners directory path.

    If *given* exists relative to the current working directory, return it.
    Otherwise walk up the directory tree until a matching subdirectory is found.
    Raises ``FileNotFoundError`` if nothing is found.
    """
    given_path = Path(given)
    if given_path.is_absolute():
        if not given_path.is_dir():
            raise FileNotFoundError(f"Partners directory '{given}' not found.")
        return given_path
    if given_path.is_dir():
        return given_path.resolve()
    # Walk up from CWD looking for the directory name
    current = Path.cwd()
    while True:
        candidate = current / given
        if candidate.is_dir():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        f"Partners directory '{given}' not found in {Path.cwd()} or any parent directory. "
        f"Run `imnot init` to create a new project, or pass --partners-dir explicitly."
    )


@click.group()
@click.version_option(package_name="imnot")
def cli() -> None:
    """imnot — stateful API mock server for integration testing."""


# ---------------------------------------------------------------------------
# imnot start
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--partners-dir",
    default=None,
    help=f"Directory containing partner YAML definitions. [default: {DEFAULT_PARTNERS_DIR}]",
)
@click.option(
    "--db",
    default=None,
    help=f"Path to the SQLite database file. [default: {DEFAULT_DB}]",
)
@click.option("--host", default=None, help="Bind host. [default: 127.0.0.1]")
@click.option("--port", default=None, type=int, help="Bind port. [default: 8000]")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (development only).")
@click.option(
    "--admin-key",
    default=None,
    envvar="IMNOT_ADMIN_KEY",
    help="Bearer token required for all /imnot/admin/* endpoints. "
    "Also readable from IMNOT_ADMIN_KEY env var. Omit for open access (local dev only).",
)
def start(
    partners_dir: str | None,
    db: str | None,
    host: str | None,
    port: int | None,
    reload: bool,
    admin_key: str | None,
) -> None:
    """Start the mock server and load partner definitions."""
    # Resolve db_path early so _resolve_config can find imnot.toml co-located with the
    # DB (e.g. /app/data/imnot.toml) before we know the full config.
    early_db_path = Path(db) if db else Path(DEFAULT_DB)
    config_path = _resolve_config(db_path=early_db_path)
    config = load_config(config_path)

    effective_db = db or config.server.db
    effective_host = host or config.server.host
    effective_port = port if port is not None else config.server.port
    effective_partners_dir = partners_dir or config.server.partners_dir

    db_path = Path(effective_db)

    # Configure logging before anything else so all subsequent events are captured.
    # Resolve relative log_dir against db_path.parent (guaranteed writable in any
    # deployment) rather than CWD, which is read-only in the official Docker image.
    log_dir = Path(config.logging.log_dir)
    if not log_dir.is_absolute():
        log_dir = (db_path.parent / log_dir).resolve()
    configure_logging(config.logging, log_dir)
    cli_log = logging.getLogger("imnot.cli")

    # Auto-write imnot.toml co-located with the DB (guaranteed writable directory).
    if config_path is None:
        toml_path = db_path.parent / "imnot.toml"
        if not toml_path.exists():
            toml_path.write_text(_IMNOT_TOML_TEMPLATE, encoding="utf-8")
            cli_log.info("Created imnot.toml with default configuration at %s", toml_path)

    # Resolve partners dir. If missing, start with zero partners (not a fatal error).
    try:
        resolved_partners_dir: Path | None = _resolve_partners_dir(effective_partners_dir)
    except FileNotFoundError:
        resolved_partners_dir = None
        click.echo(
            "Warning: No partners directory found — server starting with zero partners.\n"
            "Use `imnot generate` or POST /imnot/admin/partners to add partners.",
            err=True,
        )
        cli_log.warning("No partners directory found — starting with zero partners")

    effective_admin_key = admin_key or None
    pid_path = db_path.with_suffix(".pid")

    click.echo(f"Starting imnot on http://{effective_host}:{effective_port}")
    cli_log.info(
        "Starting imnot host=%s port=%d db=%s partners_dir=%s admin_key=%s",
        effective_host,
        effective_port,
        db_path,
        resolved_partners_dir,
        "set" if effective_admin_key else "unset",
    )

    pid_path.write_text(str(os.getpid()))
    try:
        if reload:
            os.environ["IMNOT_PARTNERS_DIR"] = str(resolved_partners_dir) if resolved_partners_dir else ""
            os.environ["IMNOT_DB_PATH"] = str(db_path)
            if effective_admin_key:
                os.environ["IMNOT_ADMIN_KEY"] = effective_admin_key
            uvicorn.run(
                "imnot.api.server:create_app_from_env",
                host=effective_host,
                port=effective_port,
                reload=True,
                reload_includes=["*.yaml"],
                factory=True,
            )
        else:
            app = create_app(
                partners_dir=resolved_partners_dir,
                db_path=db_path,
                admin_key=effective_admin_key,
                base_url=config.server.base_url,
                default_limit=config.pagination.default_limit,
                ui_config=config.ui,
            )
            uvicorn.run(app, host=effective_host, port=effective_port)
    finally:
        if pid_path.exists():
            pid_path.unlink()
        cli_log.info("imnot stopped")


# ---------------------------------------------------------------------------
# imnot stop
# ---------------------------------------------------------------------------

_DEFAULT_PID = "imnot.pid"
_STOP_POLL_INTERVAL = 0.1


@cli.command()
@click.option(
    "--pid-file",
    default=_DEFAULT_PID,
    show_default=True,
    help="Path to the PID file written by `imnot start`.",
)
def stop(pid_file: str) -> None:
    """Stop a running imnot server."""
    cli_log = _setup_logging()
    stop_timeout = load_config(_resolve_config()).server.stop_timeout_seconds

    try:
        pid_path = _resolve_pid(pid_file)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError) as exc:
        click.echo(f"Could not read PID file '{pid_path}': {exc}", err=True)
        raise SystemExit(1)

    # Check whether the process is still alive (signal 0 probes without killing).
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        click.echo(f"Process {pid} is not running (stale PID file). Cleaning up.")
        pid_path.unlink(missing_ok=True)
        return
    except PermissionError:
        click.echo(f"No permission to signal process {pid}.", err=True)
        raise SystemExit(1)

    cli_log.info("Sending SIGTERM to pid %d", pid)
    os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + stop_timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pid_path.unlink(missing_ok=True)
            cli_log.info("imnot stopped (pid %d)", pid)
            click.echo(f"imnot stopped (pid {pid}).")
            return
        time.sleep(_STOP_POLL_INTERVAL)

    cli_log.warning("Process %d did not exit within %gs", pid, stop_timeout)
    click.echo(
        f"Process {pid} did not exit within {stop_timeout:.0f}s. Run `kill -9 {pid}` to force-stop it.",
        err=True,
    )
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# imnot init
# ---------------------------------------------------------------------------

_EXAMPLES = [
    ("staylink", "oauth + polling"),
    ("bookingco", "static + fetch"),
]


@cli.command()
@click.option(
    "--dir",
    "target_dir",
    default=".",
    show_default=True,
    help="Directory to initialise. Created if it does not exist.",
)
def init(target_dir: str) -> None:
    """Scaffold a new imnot project with example partner definitions."""
    target = Path(target_dir).resolve()
    partners_dir = target / "partners"

    if partners_dir.exists():
        click.echo(
            f"partners/ already exists in {target} — nothing written.\n"
            f"To add a partner, use `imnot generate --file <yaml>`.",
            err=True,
        )
        raise SystemExit(1)

    target.mkdir(parents=True, exist_ok=True)
    cli_log = _setup_logging(target)

    written: list[tuple[Path, str]] = []
    for partner_name, patterns in _EXAMPLES:
        dest_dir = partners_dir / partner_name
        dest_dir.mkdir(parents=True)
        yaml_text = files("imnot.examples").joinpath(partner_name).joinpath("partner.yaml").read_text(encoding="utf-8")
        dest = dest_dir / "partner.yaml"
        dest.write_text(yaml_text, encoding="utf-8")
        written.append((dest.relative_to(target), patterns))

    toml_path = target / "imnot.toml"
    if not toml_path.exists():
        toml_path.write_text(_IMNOT_TOML_TEMPLATE, encoding="utf-8")

    cli_log.info("Initialized imnot project in %s", target)
    click.echo(f"Initialized imnot project in {target}\n")
    for path, patterns in written:
        click.echo(f"  {path}   ({patterns})")
    click.echo("  imnot.toml")
    click.echo()
    click.echo("Run `imnot start` to launch the mock server.")


# ---------------------------------------------------------------------------
# imnot \1
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to the SQLite database file.")
def status(db: str) -> None:
    """Show active sessions in the store."""
    store = _open_store(db)
    sessions = store.list_sessions()
    store.close()

    if not sessions:
        click.echo("No active sessions.")
        return

    click.echo(f"{'SESSION ID':<38} {'PARTNER':<12} {'DATAPOINT':<16} {'CREATED AT'}")
    click.echo("-" * 90)
    for s in sessions:
        click.echo(f"{s['session_id']:<38} {s['partner']:<12} {s['datapoint']:<16} {s['created_at']}")


# ---------------------------------------------------------------------------
# imnot \1
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--partners-dir",
    default=str(DEFAULT_PARTNERS_DIR),
    show_default=True,
    help="Directory containing partner YAML definitions.",
)
def routes(partners_dir: str) -> None:
    """List all consumer and admin endpoints for loaded partners."""
    _setup_logging()
    try:
        resolved = _resolve_partners_dir(partners_dir)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    partners = load_partners(resolved)
    if not partners:
        click.echo("No partners loaded.")
        return

    for partner in partners:
        click.echo(f"\n{click.style(partner.partner.upper(), bold=True)}  {partner.description}")
        click.echo()

        click.echo(f"  {'CONSUMER ENDPOINTS':}")
        for dp in partner.datapoints:
            for ep in dp.endpoints:
                click.echo(f"    {ep.method:<7} {ep.path}  [{dp.pattern}]")

        payload_dps = [dp for dp in partner.datapoints if dp.pattern in _PAYLOAD_PATTERNS]
        if payload_dps:
            click.echo()
            click.echo(f"  {'ADMIN ENDPOINTS':}")
            for dp in payload_dps:
                base = f"/imnot/admin/{partner.partner}/{dp.name}/payload"
                click.echo(f"    {'POST':<7} {base}")
                click.echo(f"    {'GET':<7} {base}")
                click.echo(f"    {'POST':<7} {base}/session")
                click.echo(f"    {'GET':<7} {base}/session/{{session_id}}")
                if dp.pattern == "callback":
                    retrigger = f"/imnot/admin/{partner.partner}/{dp.name}/callback/{{request_id}}/retrigger"
                    click.echo(f"    {'POST':<7} {retrigger}")

    click.echo()
    click.echo("  INFRA ENDPOINTS")
    click.echo(f"    {'GET':<7} /imnot/admin/partners")
    click.echo(f"    {'POST':<7} /imnot/admin/partners")
    click.echo(f"    {'GET':<7} /imnot/admin/sessions")
    click.echo(f"    {'POST':<7} /imnot/admin/reload")
    click.echo(f"    {'GET':<7} /imnot/admin/ui")


# ---------------------------------------------------------------------------
# imnot \1
# ---------------------------------------------------------------------------


def _fail(msg: str, json_output: bool, code: int) -> None:
    if json_output:
        click.echo(json.dumps({"status": "error", "error": msg}))
    else:
        click.echo(msg, err=True)
    raise SystemExit(code)


@cli.command()
@click.option(
    "--file",
    "file_path",
    required=True,
    help="Path to partner.yaml to validate and register. Use '-' to read from stdin.",
)
@click.option(
    "--partners-dir",
    default=str(DEFAULT_PARTNERS_DIR),
    show_default=True,
    help="Directory containing partner YAML definitions.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Validate only — print what would happen, write nothing.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Output result as JSON.")
@click.option("--force", is_flag=True, default=False, help="Overwrite existing partner.yaml if it already exists.")
def generate(file_path: str, partners_dir: str, dry_run: bool, json_output: bool, force: bool) -> None:
    """Validate and register a partner YAML definition."""
    cli_log = _setup_logging()
    try:
        resolved_partners_dir = _resolve_partners_dir(partners_dir)
    except FileNotFoundError as exc:
        _fail(str(exc), json_output, 3)

    if file_path == "-":
        raw = sys.stdin.read()
    else:
        try:
            raw = Path(file_path).read_text()
        except OSError as exc:
            _fail(str(exc), json_output, 1)

    try:
        result = register_partner(raw, resolved_partners_dir, force=force, dry_run=dry_run)
    except (yaml.YAMLError, ValueError) as exc:
        _fail(str(exc), json_output, 1)
    except FileExistsError as exc:
        _fail(str(exc), json_output, 2)

    partner = result.partner
    cli_log.info("generate partner=%s dry_run=%s created=%s", partner.partner, dry_run, result.created)
    payload_dps = [dp for dp in partner.datapoints if dp.pattern in _PAYLOAD_PATTERNS]
    payload_dp_names = {dp.name for dp in payload_dps}

    if json_output:
        click.echo(
            json.dumps(
                {
                    "status": "ok",
                    "partner": partner.partner,
                    "description": partner.description,
                    "directory": f"partners/{partner.partner}",
                    "file": f"partners/{partner.partner}/partner.yaml",
                    "created": result.created,
                    "datapoints": [
                        {
                            "name": dp.name,
                            "pattern": dp.pattern,
                            "endpoints": [{"method": ep.method, "path": ep.path} for ep in dp.endpoints],
                            "admin_routes": dp.name in payload_dp_names,
                        }
                        for dp in partner.datapoints
                    ],
                },
                indent=2,
            )
        )
        return

    if dry_run:
        dir_note, file_note = "(dry run)", "(dry run)"
    elif not result.created:
        dir_note, file_note = "(exists)", "(overwritten)"
    else:
        dir_note, file_note = "(created)", "(written)"

    click.echo(f"Partner:     {partner.partner}")
    click.echo(f"Description: {partner.description}")
    click.echo(f"Directory:   partners/{partner.partner}/ {dir_note}")
    click.echo(f"File:        partners/{partner.partner}/partner.yaml {file_note}")
    click.echo()
    click.echo("Consumer endpoints:")
    for dp in partner.datapoints:
        for ep in dp.endpoints:
            tag = dp.pattern if ep.step is None else f"{dp.pattern} step {ep.step}"
            click.echo(f"  {ep.method:<7} {ep.path:<45} [{tag}]")

    if payload_dps:
        click.echo()
        click.echo("Admin endpoints:")
        for dp in payload_dps:
            base = f"/imnot/admin/{partner.partner}/{dp.name}/payload"
            click.echo(f"  {'POST':<7} {base}")
            click.echo(f"  {'GET':<7} {base}")
            click.echo(f"  {'POST':<7} {base}/session")
            click.echo(f"  {'GET':<7} {base}/session/{{session_id}}")
            if dp.pattern == "callback":
                retrigger = f"/imnot/admin/{partner.partner}/{dp.name}/callback/{{request_id}}/retrigger"
                click.echo(f"  {'POST':<7} {retrigger}")

    click.echo()
    if dry_run:
        click.echo("Dry run — no files written.")
    else:
        click.echo("Run `imnot start` or call POST /imnot/admin/reload to activate.")


# ---------------------------------------------------------------------------
# imnot \1
# ---------------------------------------------------------------------------


@cli.group()
def export() -> None:
    """Export imnot configuration to external formats."""


@export.command("postman")
@click.option(
    "--out",
    default="imnot-collection.json",
    show_default=True,
    help="Output file path.",
)
@click.option(
    "--partners-dir",
    default=str(DEFAULT_PARTNERS_DIR),
    show_default=True,
    help="Directory containing partner YAML definitions.",
)
@click.option(
    "--partner",
    "selected_partners",
    multiple=True,
    metavar="NAME",
    help="Include only this partner (repeatable). Omit to include all.",
)
def export_postman(out: str, partners_dir: str, selected_partners: tuple[str, ...]) -> None:
    """Generate a Postman collection v2.1 JSON file from loaded partner definitions."""
    cli_log = _setup_logging()
    try:
        resolved = _resolve_partners_dir(partners_dir)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    partners = load_partners(resolved)
    if not partners:
        click.echo("No partners loaded — nothing to export.", err=True)
        raise SystemExit(1)

    if selected_partners:
        available = {p.partner for p in partners}
        unknown = [name for name in selected_partners if name not in available]
        if unknown:
            click.echo(
                f"Unknown partner(s): {', '.join(unknown)}. Available: {', '.join(sorted(available))}",
                err=True,
            )
            raise SystemExit(1)
        partners = [p for p in partners if p.partner in set(selected_partners)]

    base_url = load_config(_resolve_config()).server.base_url
    collection = build_postman_collection(partners, base_url=base_url)
    out_path = Path(out)
    out_path.write_text(json.dumps(collection, indent=2))

    stats = collection_stats(partners)
    cli_log.info("export postman out=%s partners=%d", out_path, stats["partners"])
    click.echo(f"Collection written to {out_path}")
    click.echo(f"  Partners : {stats['partners']} ({', '.join(stats['partner_names'])})")
    click.echo(
        f"  Requests : {stats['total_requests']}"
        f" ({stats['consumer_requests']} consumer, {stats['admin_requests']} admin)"
    )


# ---------------------------------------------------------------------------
# imnot \1
# ---------------------------------------------------------------------------


@cli.group()
def payload() -> None:
    """Inspect and upload datapoint payloads."""


@payload.command("get")
@click.argument("partner")
@click.argument("datapoint")
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to the SQLite database file.")
def payload_get(partner: str, datapoint: str, db: str) -> None:
    """Print the current global payload for PARTNER/DATAPOINT."""
    store = _open_store(db)
    result = store.get_global_payload(partner, datapoint)
    store.close()

    if result is None:
        click.echo(f"No global payload set for {partner}/{datapoint}.")
        raise SystemExit(1)

    click.echo(f"Partner:    {partner}")
    click.echo(f"Datapoint:  {datapoint}")
    click.echo(f"Updated at: {result['updated_at']}")
    click.echo()
    click.echo(json.dumps(result["payload"], indent=2))


@payload.command("set")
@click.argument("partner")
@click.argument("datapoint")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to the SQLite database file.")
def payload_set(partner: str, datapoint: str, file: str, db: str) -> None:
    """Upload a global payload for PARTNER/DATAPOINT from a JSON FILE."""
    try:
        data = json.loads(Path(file).read_text())
    except json.JSONDecodeError as exc:
        click.echo(f"Invalid JSON in {file}: {exc}", err=True)
        raise SystemExit(1)

    store = _open_store(db)
    store.store_global_payload(partner, datapoint, data)
    store.close()

    click.echo(f"Global payload set for {partner}/{datapoint}.")


# ---------------------------------------------------------------------------
# imnot \1
# ---------------------------------------------------------------------------


@cli.group()
def sessions() -> None:
    """Manage sessions."""


@sessions.command("clear")
@click.option("--db", default=str(DEFAULT_DB), show_default=True, help="Path to the SQLite database file.")
@click.confirmation_option(prompt="This will delete all sessions. Continue?")
def sessions_clear(db: str) -> None:
    """Delete all sessions from the store."""
    store = _open_store(db)
    count = store.clear_sessions()
    store.close()
    click.echo(f"Cleared {count} session(s).")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_db(given: str) -> Path:
    """Resolve the database file path.

    If *given* exists (absolute or relative to CWD), return it.
    Otherwise walk up the directory tree looking for the filename.
    Raises ``FileNotFoundError`` if nothing is found.
    """
    given_path = Path(given)
    if given_path.is_absolute():
        if given_path.exists():
            return given_path
        raise FileNotFoundError(f"Database '{given}' not found. Has the server been started yet?")
    if given_path.exists():
        return given_path.resolve()
    # Walk up from CWD looking for the filename
    name = given_path.name
    current = Path.cwd()
    while True:
        candidate = current / name
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        f"Database '{given}' not found in {Path.cwd()} or any parent directory. Has the server been started yet?"
    )


def _resolve_pid(given: str) -> Path:
    """Resolve the PID file path, walking up from CWD if needed."""
    given_path = Path(given)
    if given_path.is_absolute():
        if given_path.exists():
            return given_path
        raise FileNotFoundError(f"PID file '{given}' not found. Is the server running?")
    if given_path.exists():
        return given_path.resolve()
    name = given_path.name
    current = Path.cwd()
    while True:
        candidate = current / name
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise FileNotFoundError(
        f"PID file '{given}' not found in {Path.cwd()} or any parent directory. Is the server running?"
    )


def _open_store(db: str) -> SessionStore:
    try:
        db_path = _resolve_db(db)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)
    store = SessionStore(db_path=db_path)
    store.init()
    return store
