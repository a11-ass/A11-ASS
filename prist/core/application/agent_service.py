"""应用服务：一轮对话的完整编排 + /compact 命令 + Token 监控。"""

from __future__ import annotations

import re
from typing import Iterator

from ..domain.events import (
    AgentEvent,
    CompactCompleted,
    CompactStarted,
    TextDelta,
    ToolFinished,
    ToolStarted,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
)
from ..domain.models import ChatMessage, ToolCall
from ..domain.ports import LLMClient
from ..domain.prompts import SYSTEM_PROMPT
from .context_manager import (
    COMPACT_TRIGGER_RATIO,
    DEFAULT_CONTEXT_WINDOW,
    ContextArchive,
    ContextCompressor,
    estimate_messages_tokens,
)
from .registry import ToolRegistry


# ---------- 已知 Skill 的本地 fallback ----------

def _apply_mini_encryption(text: str) -> str:
    table = str.maketrans("0123456789", "零一二三四五六七八九")
    return text.translate(table)


_KNOWN_SKILL_FALLBACKS: dict[str, callable] = {
    "mini-encryption": _apply_mini_encryption,
}


class AgentService:
    """持有会话历史，按事件流方式推进对话。"""

    _skill_name_pattern_cache: dict[str, re.Pattern[str]] = {}

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        system_prompt: str = SYSTEM_PROMPT,
        archive: ContextArchive | None = None,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        compact_trigger_ratio: float = 0.80,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._system_prompt = system_prompt
        self._messages: list[ChatMessage] = []
        self._archive = archive  # None 表示不归档 / 不压缩
        self._compressor: ContextCompressor | None = None
        self._context_window = context_window
        self._compact_trigger_ratio = compact_trigger_ratio
        if archive:
            self._compressor = ContextCompressor(
                llm=llm, archive=archive, context_window=context_window
            )
        self.reset()

    # ---------- 会话状态 ----------

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        return tuple(self._messages)

    @property
    def context_window(self) -> int:
        return self._context_window

    def current_tokens(self) -> int:
        return estimate_messages_tokens(self._messages)

    def context_ratio(self) -> float:
        return self.current_tokens() / self._context_window

    def needs_compact(self) -> bool:
        return self.context_ratio() >= self._compact_trigger_ratio

    def reset(self) -> None:
        self._messages = [ChatMessage(role="system", content=self._system_prompt)]

    # ---------- /compact ----------

    def is_compact_command(self, text: str) -> bool:
        return text.strip().lower() in ("/compact", "/compress", "/c")

    def run_compact(self) -> Iterator[AgentEvent]:
        """执行上下文压缩，产出 CompactStarted → CompactCompleted。"""
        if not self._compressor or not self._archive:
            yield TurnFailed(message="当前 Agent 未配置上下文压缩能力（缺少 archive）。")
            return

        yield CompactStarted()

        try:
            new_messages, archive_id = self._compressor.run_compact(
                self._messages, self._system_prompt
            )
            self._messages = new_messages
            yield CompactCompleted(archive_id=archive_id, summary_tokens=estimate_messages_tokens(new_messages))
        except Exception as exc:
            yield TurnFailed(message=f"压缩失败: {exc}")

    # ---------- Skill 名称匹配 ----------

    def _extract_skill_names(self) -> tuple[str, ...]:
        names: list[str] = []
        in_section = False
        for line in self._system_prompt.splitlines():
            if "## 可用技能" in line:
                in_section = True
                continue
            if in_section and line.startswith("##"):
                break
            m = re.match(r"\s*-\s*\*\*([^*]+)\*\*", line)
            if m:
                names.append(m.group(1).strip())
        return tuple(names)

    def _match_skill_name_in_text(self, text: str) -> str | None:
        skill_names = self._extract_skill_names()
        if not skill_names or not text:
            return None
        text_outside_json = re.sub(r'"[^"\\]*(?:\\.[^"\\]*)*"', '""', text)
        for name in skill_names:
            pattern = self._skill_name_pattern_cache.get(name)
            if pattern is None:
                pattern = re.compile(rf'(?<![a-zA-Z0-9\-]){re.escape(name)}(?![a-zA-Z0-9\-])')
                self._skill_name_pattern_cache[name] = pattern
            if pattern.search(text_outside_json):
                return name
        return None

    def _is_loadskill_in_tools(self) -> bool:
        return "loadSkill" in self._tools.names

    # ---------- run_turn ----------

    def run_turn(self, user_text: str) -> Iterator[AgentEvent]:
        question = user_text.strip()
        if not question:
            return

        # 拦截 /compact 命令
        if self.is_compact_command(question):
            yield from self.run_compact()
            return

        # 阈值检查：达到 80% 警告 + 暂停
        if self.needs_compact():
            tokens = self.current_tokens()
            ratio = self.context_ratio() * 100
            yield TurnFailed(
                message=(
                    f"⚠️ 上下文已达 {ratio:.0f}%（{tokens} / {self._context_window} tokens）。"
                    f"请执行 /compact 压缩后再继续对话。"
                )
            )
            return

        self._messages.append(ChatMessage(role="user", content=question))
        yield TurnStarted(user_text=question)

        try:
            reply = self._llm.complete(self._messages, self._tools.specs)
            tool_calls = list(reply.tool_calls)

            autofallback_skill: str | None = None
            if not tool_calls and self._is_loadskill_in_tools():
                matched = self._match_skill_name_in_text(reply.content or "")
                if matched:
                    autofallback_skill = matched
                    tool_calls = [ToolCall(
                        id="skill-autofallback-" + matched,
                        name="loadSkill",
                        arguments={"name": matched},
                    )]

            if tool_calls:
                self._messages.append(
                    ChatMessage(
                        role="assistant",
                        content=reply.content,
                        tool_calls=list(reply.tool_calls) if reply.tool_calls else tool_calls,
                    )
                )
                for call in tool_calls:
                    yield ToolStarted(name=call.name, arguments=call.arguments)
                    result = self._tools.invoke(call.name, call.arguments)
                    yield ToolFinished(name=call.name, ok=result.ok, output=result.output)
                    self._messages.append(
                        ChatMessage(role="tool", content=result.output, tool_call_id=call.id)
                    )

                chunks: list[str] = []
                for delta in self._llm.stream(self._messages):
                    if not delta:
                        continue
                    chunks.append(delta)
                    yield TextDelta(text=delta)
                answer = "".join(chunks)

                overrides_delta = False
                if autofallback_skill and autofallback_skill in _KNOWN_SKILL_FALLBACKS:
                    encrypted = _KNOWN_SKILL_FALLBACKS[autofallback_skill](question)
                    answer = (
                        f"【本地 Skill 执行】mini-encryption →\n"
                        f"原文: {question}\n加密后: {encrypted}"
                    )
                    overrides_delta = True

                self._messages.append(ChatMessage(role="assistant", content=answer))
                yield TurnCompleted(text=answer, overrides_delta=overrides_delta)
            else:
                answer = reply.content or ""
                if answer:
                    yield TextDelta(text=answer)
                self._messages.append(ChatMessage(role="assistant", content=answer))
                yield TurnCompleted(text=answer)

        except Exception as exc:
            yield TurnFailed(message=_format_error(exc))


def _format_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text if text else type(exc).__name__
