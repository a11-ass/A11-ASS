"""CLI entry point: `python -m anythingllm_mcp` starts uvicorn on MCP_PORT."""
from __future__ import annotations

import uvicorn

from .config import load_settings
from .server import create_app


def main() -> None:
    cfg = load_settings()
    uvicorn.run(create_app(cfg), host="127.0.0.1", port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
