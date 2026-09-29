"""MCP server: one tool `ask_first_workspace`.

Flow:
    1. GET  {base_url}/api/v1/workspaces            (Bearer key) → first workspace slug
    2. POST {base_url}/api/v1/workspace/{slug}/chat  (Bearer key, {message, mode:"chat"})
    3. return AI text reply

Transport: stateless Streamable HTTP (protocol 2026-07-28), endpoint POST /mcp.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from mcp.server import MCPServer

from .config import Settings, load_settings

try:  # SDK ≥ 2.0
    from mcp.types.version import LATEST_PROTOCOL_VERSION as PROTOCOL_VERSION
except Exception:  # pragma: no cover
    PROTOCOL_VERSION = "2026-07-28"


def create_server(settings: Settings | None = None) -> MCPServer:
    cfg = settings or load_settings()

    mcp = MCPServer(
        name="anythingllm-mcp",
        version="0.1.0",
        description="Ask AnythingLLM's first workspace a question and return the AI reply.",
        instructions=(
            "Single tool `ask_first_workspace(message)` — looks up the first "
            "AnythingLLM workspace and sends the user's question to it, "
            "returning the workspace's AI answer text."
        ),
    )

    @mcp.tool(
        name="ask_first_workspace",
        description="Ask AnythingLLM's first workspace a question; return the AI reply text.",
    )
    async def ask_first_workspace(message: str) -> str:
        """Args:
            message: The question to ask the AnythingLLM first workspace.
        Returns:
            The AI reply text from the workspace.
        """
        if not cfg.api_key:
            raise RuntimeError(
                "ANYTHINGLLM_API_KEY is not set. Create one in AnythingLLM "
                "(Settings > API Keys) and export it before calling this tool."
            )
        headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=120.0) as client:
            # 1. fetch workspaces, pick the first slug
            wresp = await client.get(f"{cfg.base_url}/api/v1/workspaces", headers=headers)
            if wresp.status_code != 200:
                raise RuntimeError(f"GET /api/v1/workspaces failed: {wresp.status_code} {wresp.text[:200]}")
            wdata = wresp.json()
            workspaces = wdata.get("workspaces") if isinstance(wdata, dict) else wdata
            if not workspaces:
                raise RuntimeError("AnythingLLM has no workspaces — create one first.")
            slug = workspaces[0]["slug"]

            # 2. send chat message to that workspace
            cresp = await client.post(
                f"{cfg.base_url}/api/v1/workspace/{slug}/chat",
                headers=headers,
                json={"message": message, "mode": "chat"},
            )
            if cresp.status_code != 200:
                raise RuntimeError(f"POST /workspace/{slug}/chat failed: {cresp.status_code} {cresp.text[:200]}")
            cdata = cresp.json()
            reply = cdata.get("textResponse") or cdata.get("text") or ""
            if not reply:
                raise RuntimeError(f"Empty reply from workspace '{slug}'. Raw: {json.dumps(cdata)[:300]}")
            return reply

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(_request: Any) -> Any:
        from starlette.responses import JSONResponse

        return JSONResponse(
            {
                "status": "healthy",
                "service": "anythingllm-mcp",
                "protocol_version": PROTOCOL_VERSION,
                "anythingllm": cfg.base_url,
            }
        )

    return mcp


def create_app(settings: Settings | None = None) -> Any:
    """Return the ASGI app: POST /mcp (MCP) + GET /health."""
    return create_server(settings).streamable_http_app(stateless_http=True)
