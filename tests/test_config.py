"""Tests for imnot.config — load_config and dataclass defaults."""

from __future__ import annotations

from imnot.config import ImnotConfig, LoggingConfig, ServerConfig, load_config

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_server_config_defaults():
    c = ServerConfig()
    assert c.host == "127.0.0.1"
    assert c.port == 8000
    assert c.partners_dir == "partners"
    assert c.db == "imnot.db"
    assert c.base_url == "http://localhost:8000"
    assert c.stop_timeout_seconds == 5.0


def test_logging_config_defaults():
    c = LoggingConfig()
    assert c.log_dir == "."
    assert c.max_bytes == 10_485_760
    assert c.backup_name_format == "date"
    assert c.archived_logs_dir == "./archived-logs"
    assert c.debug is False
    assert c.stdout is False


def test_load_config_none_returns_defaults():
    config = load_config(None)
    assert isinstance(config, ImnotConfig)
    assert config.server.port == 8000
    assert config.logging.debug is False


def test_load_config_missing_file_returns_defaults(tmp_path):
    config = load_config(tmp_path / "nonexistent.toml")
    assert config.server.host == "127.0.0.1"


# ---------------------------------------------------------------------------
# Loading from file
# ---------------------------------------------------------------------------


def test_load_config_server_section(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text(
        '[server]\nhost = "0.0.0.0"\nport = 9000\nbase_url = "http://myserver:9000"\n',
        encoding="utf-8",
    )
    config = load_config(toml)
    assert config.server.host == "0.0.0.0"
    assert config.server.port == 9000
    assert config.server.base_url == "http://myserver:9000"
    # unset keys keep defaults
    assert config.server.db == "imnot.db"


def test_load_config_logging_section(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text(
        "[logging]\ndebug = true\nstdout = true\nmax_bytes = 1048576\n",
        encoding="utf-8",
    )
    config = load_config(toml)
    assert config.logging.debug is True
    assert config.logging.stdout is True
    assert config.logging.max_bytes == 1_048_576
    # unset keys keep defaults
    assert config.logging.backup_name_format == "date"


def test_load_config_partial_keys(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[server]\nport = 7777\n", encoding="utf-8")
    config = load_config(toml)
    assert config.server.port == 7777
    assert config.server.host == "127.0.0.1"  # default preserved


def test_load_config_unknown_keys_ignored(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[server]\nport = 8080\nunknown_key = 42\n", encoding="utf-8")
    config = load_config(toml)
    assert config.server.port == 8080


def test_load_config_empty_file(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("", encoding="utf-8")
    config = load_config(toml)
    assert config.server.port == 8000
    assert config.logging.debug is False


def test_load_config_stop_timeout(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[server]\nstop_timeout_seconds = 10.5\n", encoding="utf-8")
    config = load_config(toml)
    assert config.server.stop_timeout_seconds == 10.5
