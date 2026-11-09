"""领域模型：核心层与 UI 层共享的纯数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """描述一个可供大模型调用的工具。"""

    name: str
    description: str
    parameters: dict[str, Any]

    def to_api(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCall:
    """模型返回的一次工具调用请求。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """工具执行结果。"""

    ok: bool
    output: str


@dataclass
class ChatMessage:
    """对话历史中的一条消息，可直接转换为 OpenAI 兼容格式。"""

    role: str
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def to_api(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role}
        # content 始终写入：带 tool_calls 的 assistant 消息中 content 必须为 null，
        # 否则智谱等 API 会忽略随后的 tool 结果消息
        data["content"] = self.content
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": _dump_arguments(call.arguments),
                    },
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            data["tool_call_id"] = self.tool_call_id
        return data


@dataclass(frozen=True)
class AssistantMessage:
    """模型一次非流式响应。"""

    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


def _dump_arguments(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(arguments, ensure_ascii=False)
