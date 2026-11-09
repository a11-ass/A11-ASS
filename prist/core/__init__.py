"""核心层公共 API。

界面层只依赖本文件导出的内容，不直接引用核心层内部模块，
以此保证核心逻辑与 UI 的隔离。
"""

from .application.agent_service import AgentService
from .application.registry import FunctionTool, ToolRegistry
from .domain.events import (
    AgentEvent,
    TextDelta,
    ToolFinished,
    ToolStarted,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
)
from .domain.models import AssistantMessage, ChatMessage, ToolCall, ToolResult, ToolSpec
from .domain.prompts import SYSTEM_PROMPT

__all__ = [
    "AgentEvent",
    "AgentService",
    "AssistantMessage",
    "ChatMessage",
    "FunctionTool",
    "SYSTEM_PROMPT",
    "TextDelta",
    "ToolCall",
    "ToolFinished",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "ToolStarted",
    "TurnCompleted",
    "TurnFailed",
    "TurnStarted",
]
