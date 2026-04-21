from __future__ import annotations

import logging
import logging.handlers
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


def configure_logging(config: LoggingConfig, log_dir: Path) -> None:
    """Attach rotating file handlers (and optionally stdout) to imnot.cli and imnot.http."""
    level = logging.DEBUG if config.debug else logging.INFO
    formatter = logging.Formatter(_FORMAT)

    archived_logs_dir = Path(config.archived_logs_dir)
    if not archived_logs_dir.is_absolute():
        archived_logs_dir = (log_dir / archived_logs_dir).resolve()

    log_dir.mkdir(parents=True, exist_ok=True)

    for stream in _STREAMS:
        log = logging.getLogger(stream)
        log.setLevel(level)
        log.propagate = False
        log.handlers.clear()

        handler = ArchivingRotatingHandler(
            str(log_dir / f"{stream}.log"),
            archived_logs_dir=archived_logs_dir,
            backup_name_format=config.backup_name_format,
            maxBytes=config.max_bytes,
            backupCount=0,
        )
        handler.setFormatter(formatter)
        log.addHandler(handler)

        if config.stdout:
            sh = logging.StreamHandler()
            sh.setFormatter(formatter)
            log.addHandler(sh)
