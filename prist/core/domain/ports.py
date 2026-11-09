"""端口协议：应用层依赖抽象，基础设施层提供实现。"""

from __future__ import annotations

from typing import Any, Iterator, Protocol, Sequence

from .models import AssistantMessage, ChatMessage, ToolSpec


class LLMClient(Protocol):
    """大模型客户端端口。"""

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence[ToolSpec]
    ) -> AssistantMessage:
        """非流式调用，用于判断是否需要执行工具。"""
        ...

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """流式调用，逐段产出回答文本。"""
        ...


class ToolHandler(Protocol):
    """工具处理函数端口。"""

    def __call__(self, arguments: dict[str, Any]) -> str:
        ...
