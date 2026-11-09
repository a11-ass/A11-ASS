"""领域事件：AgentService 对外产出的事件流类型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentEvent:
    """所有事件的基类。"""


@dataclass(frozen=True)
class TurnStarted(AgentEvent):
    user_text: str


@dataclass(frozen=True)
class TurnCompleted(AgentEvent):
    text: str
    overrides_delta: bool = False


@dataclass(frozen=True)
class TurnFailed(AgentEvent):
    message: str


@dataclass(frozen=True)
class ToolStarted(AgentEvent):
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolFinished(AgentEvent):
    name: str
    ok: bool
    output: str


@dataclass(frozen=True)
class TextDelta(AgentEvent):
    text: str


@dataclass(frozen=True)
class CompactStarted(AgentEvent):
    """用户触发了 /compact，压缩开始。"""


@dataclass(frozen=True)
class CompactCompleted(AgentEvent):
    """压缩完成。"""
    archive_id: str
    summary_tokens: int
