"""上下文压缩管理器。

职责：
  1. 估算当前会话 Token 数
  2. 把原始上下文归档到 .agents/context/
  3. 调用 LLM 生成压缩摘要
  4. 用摘要替换原有历史

设计：
  - 不依赖 tiktoken，用 1 token ≈ 2.5 字符（中文）估算
  - 归档用 JSONL 格式，每行一条 ChatMessage 的 to_api() 结果
  - 压缩完成后，历史变成：[system, 摘要 user, 摘要 assistant, ...最近 N 条保留]
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Sequence

from ..domain.models import ChatMessage
from ..domain.ports import LLMClient


# ---------- 常量 ----------

DEFAULT_CONTEXT_WINDOW = 128_000      # 默认 128k（无法获取模型窗口时）
COMPACT_TRIGGER_RATIO = 0.80           # 80% 触发警告
SUMMARY_TARGET_TOKENS = 5_000           # 摘要目标长度
KEEP_RECENT_TURNS = 2                  # 压缩后保留最近 2 轮对话


# ---------- Token 估算 ----------

def estimate_tokens(text: str | None) -> int:
    """估算一段文本的 Token 数。

    中文约 1.5 字符/token，英文约 4 字符/token。做混合估算：
      中文比例高 → 2 字符/token
      英文多    → 3 字符/token
    """
    if not text:
        return 0
    # 粗略判断中文比例
    zh = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total = len(text)
    zh_ratio = zh / total if total else 0
    if zh_ratio > 0.3:
        return max(1, len(text) // 2)   # 中文为主：2 字符/token
    else:
        return max(1, len(text) // 3)   # 英文为主：3 字符/token


def estimate_messages_tokens(messages: Sequence[ChatMessage]) -> int:
    """估算整组消息的 Token 总数。"""
    total = 0
    for m in messages:
        total += estimate_tokens(m.content or "")
        if m.tool_calls:
            for tc in m.tool_calls:
                total += estimate_tokens(tc.name)
                total += estimate_tokens(json.dumps(tc.arguments, ensure_ascii=False))
        if m.tool_call_id:
            total += estimate_tokens(m.tool_call_id)
        # 每条消息的 role + 格式开销（大约 50 tokens）
        total += 50
    return total


# ---------- 压缩 Prompt ----------

COMPACT_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 recallContext 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""


# ---------- ContextArchive ----------

class ContextArchive:
    """管理 .agents/context/ 下的归档文件。"""

    def __init__(self, context_dir: Path) -> None:
        self.context_dir = Path(context_dir)
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def new_id(self) -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def archive_path(self, archive_id: str) -> Path:
        return self.context_dir / f"{archive_id}.jsonl"

    def list_archives(self) -> list[tuple[str, Path]]:
        files = sorted(self.context_dir.glob("*.jsonl"))
        return [(f.stem, f) for f in files]

    def save(self, messages: Sequence[ChatMessage]) -> str:
        """把完整消息历史写成 JSONL。返回 archive_id。"""
        archive_id = self.new_id()
        path = self.archive_path(archive_id)
        with open(path, "w", encoding="utf-8") as f:
            for m in messages:
                record = m.to_api()
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return archive_id

    def read(self, archive_id: str) -> list[dict]:
        path = self.archive_path(archive_id)
        if not path.exists():
            return []
        rows = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    def recall(self, query: str, archive_id: str | None = None, max_hits: int = 10) -> str:
        """全文关键词检索。返回可读文本，控制长度。"""
        if not query.strip():
            return "请提供需要检索的关键词。"

        keyword = query.strip().lower()

        if archive_id:
            archives = [(archive_id, self.archive_path(archive_id))]
        else:
            archives = self.list_archives()

        hits: list[str] = []
        for aid, path in archives:
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as f:
                for lineno, line in enumerate(f, 1):
                    if keyword in line.lower():
                        try:
                            record = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        role = record.get("role", "?")
                        content = record.get("content", "") or ""
                        # 前后各截取 80 字符的上下文
                        idx = content.lower().find(keyword)
                        if idx >= 0:
                            snippet = content[max(0, idx - 40): idx + len(keyword) + 80]
                        else:
                            snippet = content[:120]
                        snippet = snippet.replace("\n", " ")
                        if len(snippet) > 200:
                            snippet = snippet[:200] + "..."
                        hits.append(f"[{aid}:L{lineno} {role}] {snippet}")
                        if len(hits) >= max_hits:
                            break
                if len(hits) >= max_hits:
                    break

        if not hits:
            scope = f"归档 {archive_id}" if archive_id else "所有归档"
            return f"在{scope}中未找到包含「{query}」的记录。"

        header = f"共找到 {len(hits)} 条匹配（最多返回 {max_hits} 条）：\n"
        return header + "\n".join(hits)


# ---------- ContextCompressor ----------

class ContextCompressor:
    """执行上下文压缩流程。"""

    def __init__(
        self,
        llm: LLMClient,
        archive: ContextArchive,
        context_window: int = DEFAULT_CONTEXT_WINDOW,
    ) -> None:
        self._llm = llm
        self._archive = archive
        self.context_window = context_window

    def check_threshold(self, messages: Sequence[ChatMessage]) -> tuple[int, int, float, bool]:
        """返回 (tokens, window, ratio, should_warn)。"""
        tokens = estimate_messages_tokens(messages)
        ratio = tokens / self.context_window
        return tokens, self.context_window, ratio, ratio >= COMPACT_TRIGGER_RATIO

    def run_compact(self, messages: Sequence[ChatMessage], system_prompt: str) -> tuple[list[ChatMessage], str]:
        """执行完整压缩流程。返回 (新消息列表, archive_id)。

        新消息列表结构：
          [system, user(压缩请求), assistant(摘要), ...保留最近 N 条]
        """
        # 1. 归档原始上下文
        archive_id = self._archive.save(messages)

        # 2. 构建压缩请求
        history_text = self._format_messages_for_compact(messages)
        compact_user_msg = (
            f"{COMPACT_PROMPT}\n\n"
            f"--- 以下是需要压缩的历史上下文 ---\n\n"
            f"{history_text}\n\n"
            f"--- 历史上下文结束，共 {len(messages)} 条消息 ---"
        )

        # 3. 调 LLM 生成摘要（不带 tools，普通对话调用）
        compact_msgs = [
            ChatMessage(role="system", content="你是上下文压缩助手。只输出 Markdown 摘要。"),
            ChatMessage(role="user", content=compact_user_msg),
        ]

        try:
            reply = self._llm.complete(compact_msgs, tools=[])
            summary = (reply.content or "").strip()
        except Exception as e:
            raise RuntimeError(f"压缩调用 LLM 失败: {e}")

        if not summary:
            raise RuntimeError("LLM 返回空摘要，压缩未执行。")

        # 4. 构建归档说明
        archive_note = (
            f"\n\n---\n\n⚠️ **上下文压缩归档说明**\n\n"
            f"此前上下文已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 完成压缩，"
            f"原始上下文保存在编号为 `{archive_id}` 的归档文件中"
            f"（路径: {self._archive.archive_path(archive_id)}）。"
            f"如需查找历史信息，请使用 `recallContext` 工具。"
        )
        full_summary = summary + archive_note

        # 5. 构建新的消息列表
        # 保留：system + (user + assistant 摘要对) + 最近 N 轮 user/assistant/tool
        recent_keep: list[ChatMessage] = []
        turns = self._split_into_turns(list(messages))
        for turn in turns[-KEEP_RECENT_TURNS:]:
            recent_keep.extend(turn)

        new_messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content="请根据压缩摘要继续工作。以下是之前会话的完整摘要：\n\n" + full_summary),
            ChatMessage(role="assistant", content=f"好的，我已理解上下文摘要。之前的会话已压缩为归档 {archive_id}。有什么需要我继续做的？"),
        ]
        # 如果 recent_keep 里有实际内容，追加进去（但跳过前面已有的 system）
        if recent_keep:
            # 只保留 user/assistant/tool，跳过 system
            for m in recent_keep:
                if m.role == "system":
                    continue
                new_messages.append(m)

        return new_messages, archive_id

    # ---------- 内部 ----------

    @staticmethod
    def _split_into_turns(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
        """把扁平消息列表拆成一轮轮对话（user 是分界线）。"""
        turns: list[list[ChatMessage]] = []
        current: list[ChatMessage] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "user" and current:
                turns.append(current)
                current = []
            current.append(m)
        if current:
            turns.append(current)
        return turns

    @staticmethod
    def _format_messages_for_compact(messages: Sequence[ChatMessage]) -> str:
        lines = []
        for m in messages:
            content = m.content or ""
            if m.tool_calls:
                tc_names = [tc.name for tc in m.tool_calls]
                content += f"\n[tool_calls: {', '.join(tc_names)}]"
            if m.role == "tool":
                lines.append(f"[tool result] {content[:300]}")
            else:
                lines.append(f"[{m.role}] {content[:1500]}")
        return "\n\n".join(lines)
