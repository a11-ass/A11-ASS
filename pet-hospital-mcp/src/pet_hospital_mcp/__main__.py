"""CLI entry point — ``python -m pet_hospital_mcp``.

Boots the stateless Streamable HTTP server using ``uvicorn``. The MCP
endpoint is mounted at ``/mcp`` by the SDK; ``/health`` is also exposed.
"""

from __future__ import annotations

import uvicorn

from .config import settings
from .server import create_app


def main() -> None:
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
