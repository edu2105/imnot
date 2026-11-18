from __future__ import annotations

import logging
import logging.handlers
import sys
from datetime import datetime, timezone
from pathlib import Path

from imnot.config import LoggingConfig

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
_STREAMS = ("imnot.cli", "imnot.http")


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
    formatter = logging.Formatter(_FORMAT)

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
