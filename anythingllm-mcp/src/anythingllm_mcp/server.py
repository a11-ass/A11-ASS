"""MCP server: AnythingLLM workspace / chat / document tools.

Tools:
    list_workspaces()                       — list all workspaces (name + slug)
    ask_first_workspace(message)            — chat with the first workspace
    upload_document(file_path, workspace_slug?) — upload a file and embed it

Flow (chat):
    1. GET  {base_url}/api/v1/workspaces            (Bearer key) → first workspace slug
    2. POST {base_url}/api/v1/workspace/{slug}/chat  (Bearer key, {message, mode:"chat"})
    3. return AI text reply

Flow (upload_document):
    1. POST {base_url}/api/v1/document/upload                    (multipart file)
    2. POST {base_url}/api/v1/workspace/{slug}/update-embeddings ({"adds": [location]})

Transport: stateless Streamable HTTP (protocol 2026-07-28), endpoint POST /mcp.
"""
from __future__ import annotations

import json
import mimetypes
from pathlib import Path
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
        version="0.2.0",
        description="AnythingLLM tools: list workspaces, chat with a workspace, upload & embed documents.",
        instructions=(
            "Tools: `list_workspaces()` — list all workspaces; "
            "`ask_first_workspace(message)` — send a question to the first "
            "workspace and return the AI reply; "
            "`upload_document(file_path, workspace_slug?)` — upload a local "
            "file and embed it into a workspace (first workspace if slug omitted)."
        ),
    )

    def _require_key() -> str:
        if not cfg.api_key:
            raise RuntimeError(
                "ANYTHINGLLM_API_KEY is not set. Create one in AnythingLLM "
                "(Settings > API Keys) and export it before calling this tool."
            )
        return cfg.api_key

    def _headers() -> dict[str, str]:
        return {
            "Authorization": f"Bearer {_require_key()}",
            "Content-Type": "application/json",
        }

    async def _resolve_slug(client: httpx.AsyncClient, workspace_slug: str) -> str:
        """Return the given slug, or the first workspace's slug when empty."""
        slug = workspace_slug.strip()
        if slug:
            return slug
        wresp = await client.get(f"{cfg.base_url}/api/v1/workspaces", headers=_headers())
        if wresp.status_code != 200:
            raise RuntimeError(f"GET /api/v1/workspaces failed: {wresp.status_code} {wresp.text[:200]}")
        wdata = wresp.json()
        workspaces = wdata.get("workspaces") if isinstance(wdata, dict) else wdata
        if not workspaces:
            raise RuntimeError("AnythingLLM has no workspaces — create one first.")
        return workspaces[0]["slug"]

    @mcp.tool(
        name="list_workspaces",
        description="List all AnythingLLM workspaces (name + slug).",
    )
    async def list_workspaces() -> str:
        """Returns: one line per workspace, '- name (slug: xxx)'."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            wresp = await client.get(f"{cfg.base_url}/api/v1/workspaces", headers=_headers())
            if wresp.status_code != 200:
                raise RuntimeError(f"GET /api/v1/workspaces failed: {wresp.status_code} {wresp.text[:200]}")
            wdata = wresp.json()
        workspaces = wdata.get("workspaces") if isinstance(wdata, dict) else wdata
        if not workspaces:
            return "AnythingLLM has no workspaces."
        lines = [f"- {w.get('name', '?')} (slug: {w.get('slug', '?')})" for w in workspaces]
        return "Workspaces:\n" + "\n".join(lines)

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
        async with httpx.AsyncClient(timeout=120.0) as client:
            slug = await _resolve_slug(client, "")

            cresp = await client.post(
                f"{cfg.base_url}/api/v1/workspace/{slug}/chat",
                headers=_headers(),
                json={"message": message, "mode": "chat"},
            )
            if cresp.status_code != 200:
                raise RuntimeError(f"POST /workspace/{slug}/chat failed: {cresp.status_code} {cresp.text[:200]}")
            cdata = cresp.json()
            reply = cdata.get("textResponse") or cdata.get("text") or ""
            if not reply:
                raise RuntimeError(f"Empty reply from workspace '{slug}'. Raw: {json.dumps(cdata)[:300]}")
            return reply

    @mcp.tool(
        name="upload_document",
        description=(
            "Upload a local file to AnythingLLM and embed it into a workspace. "
            "Args: file_path (local path), workspace_slug (optional, defaults to first workspace). "
            "Returns the document location and the workspace slug it was embedded into."
        ),
    )
    async def upload_document(file_path: str, workspace_slug: str = "") -> str:
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"File not found: {path}")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        async with httpx.AsyncClient(timeout=120.0) as client:
            # 1. upload file
            with path.open("rb") as fh:
                uresp = await client.post(
                    f"{cfg.base_url}/api/v1/document/upload",
                    headers={"Authorization": f"Bearer {_require_key()}"},
                    files={"file": (path.name, fh, mime)},
                )
            if uresp.status_code != 200:
                raise RuntimeError(f"POST /api/v1/document/upload failed: {uresp.status_code} {uresp.text[:200]}")
            udata = uresp.json()
            documents = udata.get("documents") if isinstance(udata, dict) else None
            if not documents or not documents[0].get("location"):
                raise RuntimeError(f"Upload returned no document location. Raw: {json.dumps(udata)[:300]}")
            location = documents[0]["location"]

            # 2. embed into workspace
            slug = await _resolve_slug(client, workspace_slug)
            eresp = await client.post(
                f"{cfg.base_url}/api/v1/workspace/{slug}/update-embeddings",
                headers=_headers(),
                json={"adds": [location], "deletes": []},
            )
            if eresp.status_code != 200:
                raise RuntimeError(
                    f"POST /workspace/{slug}/update-embeddings failed: {eresp.status_code} {eresp.text[:200]}"
                )

        return f"Uploaded and embedded '{path.name}' -> {location} (workspace: {slug})"

    @mcp.custom_route("/health", methods=["GET"])
    async def _health(_request: Any) -> Any:
        from starlette.responses import JSONResponse

        return JSONResponse(
            {
                "status": "healthy",
                "service": "anythingllm-mcp",
                "protocol_version": PROTOCOL_VERSION,
                "anythingllm": cfg.base_url,
                "tools": ["list_workspaces", "ask_first_workspace", "upload_document"],
            }
        )

    return mcp


def create_app(settings: Settings | None = None) -> Any:
    """Return the ASGI app: POST /mcp (MCP) + GET /health."""
    return create_server(settings).streamable_http_app(stateless_http=True)
