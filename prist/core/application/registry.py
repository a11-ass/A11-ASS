"""工具注册表：按名称分发工具调用，并隔离工具异常。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..domain.models import ToolResult, ToolSpec
from ..domain.ports import ToolHandler


@dataclass(frozen=True)
class FunctionTool:
    """一个工具 = 元数据 + 处理函数。"""

    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    """工具集合。未知工具或执行异常都会转为错误文本返回给模型。"""

    def __init__(self, tools: Iterable[FunctionTool] = ()) -> None:
        self._tools: dict[str, FunctionTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: FunctionTool) -> None:
        name = tool.spec.name
        if name in self._tools:
            raise ValueError("工具已注册: %s" % name)
        self._tools[name] = tool

    @property
    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, output="错误: 未知工具 - %s" % name)
        try:
            output = tool.handler(dict(arguments))
        except Exception as exc:  # 工具位于系统边界，异常需转为模型可读的文本
            return ToolResult(ok=False, output="错误: 工具 %s 执行失败 - %s" % (name, exc))
        return ToolResult(ok=True, output=str(output))
