from __future__ import annotations

import os
import re
import tomllib
import typing
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Literal, Mapping


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    partners_dir: str = "partners"
    db: str = "imnot.db"
    base_url: str = "http://localhost:8000"
    stop_timeout_seconds: float = 5.0


@dataclass
class LoggingConfig:
    log_dir: str = "logs"
    max_bytes: int = 10_485_760  # 10 MB
    backup_name_format: str = "date"
    archived_logs_dir: str = "./archived"
    debug: bool = False
    stdout: bool = False
    format: Literal["text", "json"] = "text"


@dataclass
class PaginationConfig:
    default_limit: int = 50


@dataclass
class UIConfig:
    enabled: bool = True
    default_theme: Literal["light", "dark", "system"] = "dark"


@dataclass
class ImnotConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    pagination: PaginationConfig = field(default_factory=PaginationConfig)
    ui: UIConfig = field(default_factory=UIConfig)


def _from_dict(cls, data: dict):
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


class ConfigError(ValueError):
    """A setting from the environment that imnot cannot use."""


# Every key of these imnot.toml sections can also be set as IMNOT_<SECTION>_<KEY> (e.g. IMNOT_LOGGING_FORMAT,
# IMNOT_UI_ENABLED), so a container needs no imnot.toml. [server] is not here: its settings already have
# their own names (IMNOT_BIND_HOST, IMNOT_DB_PATH…, see cli.py), and one setting gets one name.
ENV_SECTIONS = ("logging", "pagination", "ui")
# Kubernetes injects <SERVICE>_SERVICE_HOST, <SERVICE>_PORT, <SERVICE>_PORT_8000_TCP… for every Service in the
# namespace: a Service named "imnot-ui" gives IMNOT_UI_PORT and friends. Those are skipped, not errors.
_K8S_SERVICE_LINK = re.compile(r"(SERVICE_HOST|SERVICE_PORT(_\w+)?|PORT(_\d+_(TCP|UDP|SCTP)(_PROTO|_PORT|_ADDR)?)?)")
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _coerce(name: str, raw: str, kind: Any) -> Any:
    value = raw.strip()
    if typing.get_origin(kind) is Literal:
        choices = typing.get_args(kind)
        if value.lower() in choices:
            return value.lower()
        raise ConfigError(f"{name}={raw!r}: expected one of {', '.join(choices)}")
    if kind is bool:
        if value.lower() in _TRUE | _FALSE:
            return value.lower() in _TRUE
        raise ConfigError(f"{name}={raw!r}: expected true or false (1/0, yes/no, on/off)")
    if kind in (int, float):
        try:
            return kind(value)
        except ValueError:
            raise ConfigError(f"{name}={raw!r}: expected a number") from None
    return raw


def _apply_env(config: ImnotConfig, environ: Mapping[str, str]) -> None:
    for name, raw in environ.items():
        for section_name in ENV_SECTIONS:
            prefix = f"IMNOT_{section_name.upper()}_"
            if not name.startswith(prefix):
                continue
            section = getattr(config, section_name)
            hints = typing.get_type_hints(type(section))
            key = name[len(prefix) :].lower()
            if key not in hints:
                if _K8S_SERVICE_LINK.fullmatch(key.upper()):
                    continue
                known = ", ".join(prefix + k.upper() for k in hints)
                raise ConfigError(f"{name}: unknown setting. Known: {known}")
            setattr(section, key, _coerce(name, raw, hints[key]))


def load_config(path: Path | None, environ: Mapping[str, str] | None = None) -> ImnotConfig:
    """Load imnot.toml from *path* (all defaults if None or absent), then apply IMNOT_<SECTION>_<KEY> overrides.

    Raises ConfigError for an unknown or malformed IMNOT_LOGGING_* / IMNOT_PAGINATION_* / IMNOT_UI_* variable.
    """
    config = ImnotConfig()
    if path is not None and path.exists():
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        config = ImnotConfig(
            server=_from_dict(ServerConfig, data.get("server", {})),
            logging=_from_dict(LoggingConfig, data.get("logging", {})),
            pagination=_from_dict(PaginationConfig, data.get("pagination", {})),
            ui=_from_dict(UIConfig, data.get("ui", {})),
        )
    _apply_env(config, os.environ if environ is None else environ)
    return config
