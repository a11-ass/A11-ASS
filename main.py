"""prist 程序入口（组合根）。"""

from __future__ import annotations

import argparse
import importlib
import sys
import threading
import time

# Windows 终端编码修复
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from pathlib import Path

from prist.core import AgentService
from prist.core.domain.errors import ConfigurationError
from prist.core.domain.prompts import build_system_prompt
from prist.core.domain.skill_loader import discover_skills
from prist.core.infrastructure.config import (
    PROJECT_ROOT,
    create_default_config,
    load_settings,
    config_exists,
    config_is_mock,
)
from prist.core.infrastructure.llm_client import OpenAICompatibleClient
from prist.core.infrastructure.tools import (
    build_default_registry,
    get_context_archive,
    load_mcp_async,
    shutdown_mcp,
)

UI_ENTRYPOINTS: dict[str, tuple[str, str]] = {
    "tui": ("prist.ui.tui.app", "PristApp"),
    "cli": ("prist.ui.cli_app", "CliApp"),
}


def _find_agents_md() -> Path | None:
    """在 cwd 和项目根找 AGENTS.md。"""
    for p in (Path.cwd() / "AGENTS.md", PROJECT_ROOT / "AGENTS.md"):
        if p.is_file():
            return p
    return None


def build_agent(config_path: str | None = None):
    """装配核心服务，返回 (agent, mcp_loader_thread)。"""
    settings = load_settings(config_path)
    skills = discover_skills()

    agents_md = _find_agents_md()
    system_prompt = build_system_prompt(skills, agents_md_path=agents_md)

    archive_dir = Path(PROJECT_ROOT) / ".agents" / "context"
    tools = build_default_registry(
        settings, skills, archive_dir=archive_dir, mcp_async=True,
    )

    agent = AgentService(
        llm=OpenAICompatibleClient(settings),
        tools=tools,
        system_prompt=system_prompt,
        archive=get_context_archive(),
        context_window=settings.app.context_window,
        compact_trigger_ratio=settings.app.compact_trigger_ratio,
    )
    # 保留 app 层配置 + MCP 状态
    agent._app_settings = settings.app
    return agent


def load_ui(name: str):
    """按名称动态加载界面类。"""
    module_name, class_name = UI_ENTRYPOINTS[name]
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="prist - 支持本地工具调用的智能体")
    parser.add_argument("--ui", choices=sorted(UI_ENTRYPOINTS), default="tui",
                        help="界面类型（默认 tui）")
    parser.add_argument("--config", default=None, help="配置文件路径（默认 config.ini）")
    args = parser.parse_args(argv)

    # ---------- config.ini 首次启动检查 ----------
    import os as _os
    print(f"🚀 prist v2 启动中  cwd={_os.getcwd()}")

    config_path = Path(args.config) if args.config else None
    config_p = config_path or (Path.cwd() / "config.ini")
    if not config_p.is_file():
        create_default_config(PROJECT_ROOT / "config.ini")
        print(f"⚠️  未找到 config.ini，已在 {PROJECT_ROOT / 'config.ini'} 创建默认模板。")
        print("   请修改 api_key 后重新启动 prist。")
        print("   （如果不修改，prist 仍能启动，但大模型调用会失败。）")
    elif config_is_mock(config_p):
        print(f"⚠️  config.ini 中的 api_key 还是默认值，请修改后重启。")

    try:
        agent = build_agent(args.config)
    except ConfigurationError as exc:
        print("配置错误: %s" % exc, file=sys.stderr)
        return 1

    app_class = load_ui(args.ui)
    print(f"   App 类: {app_class.__module__}.{app_class.__name__}")
    print(f"   工具数: {len(agent._tools.names)} (本地)")
    agents_md = _find_agents_md()
    if agents_md:
        print(f"   ✅ 注入 AGENTS.md: {agents_md}")
    print(f"   📦 上下文窗口: {agent.context_window} (从 config.ini 读取)")
    print(f"   🔌 MCP: 后台连接中（先进入 TUI）...")
    sys.stdout.flush()

    try:
        app = app_class(agent)

        # 启动 TUI 之前先注册 MCP 异步加载回调
        if args.ui == "tui":
            # 启动 TUI 后再触发 MCP 异步加载
            def _on_mcp_done():
                try:
                    app.call_from_thread(app.refresh_mcp)
                except Exception:
                    pass
            # TUI 的 run() 是阻塞的，用 call_from_thread 从后台线程刷新
            mcp_thread = load_mcp_async(agent._tools, on_done=_on_mcp_done)
        else:
            mcp_thread = None
            # CLI 模式直接同步连
            try:
                mcp_thread = load_mcp_async(agent._tools)
                mcp_thread.join(timeout=15)
            except Exception:
                pass

        app.run()
    finally:
        shutdown_mcp()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
