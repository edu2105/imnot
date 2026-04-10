"""
CLI entry point for Mirage.

Responsibilities:
- Provide the `mirage` command group via Click.
- `mirage start`:         load partner YAMLs, build the FastAPI app, launch Uvicorn.
- `mirage status`:        show active sessions in the store.
- `mirage routes`:        list all consumer and admin endpoints for loaded partners.
- `mirage payload get`:   print the current global payload for a datapoint.
- `mirage payload set`:   upload a global payload for a datapoint from a JSON file.
- `mirage sessions clear`: wipe all sessions from the store.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
import uvicorn

from mirage.api.server import create_app
from mirage.engine.router import _PAYLOAD_PATTERNS
from mirage.engine.session_store import SessionStore
from mirage.loader.yaml_loader import load_partners

DEFAULT_PARTNERS_DIR = "partners"
DEFAULT_DB = Path("mirage.db")


def _resolve_partners_dir(given: str) -> Path:
    """Resolve the partners directory path.

    If *given* exists relative to the current working directory, return it.
    Otherwise walk up the directory tree until a matching subdirectory is found.
    Raises ``FileNotFoundError`` if nothing is found.
    """
    given_path = Path(given)
    if given_path.is_absolute():
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
        f"Run from inside a Mirage project or pass --partners-dir explicitly."
    )


@click.group()
def cli() -> None:
    """Mirage — stateful API mock server for integration testing."""


# ---------------------------------------------------------------------------
# mirage start
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--partners-dir",
    default=str(DEFAULT_PARTNERS_DIR),
    show_default=True,
    help="Directory containing partner YAML definitions.",
)
@click.option(
    "--db",
    default=str(DEFAULT_DB),
    show_default=True,
    help="Path to the SQLite database file.",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host.")
@click.option("--port", default=8000, show_default=True, help="Bind port.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (development only).")
@click.option(
    "--admin-key",
    default=None,
    envvar="MIRAGE_ADMIN_KEY",
    help="Bearer token required for all /mirage/admin/* endpoints. "
         "Also readable from MIRAGE_ADMIN_KEY env var. Omit for open access (local dev only).",
)
def start(partners_dir: str, db: str, host: str, port: int, reload: bool, admin_key: str | None) -> None:
    """Load partner definitions and start the mock server."""
    try:
        resolved_partners_dir = _resolve_partners_dir(partners_dir)
    except FileNotFoundError as exc:
        click.echo(str(exc), err=True)
        raise SystemExit(1)

    db_path = Path(db)
    effective_admin_key = admin_key or None

    click.echo(f"Starting Mirage on http://{host}:{port}")

    if reload:
        # uvicorn reload mode requires a factory import string, not an app object.
        # Export configuration via env vars so create_app_from_env() can pick them up.
        os.environ["MIRAGE_PARTNERS_DIR"] = str(resolved_partners_dir)
        os.environ["MIRAGE_DB_PATH"] = str(db_path)
        if effective_admin_key:
            os.environ["MIRAGE_ADMIN_KEY"] = effective_admin_key
        uvicorn.run(
            "mirage.api.server:create_app_from_env",
            host=host,
            port=port,
            reload=True,
            reload_includes=["*.yaml"],
            factory=True,
        )
    else:
        app = create_app(
            partners_dir=resolved_partners_dir,
            db_path=db_path,
            admin_key=effective_admin_key,
        )
        uvicorn.run(app, host=host, port=port)


# ---------------------------------------------------------------------------
# mirage status
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
        click.echo(
            f"{s['session_id']:<38} {s['partner']:<12} {s['datapoint']:<16} {s['created_at']}"
        )


# ---------------------------------------------------------------------------
# mirage routes
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
                base = f"/mirage/admin/{partner.partner}/{dp.name}/payload"
                click.echo(f"    {'POST':<7} {base}")
                click.echo(f"    {'GET':<7} {base}")
                click.echo(f"    {'POST':<7} {base}/session")
                click.echo(f"    {'GET':<7} {base}/session/{{session_id}}")

    click.echo()
    click.echo("  INFRA ENDPOINTS")
    click.echo(f"    {'GET':<7} /mirage/admin/partners")
    click.echo(f"    {'GET':<7} /mirage/admin/sessions")
    click.echo(f"    {'POST':<7} /mirage/admin/reload")


# ---------------------------------------------------------------------------
# mirage payload
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
# mirage sessions
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


def _open_store(db: str) -> SessionStore:
    db_path = Path(db)
    if not db_path.exists():
        click.echo(f"No database found at {db_path}. Has the server been started yet?", err=True)
        raise SystemExit(1)
    store = SessionStore(db_path=db_path)
    store.init()
    return store
