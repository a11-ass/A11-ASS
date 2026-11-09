"""MCP Client —— 连接外部 MCP Server，动态注册工具到 prist。

设计：
  - 每个 MCP Server 在独立线程里运行 asyncio 事件循环
  - 用 `async with` 嵌套（transport + ClientSession）确保 dispatcher 正确启动
  - 内部挂永不完成的 Future 保持连接持久化
  - call_tool 通过 asyncio.run_coroutine_threadsafe 提交
  - 工具命名: "{server_name}_{tool_name}"
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..application.registry import FunctionTool
from ..domain.models import ToolSpec


# ==========================================================================
# 单个 MCP Server 连接
# ==========================================================================

class MCPServerConnection:
    """一个 MCP Server 的长连接。"""

    def __init__(self, server_name: str, config: dict[str, Any]) -> None:
        self.server_name = server_name
        self.config = config
        self.loop: asyncio.AbstractEventLoop | None = None
        self.session: Any = None  # ClientSession（在 async with 内持有）
        self.thread: threading.Thread | None = None
        self._connected = False
        self._error: str | None = None
        self._tools: list[dict[str, Any]] = []
        self._shutdown_event: asyncio.Event | None = None  # 在 loop 内创建
        self._ready_event = threading.Event()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def tools(self) -> list[dict[str, Any]]:
        return list(self._tools)

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        self._error = None
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        self._ready_event.wait(timeout=15)
        return self._connected

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop

        async def _persist():
            """用 async with 嵌套建立连接，然后持久等待 shutdown。"""
            mcp_type = self.config.get("type", "streamable_http")

            try:
                if mcp_type == "streamable_http":
                    from mcp.client.streamable_http import streamable_http_client
                    transport_cm = streamable_http_client(self.config["url"])
                elif mcp_type == "stdio":
                    from mcp.client.stdio import stdio_client
                    transport_cm = stdio_client(
                        self.config["command"], self.config.get("args", [])
                    )
                else:
                    self._error = f"不支持的 MCP 类型: {mcp_type}"
                    self._ready_event.set()
                    return

                async with transport_cm as (read, write):
                    from mcp.client.session import ClientSession
                    async with ClientSession(read, write) as session:
                        self.session = session
                        await session.initialize()

                        result = await session.list_tools()
                        tools = getattr(result, "tools", [])
                        self._tools = [
                            {
                                "name": t.name,
                                "description": t.description or "",
                                "inputSchema": getattr(
                                    t, "inputSchema", {"type": "object", "properties": {}}
                                ),
                            }
                            for t in tools
                        ]
                        self._connected = True
                        self._shutdown_event = asyncio.Event()
                        self._ready_event.set()

                        # 持久等待 shutdown
                        await self._shutdown_event.wait()
            except Exception as e:
                self._error = f"{type(e).__name__}: {e}"
                self._connected = False
                self._ready_event.set()

        try:
            loop.run_until_complete(_persist())
        finally:
            try:
                loop.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 调用工具
    # ------------------------------------------------------------------

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if not self._connected or self.loop is None or self.session is None:
            return f"错误: MCP Server [{self.server_name}] 未连接 ({self._error or 'unknown'})"

        async def _call():
            result = await self.session.call_tool(tool_name, arguments)
            content = getattr(result, "content", [])
            if not content:
                return "(无返回内容)"
            parts = []
            for c in content:
                if hasattr(c, "text") and c.text:
                    parts.append(c.text)
                elif hasattr(c, "data"):
                    parts.append(json.dumps(c.data, ensure_ascii=False))
                else:
                    parts.append(str(c))
            return "\n".join(parts)

        try:
            future = asyncio.run_coroutine_threadsafe(_call(), self.loop)
            return future.result(timeout=30)
        except TimeoutError:
            return f"错误: MCP 工具 {tool_name} 调用超时"
        except Exception as e:
            return f"错误: MCP 工具 {tool_name} 调用失败 - {e}"

    # ------------------------------------------------------------------
    # 断开
    # ------------------------------------------------------------------

    def disconnect(self) -> None:
        if self.loop and self.loop.is_running() and self._shutdown_event:
            # Event.set() 是普通方法，不是 coroutine，用 call_soon_threadsafe
            self.loop.call_soon_threadsafe(self._shutdown_event.set)
        if self.thread:
            self.thread.join(timeout=5)
        self._connected = False


# ==========================================================================
# MCPClient —— 管理多个 Server
# ==========================================================================

class MCPClient:
    """管理多个 MCP Server，把它们的工具注册为 prist FunctionTool。"""

    def __init__(self, config_path: Path | str | None = None) -> None:
        self.config_path = Path(config_path) if config_path else Path.cwd() / ".mcp.json"
        self.connections: dict[str, MCPServerConnection] = {}
        self._tool_map: dict[str, tuple[str, str]] = {}

    @classmethod
    def from_project_root(cls, project_root: Path | str) -> "MCPClient":
        return cls(Path(project_root) / ".mcp.json")

    def load_and_connect(self) -> list[FunctionTool]:
        if not self.config_path.exists():
            print(f"[MCP] {self.config_path} 不存在，跳过")
            return []

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            print(f"[MCP] 读取 .mcp.json 失败: {e}")
            return []

        servers = config.get("mcpServers", {})
        if not servers:
            print("[MCP] 配置里没有 mcpServers")
            return []

        all_tools: list[FunctionTool] = []
        for server_name, server_config in servers.items():
            all_tools.extend(self._connect_one(server_name, server_config))

        connected = sum(1 for c in self.connections.values() if c.connected)
        print(f"[MCP] {connected}/{len(servers)} Server 连接, {len(all_tools)} 个工具")
        for name, conn in self.connections.items():
            status = "✅" if conn.connected else "❌"
            err = f" ({conn.error})" if conn.error else ""
            print(f"  {status} {name}: {len(conn.tools)} 工具{err}")

        return all_tools

    def _connect_one(self, server_name: str, server_config: dict) -> list[FunctionTool]:
        conn = MCPServerConnection(server_name, server_config)
        self.connections[server_name] = conn

        if not conn.connect():
            return []

        registered: list[FunctionTool] = []
        for t in conn.tools:
            safe_server = server_name.replace("-", "_").replace(".", "_")
            safe_tool = t["name"].replace("-", "_").replace(".", "_")
            tool_name = f"{safe_server}_{safe_tool}"

            base = tool_name
            i = 1
            while tool_name in self._tool_map:
                tool_name = f"{base}_{i}"
                i += 1
            self._tool_map[tool_name] = (server_name, t["name"])

            orig_name = t["name"]

            def make_handler(c: MCPServerConnection, orig: str) -> Callable:
                def handler(args: dict) -> str:
                    return c.call_tool(orig, args)
                return handler

            schema = t["inputSchema"]
            if "type" not in schema:
                schema = {"type": "object", "properties": schema.get("properties", {})}

            spec = ToolSpec(
                name=tool_name,
                description=f"[MCP:{server_name}] {t['description'] or t['name']}",
                parameters=schema,
            )

            registered.append(FunctionTool(spec=spec, handler=make_handler(conn, orig_name)))

        return registered

    def shutdown(self) -> None:
        for conn in self.connections.values():
            conn.disconnect()
        self.connections.clear()
        self._tool_map.clear()

    def get_status(self) -> dict:
        """返回 MCP 状态摘要（给侧栏 / /mcp 命令用）。"""
        servers = []
        total_tools = 0
        for name, conn in self.connections.items():
            servers.append({
                "name": name,
                "connected": conn.connected,
                "tools": [t["name"] for t in conn.tools],
                "error": getattr(conn, "error", None),
            })
            total_tools += len(conn.tools)
        return {
            "servers": servers,
            "tool_count": total_tools,
            "connected": sum(1 for s in servers if s["connected"]),
        }


__all__ = ["MCPClient", "MCPServerConnection"]
