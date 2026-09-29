"""Runtime configuration for the Pet Hospital MCP server.

All values are read from environment variables so the same image can be
deployed to different environments without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value is not None else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a float, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Resolved configuration snapshot, captured at startup time."""

    # MCP HTTP listener
    host: str
    port: int

    # Upstream Go REST API
    pet_hospital_base_url: str
    backend_timeout_seconds: float
    backend_retries: int
    backend_backoff_seconds: float

    # Runtime
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=_env_str("MCP_HOST", "127.0.0.1"),
            port=_env_int("MCP_PORT", 8100),
            pet_hospital_base_url=_env_str(
                "PET_HOSPITAL_BASE_URL", "http://127.0.0.1:8080"
            ).rstrip("/"),
            backend_timeout_seconds=_env_float("BACKEND_TIMEOUT_SECONDS", 5.0),
            backend_retries=_env_int("BACKEND_RETRIES", 2),
            backend_backoff_seconds=_env_float("BACKEND_BACKOFF_SECONDS", 0.2),
            log_level=_env_str("LOG_LEVEL", "INFO"),
        )


# Single shared settings instance — captured at import time so every module
# sees the same values without re-reading the environment on each request.
settings = Settings.from_env()
