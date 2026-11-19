from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from imnot.config import LoggingConfig

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
_STREAMS = ("imnot.cli", "imnot.http")
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ``time`` (UTC, ISO 8601), ``level``, ``logger``, ``message``.

    Fields passed as ``extra={"fields": {...}}`` are added at the top level (the HTTP log adds
    ``method``, ``path``, ``status``, ``duration_ms``…), and ``exception`` holds a traceback if any.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            entry.update({k: v for k, v in extra.items() if k not in entry})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def make_formatter(log_format: str) -> logging.Formatter:
    return JsonFormatter() if log_format == "json" else logging.Formatter(_FORMAT)


def uvicorn_log_config(log_format: str) -> dict[str, Any] | None:
    """``log_config`` for ``uvicorn.run`` in JSON mode (uvicorn's own lines to stdout as JSON).

    None in text mode: the caller then leaves ``log_config`` out, because ``log_config=None`` would turn
    uvicorn's logs off instead of keeping its defaults.
    """
    if log_format != "json":
        return None
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": "imnot.logging_setup.JsonFormatter"}},
        "handlers": {"stdout": {"class": "logging.StreamHandler", "formatter": "json", "stream": "ext://sys.stdout"}},
        "loggers": {name: {"handlers": ["stdout"], "level": "INFO", "propagate": False} for name in UVICORN_LOGGERS},
    }


class ArchivingRotatingHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that moves rotated files to an archive directory
    with a timestamp-based filename instead of .1/.2 suffixes.

    Rotation is triggered by the parent class when the file exceeds maxBytes.
    This subclass only overrides doRollover() to change the destination.
    """

    def __init__(
        self,
        filename: str,
        archived_logs_dir: Path,
        backup_name_format: str = "date",
        **kwargs,
    ) -> None:
        self._archived_logs_dir = Path(archived_logs_dir)
        self._backup_name_format = backup_name_format
        super().__init__(filename, **kwargs)

    def doRollover(self) -> None:  # type: ignore[override]
        if self.stream:
            self.stream.close()
            self.stream = None  # type: ignore[assignment]

        src = Path(self.baseFilename)
        if src.exists():
            self._archived_logs_dir.mkdir(parents=True, exist_ok=True)
            stem = src.stem  # e.g. "imnot.cli"

            if self._backup_name_format == "epoch":
                ts = str(int(datetime.now(timezone.utc).timestamp()))
            else:
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            dest = self._archived_logs_dir / f"{stem}.{ts}.log"
            counter = 2
            while dest.exists():
                dest = self._archived_logs_dir / f"{stem}.{ts}-{counter}.log"
                counter += 1

            src.rename(dest)

        if not self.delay:
            self.stream = self._open()


def configure_logging(config: LoggingConfig, log_dir: Path | None) -> None:
    """Attach rotating file handlers (and optionally stdout) to imnot.cli and imnot.http.

    Every other ``imnot.*`` logger ends up in the CLI log file, with warnings also on the console.

    With *log_dir* ``None`` (stateless mode) no file is created: everything goes to stdout.
    """
    level = logging.DEBUG if config.debug else logging.INFO
    formatter = make_formatter(config.format)

    archived_logs_dir = Path(config.archived_logs_dir)
    if log_dir is not None:
        if not archived_logs_dir.is_absolute():
            archived_logs_dir = (log_dir / archived_logs_dir).resolve()
        log_dir.mkdir(parents=True, exist_ok=True)

    cli_file: logging.Handler | None = None
    for stream in _STREAMS:
        log = logging.getLogger(stream)
        log.setLevel(level)
        log.propagate = False
        log.handlers.clear()

        if log_dir is not None:
            handler = ArchivingRotatingHandler(
                str(log_dir / f"{stream}.log"),
                archived_logs_dir=archived_logs_dir,
                backup_name_format=config.backup_name_format,
                maxBytes=config.max_bytes,
                backupCount=0,
            )
            handler.setFormatter(formatter)
            log.addHandler(handler)
            if stream == "imnot.cli":
                cli_file = handler

        if log_dir is None:
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(formatter)
            log.addHandler(sh)
        elif config.stdout:
            sh = logging.StreamHandler()
            sh.setFormatter(formatter)
            log.addHandler(sh)

    # Module loggers (imnot.loader.yaml_loader, imnot.engine.patterns.push, …) have no handler of
    # their own: route them to the CLI log file, and keep warnings on the console as before
    # (without this they only reached Python's last-resort stderr handler, never a file).
    # propagate stays True so pytest's caplog still sees them; root has no handlers by default.
    parent = logging.getLogger("imnot")
    parent.setLevel(level)
    parent.handlers.clear()
    if cli_file is not None:
        parent.addHandler(cli_file)
    console = logging.StreamHandler(sys.stdout if log_dir is None else None)
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG if config.stdout or log_dir is None else logging.WARNING)
    parent.addHandler(console)
