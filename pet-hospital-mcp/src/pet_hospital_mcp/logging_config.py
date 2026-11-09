"""Structured logging based on ``structlog``.

Key fields emitted for every tool call:

* ``timestamp``        — ISO-8601 UTC.
* ``tool_name``        — name of the MCP tool.
* ``params``           — redacted copy of the input parameters.
* ``status``          — ``ok`` / ``error``.
* ``duration_ms``     — wall-clock duration of the call.

Sensitive fields (``ownerPhone``, ``ownerAddr``, ``chipNo`` and their
snake_case forms) are recursively replaced with ``"***"`` before logging.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Iterable

import structlog

# Field names that must be redacted wherever they appear in a log record.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "ownerPhone",
        "owner_phone",
        "ownerAddr",
        "owner_addr",
        "chipNo",
        "chip_no",
    }
)


def _redact_value(value: Any) -> str:
    return "***"


def _redact(obj: Any) -> Any:
    """Return a deep copy of ``obj`` with every sensitive field masked."""
    if isinstance(obj, dict):
        redacted: dict[str, Any] = {}
        for key, value in obj.items():
            if isinstance(key, str) and key in SENSITIVE_KEYS:
                redacted[key] = _redact_value(value)
            else:
                redacted[key] = _redact(value)
        return redacted
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(item) for item in obj)
    return obj


def redact_params(params: Any) -> Any:
    """Public wrapper around :func:`_redact` for callers/tests."""
    try:
        return _redact(deepcopy(params))
    except Exception:  # pragma: no cover - defensive
        return "***"


def configure_logging(level: str = "INFO") -> structlog.BoundLogger:
    """Configure stdlib + structlog once at startup; return a bound logger."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys_stderr(),
        level=getattr(logging, level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys_stderr()),
        cache_logger_on_first_use=True,
    )
    return structlog.get_logger("pet_hospital_mcp")


def sys_stderr():
    """Indirection so tests can monkeypatch the destination stream."""
    import sys

    return sys.stderr


def log_tool_call(
    logger: structlog.BoundLogger,
    tool_name: str,
    params: Any,
    status: str,
    duration_ms: float,
    error_code: str | None = None,
) -> None:
    """Emit the canonical tool-call log record."""
    logger.info(
        "tool.call",
        tool_name=tool_name,
        params=redact_params(params),
        status=status,
        duration_ms=round(duration_ms, 3),
        error_code=error_code,
    )


__all__ = [
    "configure_logging",
    "log_tool_call",
    "redact_params",
    "SENSITIVE_KEYS",
]
