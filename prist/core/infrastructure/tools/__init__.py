"""默认工具集：系统 + 文件 + CLI + Web + Office + loadSkill + createSkill + recallContext + MCP。"""

from __future__ import annotations

import threading
from pathlib import Path

from ...domain.skill_loader import SkillIndex
from ..config import PROJECT_ROOT, Settings
from ...application.context_manager import ContextArchive
from ...application.registry import FunctionTool, ToolRegistry
from ..mcp_client import MCPClient
from .cli_tools import build_cli_tools
from .create_skill_tool import build_createSkill_tool
from .file_tools import FILE_TOOLS
from .office_tools import build_office_tools
from .recall_tool import build_recallContext_tool
from .skill_tools import build_loadSkill_tool
from .system_tools import SYSTEM_TOOLS
from .web_tools import build_web_tools

_mcp_client: MCPClient | None = None
_mcp_loader: threading.Thread | None = None
_context_archive: ContextArchive | None = None


def get_mcp_client() -> MCPClient | None:
    return _mcp_client


def get_context_archive() -> ContextArchive | None:
    return _context_archive


def build_default_registry(
    settings: Settings,
    skills: SkillIndex | None = None,
    archive_dir: Path | None = None,
    mcp_async: bool = False,
) -> ToolRegistry:
    global _context_archive

    tools: list[FunctionTool] = [*SYSTEM_TOOLS, *FILE_TOOLS]
    tools.extend(build_cli_tools())
    tools.extend(build_web_tools(settings.search))
    tools.extend(build_office_tools())
    tools.append(build_loadSkill_tool(skills or SkillIndex()))
    tools.append(build_createSkill_tool(Path(PROJECT_ROOT)))

    # recallContext 工具
    if archive_dir is None:
        archive_dir = Path(PROJECT_ROOT) / ".agents" / "context"
    _context_archive = ContextArchive(archive_dir)
    tools.append(build_recallContext_tool(archive_dir))

    if not mcp_async:
        # 同步模式：直接连 MCP
        _load_mcp_sync(tools)

    return ToolRegistry(tools)


def _load_mcp_sync(tools: list[FunctionTool]) -> None:
    """同步连接 MCP 并追加到工具列表。"""
    global _mcp_client
    try:
        _mcp_client = MCPClient.from_project_root(PROJECT_ROOT)
        mcp_tools = _mcp_client.load_and_connect()
        tools.extend(mcp_tools)
    except Exception as e:
        print(f"[MCP] 加载异常（跳过）: {e}")
        _mcp_client = None


def load_mcp_async(registry: ToolRegistry, on_done=None) -> threading.Thread:
    """后台线程连接 MCP，完成后更新 registry 并调用 on_done 回调。"""
    global _mcp_client

    def _worker():
        global _mcp_client
        try:
            _mcp_client = MCPClient.from_project_root(PROJECT_ROOT)
            mcp_tools = _mcp_client.load_and_connect()
            for t in mcp_tools:
                registry.register(t)
            print(f"[MCP] 异步加载完成: {len(mcp_tools)} 工具")
        except Exception as e:
            print(f"[MCP] 异步加载失败（跳过）: {e}")
            _mcp_client = None
        finally:
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

    global _mcp_loader
    _mcp_loader = threading.Thread(target=_worker, daemon=True)
    _mcp_loader.start()
    return _mcp_loader


def shutdown_mcp() -> None:
    global _mcp_client
    if _mcp_client:
        _mcp_client.shutdown()
        _mcp_client = None


__all__ = [
    "FunctionTool", "build_default_registry", "load_mcp_async",
    "get_mcp_client", "get_context_archive", "shutdown_mcp",
]
