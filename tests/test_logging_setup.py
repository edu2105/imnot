"""Tests for imnot.logging_setup — ArchivingRotatingHandler and configure_logging."""

from __future__ import annotations

import logging

import pytest

from imnot.config import LoggingConfig
from imnot.logging_setup import ArchivingRotatingHandler, configure_logging

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_loggers():
    """Remove all handlers from imnot.cli and imnot.http and re-enable propagation."""
    for name in ("imnot.cli", "imnot.http"):
        log = logging.getLogger(name)
        log.handlers.clear()
        log.propagate = True


@pytest.fixture(autouse=True)
def restore_loggers():
    yield
    _clean_loggers()


# ---------------------------------------------------------------------------
# configure_logging — file creation
# ---------------------------------------------------------------------------


def test_configure_logging_creates_log_files(tmp_path):
    configure_logging(LoggingConfig(), log_dir=tmp_path)
    logging.getLogger("imnot.cli").info("hello cli")
    logging.getLogger("imnot.http").info("hello http")
    assert (tmp_path / "imnot.cli.log").exists()
    assert (tmp_path / "imnot.http.log").exists()


def test_configure_logging_creates_log_dir(tmp_path):
    log_dir = tmp_path / "nested" / "logs"
    configure_logging(LoggingConfig(), log_dir=log_dir)
    logging.getLogger("imnot.cli").info("msg")
    assert log_dir.is_dir()
    assert (log_dir / "imnot.cli.log").exists()


def test_configure_logging_propagate_false(tmp_path):
    configure_logging(LoggingConfig(), log_dir=tmp_path)
    assert logging.getLogger("imnot.cli").propagate is False
    assert logging.getLogger("imnot.http").propagate is False


def test_configure_logging_default_level_is_info(tmp_path):
    configure_logging(LoggingConfig(), log_dir=tmp_path)
    assert logging.getLogger("imnot.cli").level == logging.INFO


def test_configure_logging_debug_flag(tmp_path):
    configure_logging(LoggingConfig(debug=True), log_dir=tmp_path)
    assert logging.getLogger("imnot.cli").level == logging.DEBUG


def test_configure_logging_stdout_adds_stream_handler(tmp_path):
    configure_logging(LoggingConfig(stdout=True), log_dir=tmp_path)
    handlers = logging.getLogger("imnot.cli").handlers
    assert any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler) for h in handlers)


def test_configure_logging_idempotent(tmp_path):
    configure_logging(LoggingConfig(), log_dir=tmp_path)
    configure_logging(LoggingConfig(), log_dir=tmp_path)
    assert len(logging.getLogger("imnot.cli").handlers) == 1


# ---------------------------------------------------------------------------
# ArchivingRotatingHandler — rotation behaviour
# ---------------------------------------------------------------------------


def test_dorollover_moves_file_to_archive(tmp_path):
    archived_dir = tmp_path / "archived-logs"
    log_file = tmp_path / "imnot.cli.log"

    handler = ArchivingRotatingHandler(
        str(log_file),
        archived_logs_dir=archived_dir,
        backup_name_format="epoch",
        maxBytes=1,
        backupCount=0,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    log = logging.getLogger("_test_rotation")
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    log.propagate = False

    # Write enough to trigger rotation
    for _ in range(5):
        log.info("x" * 50)

    handler.close()
    log.removeHandler(handler)

    assert archived_dir.is_dir()
    archived = list(archived_dir.glob("imnot.cli.*.log"))
    assert len(archived) >= 1


def test_dorollover_date_format(tmp_path):
    archived_dir = tmp_path / "archived-logs"
    log_file = tmp_path / "imnot.cli.log"
    log_file.write_text("existing content\n")

    handler = ArchivingRotatingHandler(
        str(log_file),
        archived_logs_dir=archived_dir,
        backup_name_format="date",
        maxBytes=0,
        backupCount=0,
        delay=True,
    )
    handler.doRollover()
    handler.close()

    archived = list(archived_dir.glob("imnot.cli.*.log"))
    assert len(archived) == 1
    # Name should match date pattern YYYY-MM-DD
    import re

    assert re.search(r"\d{4}-\d{2}-\d{2}", archived[0].name)


def test_dorollover_epoch_format(tmp_path):
    archived_dir = tmp_path / "archived-logs"
    log_file = tmp_path / "imnot.cli.log"
    log_file.write_text("content\n")

    handler = ArchivingRotatingHandler(
        str(log_file),
        archived_logs_dir=archived_dir,
        backup_name_format="epoch",
        maxBytes=0,
        backupCount=0,
        delay=True,
    )
    handler.doRollover()
    handler.close()

    archived = list(archived_dir.glob("imnot.cli.*.log"))
    assert len(archived) == 1
    import re

    assert re.search(r"\d{10}", archived[0].name)


def test_dorollover_same_day_collision(tmp_path):
    archived_dir = tmp_path / "archived-logs"
    archived_dir.mkdir()
    log_file = tmp_path / "imnot.cli.log"

    # Pre-create a file with today's date to force collision
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (archived_dir / f"imnot.cli.{today}.log").write_text("old")

    log_file.write_text("new content\n")
    handler = ArchivingRotatingHandler(
        str(log_file),
        archived_logs_dir=archived_dir,
        backup_name_format="date",
        maxBytes=0,
        backupCount=0,
        delay=True,
    )
    handler.doRollover()
    handler.close()

    archived = list(archived_dir.glob("imnot.cli.*.log"))
    assert len(archived) == 2
    names = {f.name for f in archived}
    assert f"imnot.cli.{today}-2.log" in names


def test_dorollover_creates_archive_dir(tmp_path):
    archived_dir = tmp_path / "deep" / "archive"
    log_file = tmp_path / "imnot.cli.log"
    log_file.write_text("content\n")

    handler = ArchivingRotatingHandler(
        str(log_file),
        archived_logs_dir=archived_dir,
        maxBytes=0,
        backupCount=0,
        delay=True,
    )
    handler.doRollover()
    handler.close()

    assert archived_dir.is_dir()
