"""MCP service entry point.

Uses the official Python SDK ``MCPServer`` (NOT the 1.x ``FastMCP``) and
exposes the service over **stateless Streamable HTTP** per protocol version
``2026-07-28``:

* no ``initialize`` handshake,
* no ``Mcp-Session-Id`` header,
* no server-side session storage,
* discovery happens via the modern ``server/discover`` method.

The HTTP endpoint is mounted at ``/mcp`` and a separate ``/health`` endpoint
is added for container probes.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer

from .config import Settings, settings as default_settings
from .errors import ToolError, build_error_payload
from .logging_config import configure_logging
from .rest_client import RestApiClient, default_client
from .tools import register_list_pets

# Protocol version is reported to clients that send the legacy ``initialize``
# handshake or the modern ``server/discover`` probe; the SDK negotiates it
# automatically from the constant above. We import it purely for documentation
# and so tests can assert the reported value.
try:  # pragma: no cover - SDK ≥ 2.0 exposes this path
    from mcp.types.version import LATEST_PROTOCOL_VERSION as PROTOCOL_VERSION
except Exception:  # pragma: no cover - keep the constant meaningful even on very old SDKs
    PROTOCOL_VERSION = "2026-07-28"

SDK_VERSION = "2.0.0"


def create_server(
    config: Settings | None = None,
    client: RestApiClient | None = None,
    logger: Any = None,
) -> MCPServer:
    """Build a configured MCPServer instance with the ``list_pets`` tool.

    Factory function — used by both the CLI entry point and the ASGI loader.
    """
    cfg = config or default_settings
    log = logger or configure_logging(cfg.log_level)

    mcp = MCPServer(
        name="pet-hospital-mcp",
        version="1.0.0",
        description="Wrap the Go pet hospital REST API as an MCP service (stage 1).",
        instructions=(
            "Provides the `list_pets` tool that proxies GET /api/v1/pets on the "
            "Go pet hospital backend. All filter/sort/pagination parameters are "
            "forwarded verbatim. Backend base URL is configurable via the "
            "PET_HOSPITAL_BASE_URL environment variable."
        ),
        log_level=cfg.log_level,
    )

    register_list_pets(mcp, client=client or default_client, logger=log)

    # ``/health`` is intentionally unauthenticated — used by container probes.
    @mcp.custom_route("/health", methods=["GET"])
    async def _health(_request: Any) -> Any:  # type: ignore[override]
        from starlette.responses import JSONResponse

        return JSONResponse(
            {
                "status": "healthy",
                "service": "pet-hospital-mcp",
                "sdk_version": SDK_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "backend": cfg.pet_hospital_base_url,
            }
        )

    return mcp


def create_app(
    config: Settings | None = None,
    client: RestApiClient | None = None,
    logger: Any = None,
) -> Any:
    """Return the Starlette ASGI app with /mcp + /health mounted.

    ``stateless_http=True`` follows the 2026-07-28 revision: no ``initialize``
    handshake, no ``Mcp-Session-Id`` header, no server-side session storage.
    """
    mcp = create_server(config=config, client=client, logger=logger)
    return mcp.streamable_http_app(stateless_http=True)


async def list_pets_handler(
    raw_input: dict[str, Any],
    client: RestApiClient | None = None,
    logger: Any = None,
) -> dict[str, Any]:
    """Module-level re-export of the tool handler — for direct unit testing."""
    from .tools.list_pets import handle_list_pets

    return await handle_list_pets(raw_input, client=client, logger=logger)


__all__ = [
    "create_app",
    "create_server",
    "list_pets_handler",
    "PROTOCOL_VERSION",
    "SDK_VERSION",
]
