"""prist v17 — 斜杠命令 + MCP 异步加载 + Session 持久化 + config.ini 参数化。

v17 变更：
  1. 斜杠命令：/new /save /resume /compact /help /quit /mcp
  2. CommandPalette（Ctrl+P）命令面板补全
  3. MCP 异步加载：侧栏显示"连接中..."，连好后动态刷新
  4. Session 持久化：/save 存 .agents/sessions/*.jsonl，/resume 列出来选
  5. Spinner 间隔等从 config.ini 读取
  6. AGENTS.md 自动注入 System Prompt
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static, TextArea
from textual.binding import Binding

from rich.panel import Panel
from rich.text import Text
from rich.style import Style as RichStyle
from rich.box import ROUNDED as ROUNDED_BOX


# ---------- 斜杠命令定义 ----------

SLASH_COMMANDS: dict[str, tuple[str, str]] = {
    "/help": ("显示所有可用的斜杠命令", "/help"),
    "/new": ("新建会话（清空当前上下文）", "/new"),
    "/save": ("保存当前会话到 .agents/sessions/", "/save [名称]"),
    "/resume": ("列出并恢复历史会话（上/下 选择，Enter 确认，ESC 取消）", "/resume"),
    "/compact": ("压缩上下文（归档 + LLM 摘要替换）", "/compact"),
    "/mcp": ("显示已连接的 MCP 服务器和工具", "/mcp"),
    "/quit": ("退出 prist", "/quit"),
}

SESSIONS_DIR_NAME = ".agents/sessions"


# ---------- 气泡构建 ----------

def _make_user_line(text: str) -> Text:
    """用户行：■ 你：消息（单行，无框）。"""
    import re
    plain = re.sub(r'\[[^\]]+\]', '', text)
    return Text.from_markup(f"[green]■[/] [bold cyan]你：[/] [dim]{plain}[/]")


def _make_ai_panel(text: str) -> Panel:
    """AI 气泡：Rich Panel，深紫蓝实心背景 + 淡蓝边框 + 圆角。"""
    import re
    plain = re.sub(r'\[[^\]]+\]', '', text)
    content = Text.from_markup(plain)
    return Panel(
        content,
        box=ROUNDED_BOX,
        padding=(0, 1),
        border_style="#3a4a6a",
        style=RichStyle(bgcolor="#1a2744", color="#c8d8e8"),
    )


def _make_error_panel(text: str) -> Panel:
    """错误气泡：深红背景。"""
    import re
    plain = re.sub(r'\[[^\]]+\]', '', text)
    content = Text.from_markup(plain)
    return Panel(
        content,
        box=ROUNDED_BOX,
        padding=(0, 1),
        border_style="#6a3a3a",
        style=RichStyle(bgcolor="#3a1a1a", color="#e8c8c8"),
    )


def _project_root() -> Path:
    """从 import 路径推项目根。"""
    return Path(__file__).resolve().parents[4]


def _sessions_dir() -> Path:
    return _project_root() / SESSIONS_DIR_NAME


# ---------- Session 持久化 ----------

def save_session(messages: list, name: str | None = None) -> Path:
    """保存会话到 .agents/sessions/。返回保存路径。"""
    sessions_dir = _sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    if not name:
        name = datetime.now().strftime("%Y%m%d-%H%M%S")

    path = sessions_dir / f"{name}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for msg in messages:
            obj = {
                "role": msg.role,
                "content": msg.content,
            }
            # ToolCall / ToolResult 也存
            for attr in ("tool_calls", "tool_call_id", "name"):
                v = getattr(msg, attr, None)
                if v:
                    obj[attr] = v
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return path


def list_sessions() -> list[tuple[str, Path, int]]:
    """列出所有保存的会话：(名称, 路径, 消息数)。按时间倒序。"""
    sessions_dir = _sessions_dir()
    if not sessions_dir.is_dir():
        return []
    results: list[tuple[str, Path, int]] = []
    for p in sorted(sessions_dir.glob("*.jsonl"), reverse=True):
        name = p.stem
        try:
            count = sum(1 for _ in p.open("r", encoding="utf-8"))
        except OSError:
            count = 0
        results.append((name, p, count))
    return results


def load_session(path: Path) -> list:
    """从 jsonl 恢复消息列表。"""
    from prist.core.domain.models import ChatMessage
    messages = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            messages.append(ChatMessage(
                role=obj.get("role", "user"),
                content=obj.get("content", ""),
            ))
    return messages


# ---------- PristApp ----------

class PristApp(App):
    TITLE = "prist 智能体 v17"
    SUB_TITLE = "Enter 发送 · Ctrl+J 换行 · Ctrl+P 命令面板 · /help"

    BINDINGS = [
        Binding("enter", "send", "发送", show=False, priority=True),
        Binding("ctrl+j", "newline", "换行", show=False, priority=True),
        Binding("ctrl+p", "command_palette", "命令面板"),
        Binding("ctrl+c", "quit", "退出"),
        Binding("ctrl+l", "clear_log", "清屏"),
        Binding("ctrl+n", "new_session", "新会话"),
    ]

    CSS = """
    Screen { layout: vertical; }
    #main-area { height: 1fr; width: 1fr; }
    #left-col { width: 3fr; height: 1fr; }
    #log { height: 1fr; width: 1fr; border: none; padding: 0 1; }
    #spinner-bar { width: 1fr; height: auto; border: none; padding: 0 1; }
    #sidebar { width: 1fr; height: 1fr; border: round $primary; padding: 0 1; background: $surface; }
    #input-area { dock: bottom; border: round $primary-darken-2; padding: 0 1; margin: 0 0 1 0; height: auto; }
    #ta { width: 100%; height: 4; border: solid $primary-darken-1; padding: 0 1; margin: 0; }
    #cmd-popup { dock: bottom; height: auto; border: round $accent; padding: 0 1; margin: 0 1; background: $surface; }
    #cmd-popup-hidden { display: none; }
    """

    awaiting = False
    SPINNER_FRAMES = ["|", "/", "-", "\\"]
    THINKING_STATES = [
        "🤔 AI 思考中", "🤔 正在联网搜索", "🤔 正在调用工具", "🤔 正在组织回复",
    ]

    def __init__(self, agent) -> None:
        super().__init__()
        self._agent = agent
        self._ai_buffer: list[str] = []
        self._tool_count = 0
        self._last_tool_ok: list[tuple[str, bool]] = []
        self._tool_history: list[tuple[str, str, bool, str]] = []
        self._spinner_idx = 0
        # MCP 状态（刷新时用）
        self._mcp_status = "连接中..."
        self._mcp_servers: list[str] = []
        # 会话恢复选择状态
        self._resume_visible = False
        self._resume_cursor = 0
        # config 参数（从 agent 里拿）
        app_settings = getattr(agent, "_app_settings", None)
        if app_settings:
            self._spinner_interval = app_settings.spinner_interval
        else:
            self._spinner_interval = 0.15

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            with Vertical(id="left-col"):
                yield RichLog(id="log", wrap=True, highlight=False, markup=True, auto_scroll=True)
                yield Static("", id="spinner-bar", markup=True)
            yield Static(id="sidebar", markup=True)
        with Vertical(id="input-area"):
            yield TextArea(id="ta", placeholder="Enter 发送 · Ctrl+J 换行 · /help 看命令")
        yield Static("", id="cmd-popup", markup=True)
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[bold cyan]🎉 prist v17 启动！[/]")
        log.write(f"[dim]本地工具: {len(self._agent._tools.names)} 个  MCP: 连接中...[/]")

        # AGENTS.md 提示
        from pathlib import Path
        agents_path = Path.cwd() / "AGENTS.md"
        if agents_path.is_file():
            log.write(f"[dim]✅ 注入 AGENTS.md[/]")

        log.write(f"[dim]上下文窗口: {self._agent.context_window}[/]")
        log.write("")
        self._refresh_sidebar()
        self.query_one("#ta", TextArea).focus()
        self.set_interval(self._spinner_interval, self._tick_spinner)

    # ---------- Command Palette ----------

    def action_command_palette(self) -> None:
        """Ctrl+P：弹出 Textual 内置的命令面板（搜索命令）。"""
        from textual.command import DiscoveryHit, Hit, Provider
        from textual.command import CommandPalette as _Palette

        # 直接用 Textual 的 run_action
        # 但我们的命令都是 send '/xxx'，所以直接显示补全面板
        self._show_cmd_popup("输入斜杠命令：", list(SLASH_COMMANDS.keys()))

    # ---------- 发送 ----------

    def action_send(self) -> None:
        self._do_send()

    def _do_send(self) -> None:
        if self.awaiting:
            return
        ta = self.query_one("#ta", TextArea)
        text = ta.text.strip()
        if not text:
            return
        ta.clear()
        self._hide_cmd_popup()

        # 斜杠命令拦截
        if text.startswith("/"):
            self._handle_command(text)
            return

        self._run_turn_async(text)

    # ---------- 换行 ----------

    def action_newline(self) -> None:
        ta = self.query_one("#ta", TextArea)
        start, end = ta.selection
        ta._replace_via_keyboard("\n", start, end)

    # ---------- Slash complete ----------

    def action_slash_complete(self) -> None:
        """输入 / 时弹出命令补全面板。"""
        ta = self.query_one("#ta", TextArea)
        text = ta.text.strip()
        if text == "/":
            # 直接弹出所有命令
            self._show_cmd_popup("选择命令（点击或回车）：", list(SLASH_COMMANDS.keys()), filter_text="")
        elif text.startswith("/"):
            self._show_cmd_popup("过滤：", list(SLASH_COMMANDS.keys()), filter_text=text[1:])

    def _show_cmd_popup(self, title: str, cmds: list[str], filter_text: str = "") -> None:
        popup = self.query_one("#cmd-popup", Static)
        filtered = [c for c in cmds if filter_text.lower() in c.lower()] if filter_text else cmds
        if not filtered:
            popup.update(f"[dim]（无匹配）[/]")
            return
        lines = [f"[bold]{title}[/]"]
        for c in filtered[:10]:
            desc = SLASH_COMMANDS[c][0]
            lines.append(f" [yellow]{c}[/] — [dim]{desc}[/]")
        popup.update("\n".join(lines))
        popup.styles.height = "auto"

    def _hide_cmd_popup(self) -> None:
        popup = self.query_one("#cmd-popup", Static)
        popup.update("")

    # ---------- 斜杠命令处理 ----------

    def _handle_command(self, text: str) -> None:
        log = self.query_one("#log", RichLog)
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/help", "?"):
            log.write("[bold]📋 可用斜杠命令：[/]")
            for name, (desc, usage) in SLASH_COMMANDS.items():
                log.write(f"  [yellow]{usage}[/] — [dim]{desc}[/]")
            log.write("")

        elif cmd in ("/quit", "/q", "/exit"):
            self.exit()

        elif cmd in ("/new", "/reset"):
            self._agent.reset()
            self._ai_buffer = []
            self._tool_count = 0
            self._tool_history = []
            log.clear()
            log.write("[dim]🆕 已开启新会话[/]")
            log.write("")
            self._hide_spinner()
            self._refresh_sidebar()

        elif cmd == "/save":
            path = save_session(self._agent.messages, arg or None)
            log.write(f"[green]💾 已保存会话 →[/] [dim]{path}[/]")
            log.write("")

        elif cmd == "/resume":
            self._handle_resume()

        elif cmd in ("/compact", "/compress", "/c"):
            self._run_compact()

        elif cmd in ("/mcp", "/tools"):
            self._show_mcp_status()

        else:
            log.write(f"[dim]未知命令：{cmd}（输入 /help 查看所有命令）[/]")

    # ---------- /resume ----------

    def _handle_resume(self) -> None:
        log = self.query_one("#log", RichLog)
        sessions = list_sessions()
        if not sessions:
            log.write("[dim]（没有保存的会话）[/]")
            log.write("")
            return

        log.write("[bold]📚 历史会话：[/]")
        for i, (name, path, count) in enumerate(sessions[:10]):
            log.write(f"  [dim]{i+1}.[/] [bold]{name}[/] [dim]({count} 条消息)[/]")
        log.write("")
        log.write("[dim]提示：复制上面的名称后输入 /resume <名称> 来恢复[/]")
        log.write("")

        # 如果带了参数，直接恢复
        ta = self.query_one("#ta", TextArea)
        text = ta.text.strip()
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            target = parts[1].strip()
            for name, path, _ in sessions:
                if name == target or path.stem == target:
                    self._agent._messages = load_session(path)
                    log.clear()
                    log.write(f"[green]📚 已恢复会话：{name}[/]")
                    log.write("")
                    self._refresh_sidebar()
                    return
            log.write(f"[dim]未找到会话：{target}[/]")

    # ---------- /compact ----------

    def _run_compact(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write(_make_user_line("/compact"))
        log.write("")
        self._show_spinner()

        def _worker():
            try:
                # 先保存原始会话
                archive_dir = _project_root() / ".agents" / "context"
                archive_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                save_session(self._agent.messages, name=f"pre-compact-{ts}")

                # 跑压缩
                for event in self._agent.run_compact():
                    self._handle_event(event)
            finally:
                self.call_from_thread(self._hide_spinner)
                self.call_from_thread(self._on_turn_done)

        threading.Thread(target=_worker, daemon=True).start()

    # ---------- /mcp ----------

    def _show_mcp_status(self) -> None:
        log = self.query_one("#log", RichLog)
        from prist.core.infrastructure.tools import get_mcp_client
        client = get_mcp_client()
        if client is None:
            log.write("[dim]🔌 MCP 未连接[/]")
        else:
            info = client.get_status() if hasattr(client, "get_status") else {}
            servers = info.get("servers", [])
            total_tools = info.get("tool_count", 0)
            log.write(f"[bold]🔌 MCP 状态：[/]")
            for s in servers:
                name = s.get("name", "?")
                tools = s.get("tools", [])
                log.write(f"  [green]✅[/] {name} [dim]({len(tools)} 工具)[/]")
                for t in tools:
                    log.write(f"     • [yellow]{t}[/]")
            log.write(f"  [dim]合计 {len(servers)} 个 Server，{total_tools} 个工具[/]")
        log.write("")

    # ---------- backend ----------

    def _run_turn_async(self, question: str) -> None:
        log = self.query_one("#log", RichLog)
        log.write(_make_user_line(question))
        log.write("")
        self._ai_buffer = []
        self._show_spinner()
        threading.Thread(target=self._run_turn_worker, args=(question,), daemon=True).start()

    def _run_turn_worker(self, question: str) -> None:
        try:
            for event in self._agent.run_turn(question):
                self._handle_event(event)
        finally:
            self.call_from_thread(self._hide_spinner)
            self.call_from_thread(self._on_turn_done)

    def _on_turn_done(self) -> None:
        self._refresh_sidebar()

    def _handle_event(self, event) -> None:
        self.call_from_thread(self._render_event, event)

    def _render_event(self, event) -> None:
        from prist.core.domain.events import (
            CompactCompleted, CompactStarted,
            ToolStarted, ToolFinished, TextDelta, TurnCompleted, TurnFailed,
        )

        log = self.query_one("#log", RichLog)

        if isinstance(event, ToolStarted):
            args_str = ", ".join(f"{k}={v}" for k, v in event.arguments.items())
            self._tool_history.append((event.name, args_str, True, ""))
        elif isinstance(event, ToolFinished):
            status = event.ok
            short_out = event.output[:120].replace("\n", " ")
            if len(event.output) > 120:
                short_out += "..."
            if self._tool_history and self._tool_history[-1][0] == event.name:
                name, args, _, _ = self._tool_history[-1]
                self._tool_history[-1] = (name, args, status, short_out)
            else:
                self._tool_history.append((event.name, "", status, short_out))
            self._tool_history = self._tool_history[-8:]
            self._tool_count += 1
        elif isinstance(event, TextDelta):
            self._ai_buffer.append(event.text)
        elif isinstance(event, TurnCompleted):
            if event.overrides_delta:
                answer = event.text
                self._ai_buffer = []
            else:
                answer = "".join(self._ai_buffer).strip()
                self._ai_buffer = []
            if answer:
                log.write(_make_ai_panel(answer))
            else:
                log.write("[dim]（AI 未返回文本回复）[/]")
            log.write("")
        elif isinstance(event, TurnFailed):
            log.write(_make_error_panel(f"💥 错误: {event.message}"))
            log.write("")
            self._ai_buffer = []
        elif isinstance(event, CompactStarted):
            log.write("[bold yellow]📦 开始压缩上下文...[/]")
            log.write("")
        elif isinstance(event, CompactCompleted):
            log.write(f"[bold green]✅ 上下文压缩完成！[/] 归档 `{event.archive_id}`  摘要约 {event.summary_tokens} tokens")
            log.write("")
        self._refresh_sidebar()

    # ---------- spinner ----------

    def _tick_spinner(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(self.SPINNER_FRAMES)
        self._refresh_sidebar()
        self._refresh_spinner_bar()

    def _refresh_spinner_bar(self) -> None:
        sb = self.query_one("#spinner-bar", Static)
        if self.awaiting:
            frame = self.SPINNER_FRAMES[self._spinner_idx]
            hint = self.THINKING_STATES[self._tool_count % len(self.THINKING_STATES)]
            sb.update(f"[dim]{hint} {frame}[/]")
        else:
            sb.update("")

    def _show_spinner(self) -> None:
        self.awaiting = True
        self._refresh_spinner_bar()

    def _hide_spinner(self) -> None:
        self.awaiting = False
        self._refresh_spinner_bar()

    # ---------- MCP 异步刷新 ----------

    def refresh_mcp(self) -> None:
        """MCP 后台加载完成后，从主线程调用刷新侧栏。"""
        from prist.core.infrastructure.tools import get_mcp_client
        client = get_mcp_client()
        if client is not None:
            try:
                info = client.get_status() if hasattr(client, "get_status") else {}
                self._mcp_servers = [s.get("name", "?") for s in info.get("servers", [])]
                total = info.get("tool_count", 0)
                self._mcp_status = f"✅ {len(self._mcp_servers)} Server, {total} tools"
            except Exception as e:
                self._mcp_status = f"❌ 连接失败"
                self._mcp_servers = []
        else:
            self._mcp_status = "❌ 连接失败"
            self._mcp_servers = []
        self._refresh_sidebar()

    # ---------- sidebar ----------

    def _refresh_sidebar(self) -> None:
        sidebar = self.query_one("#sidebar", Static)
        tools = self._agent._tools.names
        mcp_names = [n for n in tools if "MCP" in n or "_MCP_" in n or n.startswith("Bazi_")]
        local_names = [n for n in tools if n not in mcp_names]

        # 1. MCP 区域
        lines = [f"🔌 MCP: {self._mcp_status}"]
        if self._mcp_servers:
            for s in self._mcp_servers[:3]:
                lines.append(f"  [dim]•[/] [yellow]{s}[/]")

        # 2. 工具列表（折叠）
        lines.append(f"\n📦 工具({len(tools)})")
        show = local_names[:5]
        for n in show:
            lines.append(f" • {n}")
        if len(local_names) > 5:
            lines.append(f" [dim]+{len(local_names)-5} 个[/dim]")
        if mcp_names:
            lines.append(f" [dim]+{len(mcp_names)} MCP[/dim]")

        # 3. 最近调用
        recent_lines = ["\n🔨 调用"]
        recent = self._tool_history[-2:] if self._tool_history else []
        if recent:
            for name, args, ok, out in reversed(recent):
                tag = "[green]✓[/]" if ok else "[red]✗[/]"
                recent_lines.append(f" {tag} [bold]{name}[/]")
        else:
            recent_lines.append(" (无)")

        # 4. 会话
        msg_count = len(self._agent.messages)
        ctx_tokens = self._agent.current_tokens()
        ctx_window = self._agent.context_window
        ctx_ratio = ctx_tokens / ctx_window
        pct = int(ctx_ratio * 100)

        if ctx_ratio >= 0.90:
            pct_color = "red"
        elif ctx_ratio >= 0.80:
            pct_color = "yellow"
        else:
            pct_color = "green"

        filled = int(ctx_ratio * 10)
        bar = "█" * filled + "░" * (10 - filled)
        ctx_k = ctx_tokens / 1024
        win_k = ctx_window / 1024

        session_lines = [
            "\n📊 会话",
            f"  消息:{msg_count}  调用:{self._tool_count}",
            f"  上下文:[bold]{ctx_k:.1f}k[/]/{win_k:.0f}k[dim]默认[/] [{pct_color}]{pct}%[/]",
            f"  [{pct_color}]{bar}[/]",
        ]
        if ctx_ratio >= 0.80:
            session_lines.append("  [yellow]⚠️ /compact[/]")

        # 5. Spinner 或就绪
        if self.awaiting:
            frame = self.SPINNER_FRAMES[self._spinner_idx]
            session_lines.append(f"  ⏳ {frame}")
        else:
            session_lines.append("  ✅ 就绪")

        # 6. 命令提示
        session_lines.append("\n[dim]Ctrl+P 命令[/]")

        sidebar.update("\n".join(lines + recent_lines + session_lines))

    # ---------- shortcuts ----------

    def action_clear_log(self) -> None:
        self.query_one("#log", RichLog).clear()
        self.query_one("#log", RichLog).write("[dim]（已清屏）[/]")

    def action_new_session(self) -> None:
        self._agent.reset()
        self._ai_buffer = []
        self._tool_count = 0
        self._tool_history = []
        self.query_one("#log", RichLog).clear()
        self.query_one("#log", RichLog).write("[dim]🆕 已开启新会话[/]")
        self._hide_spinner()
        self._refresh_sidebar()
