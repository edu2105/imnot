"""Tests for imnot.config — load_config and dataclass defaults."""

from __future__ import annotations

import pytest

from imnot.config import (
    ConfigError,
    ImnotConfig,
    LoggingConfig,
    PaginationConfig,
    ServerConfig,
    UIConfig,
    load_config,
)

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
    assert c.log_dir == "logs"
    assert c.max_bytes == 10_485_760
    assert c.backup_name_format == "date"
    assert c.archived_logs_dir == "./archived"
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


# ---------------------------------------------------------------------------
# PaginationConfig
# ---------------------------------------------------------------------------


def test_pagination_config_defaults():
    c = PaginationConfig()
    assert c.default_limit == 50


def test_load_config_pagination_section(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[pagination]\ndefault_limit = 25\n", encoding="utf-8")
    config = load_config(toml)
    assert config.pagination.default_limit == 25


def test_load_config_pagination_default_when_absent(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[server]\nport = 8001\n", encoding="utf-8")
    config = load_config(toml)
    assert config.pagination.default_limit == 50


def test_load_config_pagination_unknown_keys_ignored(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[pagination]\ndefault_limit = 10\nunknown_key = 99\n", encoding="utf-8")
    config = load_config(toml)
    assert config.pagination.default_limit == 10


def test_imnot_config_has_pagination_field():
    config = load_config(None)
    assert isinstance(config.pagination, PaginationConfig)
    assert config.pagination.default_limit == 50


# ---------------------------------------------------------------------------
# UIConfig
# ---------------------------------------------------------------------------


def test_ui_config_defaults():
    c = UIConfig()
    assert c.enabled is True
    assert c.default_theme == "dark"


def test_imnot_config_has_ui_field():
    config = load_config(None)
    assert isinstance(config.ui, UIConfig)
    assert config.ui.enabled is True
    assert config.ui.default_theme == "dark"


def test_load_config_ui_section(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text('[ui]\nenabled = false\ndefault_theme = "dark"\n', encoding="utf-8")
    config = load_config(toml)
    assert config.ui.enabled is False
    assert config.ui.default_theme == "dark"


def test_load_config_ui_defaults_when_absent(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[server]\nport = 8001\n", encoding="utf-8")
    config = load_config(toml)
    assert config.ui.enabled is True
    assert config.ui.default_theme == "dark"


def test_load_config_ui_unknown_keys_ignored(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text("[ui]\nenabled = true\nunknown_key = 42\n", encoding="utf-8")
    config = load_config(toml)
    assert config.ui.enabled is True


def test_imnot_toml_template_shows_the_real_defaults():
    """The template written by `imnot start` says "All values shown are defaults": keep it true."""
    import re
    import tomllib

    from imnot.cli import _IMNOT_TOML_TEMPLATE
    from imnot.config import ImnotConfig

    uncommented = re.sub(r"^# ?(\[|[a-z_]+ =)", r"\1", _IMNOT_TOML_TEMPLATE, flags=re.M)
    uncommented = re.sub(r"\s+#.*$", "", uncommented, flags=re.M)
    shown = tomllib.loads(uncommented)
    defaults = ImnotConfig()
    for section, values in shown.items():
        for key, value in values.items():
            assert getattr(getattr(defaults, section), key) == value, f"[{section}] {key}"


# ---------------------------------------------------------------------------
# IMNOT_<SECTION>_<KEY> overrides
# ---------------------------------------------------------------------------


def test_env_overrides_every_type():
    cfg = load_config(
        None,
        {
            "IMNOT_LOGGING_FORMAT": "JSON",
            "IMNOT_LOGGING_DEBUG": "yes",
            "IMNOT_LOGGING_MAX_BYTES": "2048",
            "IMNOT_LOGGING_LOG_DIR": "/var/log/imnot",
            "IMNOT_UI_ENABLED": "off",
            "IMNOT_UI_DEFAULT_THEME": "light",
            "IMNOT_PAGINATION_DEFAULT_LIMIT": "7",
        },
    )
    assert cfg.logging.format == "json"
    assert cfg.logging.debug is True
    assert cfg.logging.max_bytes == 2048
    assert cfg.logging.log_dir == "/var/log/imnot"
    assert cfg.ui.enabled is False
    assert cfg.ui.default_theme == "light"
    assert cfg.pagination.default_limit == 7


def test_env_wins_over_the_toml(tmp_path):
    toml = tmp_path / "imnot.toml"
    toml.write_text('[logging]\nformat = "text"\ndebug = true\n[ui]\nenabled = true\n')
    cfg = load_config(toml, {"IMNOT_LOGGING_FORMAT": "json", "IMNOT_UI_ENABLED": "0"})
    assert cfg.logging.format == "json"
    assert cfg.logging.debug is True  # not overridden, the toml value stays
    assert cfg.ui.enabled is False


def test_server_section_and_other_variables_are_not_read_this_way():
    # [server] settings have their own names (IMNOT_BIND_HOST…) handled by the CLI.
    cfg = load_config(None, {"IMNOT_SERVER_HOST": "0.0.0.0", "IMNOT_BIND_HOST": "0.0.0.0", "HOME": "/x"})
    assert cfg.server.host == "127.0.0.1"


def test_default_reads_os_environ(monkeypatch):
    monkeypatch.setenv("IMNOT_UI_DEFAULT_THEME", "system")
    assert load_config(None).ui.default_theme == "system"


@pytest.mark.parametrize(
    "env, message",
    [
        ({"IMNOT_UI_ENABLE": "1"}, "unknown setting. Known: IMNOT_UI_ENABLED, IMNOT_UI_DEFAULT_THEME"),
        ({"IMNOT_LOGGING_FORMAT": "yaml"}, "expected one of text, json"),
        ({"IMNOT_LOGGING_STDOUT": "maybe"}, "expected true or false"),
        ({"IMNOT_PAGINATION_DEFAULT_LIMIT": "ten"}, "expected a number"),
    ],
)
def test_bad_env_values_are_errors(env, message):
    with pytest.raises(ConfigError, match=message):
        load_config(None, env)


def test_kubernetes_service_links_are_skipped():
    # A Service named "imnot-ui" or "imnot-logging" in the namespace injects these into every pod.
    env = {
        "IMNOT_UI_PORT": "tcp://10.0.0.1:80",
        "IMNOT_UI_SERVICE_HOST": "10.0.0.1",
        "IMNOT_UI_SERVICE_PORT": "80",
        "IMNOT_UI_SERVICE_PORT_HTTP": "80",
        "IMNOT_UI_PORT_80_TCP": "tcp://10.0.0.1:80",
        "IMNOT_UI_PORT_80_TCP_ADDR": "10.0.0.1",
        "IMNOT_LOGGING_PORT_8000_TCP_PROTO": "tcp",
        "IMNOT_UI_BACKEND_SERVICE_HOST": "10.0.0.2",  # a Service named "imnot-ui-backend"
        "IMNOT_UI_BACKEND_PORT": "tcp://10.0.0.2:80",
    }
    assert load_config(None, env).ui.enabled is True
    with pytest.raises(ConfigError, match="IMNOT_UI_PORTS: unknown setting"):
        load_config(None, {"IMNOT_UI_PORTS": "1"})
