from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


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
    log_dir: str = "."
    max_bytes: int = 10_485_760  # 10 MB
    backup_name_format: str = "date"
    archived_logs_dir: str = "./archived-logs"
    debug: bool = False
    stdout: bool = False


@dataclass
class PaginationConfig:
    default_limit: int = 50


@dataclass
class ImnotConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    pagination: PaginationConfig = field(default_factory=PaginationConfig)


def _from_dict(cls, data: dict):
    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


def load_config(path: Path | None) -> ImnotConfig:
    """Load imnot.toml from *path*. Returns all-defaults config if path is None or absent."""
    if path is None or not path.exists():
        return ImnotConfig()
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    return ImnotConfig(
        server=_from_dict(ServerConfig, data.get("server", {})),
        logging=_from_dict(LoggingConfig, data.get("logging", {})),
        pagination=_from_dict(PaginationConfig, data.get("pagination", {})),
    )
