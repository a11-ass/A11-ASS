"""Unified structured error envelope for every tool in the MCP service.

The MCP client must never see raw ``httpx``/``pydantic``/``mcp`` stack traces;
all surface errors are mapped to one of the ``ErrorCode`` constants below and
serialized through :class:`MCPErrorPayload`.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    """Closed set of error codes returned to MCP clients."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    BACKEND_TIMEOUT = "BACKEND_TIMEOUT"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    BACKEND_API_ERROR = "BACKEND_API_ERROR"
    BACKEND_INVALID_RESPONSE = "BACKEND_INVALID_RESPONSE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorDetail(BaseModel):
    """Single error detail block, embedded inside :class:`MCPErrorPayload`."""

    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class MCPErrorPayload(BaseModel):
    """Top-level error envelope — what an MCP client receives on failure.

    Serialized as::

        {"error": {"code": "...", "message": "...", "details": {...}}}
    """

    error: ErrorDetail


class ToolError(Exception):
    """Raised by tool handlers to signal a structured failure to the SDK.

    The MCP layer catches it and emits a :class:`MCPErrorPayload` to the client
    instead of leaking the raw Python exception text.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_payload(self) -> MCPErrorPayload:
        return MCPErrorPayload(
            error=ErrorDetail(code=self.code, message=self.message, details=self.details)
        )


def build_error_payload(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
) -> MCPErrorPayload:
    """Convenience helper for ad-hoc error construction."""
    return MCPErrorPayload(
        error=ErrorDetail(code=code, message=message, details=details or {})
    )
