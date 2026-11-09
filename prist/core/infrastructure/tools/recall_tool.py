"""recallContext 工具：全文检索历史归档。"""

from __future__ import annotations

from pathlib import Path

from ...application.registry import FunctionTool
from ...application.context_manager import ContextArchive
from ...domain.models import ToolSpec


def build_recallContext_tool(archive_dir: Path) -> FunctionTool:
    """构建 recallContext FunctionTool。"""
    archive = ContextArchive(archive_dir)

    schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "需要查找的关键词或文本内容（必需）",
            },
            "id": {
                "type": "string",
                "description": "可选，指定检索的归档编号（如 20261022-153000）。不填则检索所有归档",
            },
        },
        "required": ["text"],
    }

    def handler(args: dict) -> str:
        text = (args.get("text") or "").strip()
        aid = (args.get("id") or "").strip() or None
        return archive.recall(query=text, archive_id=aid, max_hits=10)

    return FunctionTool(
        spec=ToolSpec(
            name="recallContext",
            description=(
                "【历史上下文检索】在压缩归档中全文检索关键词。"
                "当上下文摘要缺少某些细节、需要查阅之前对话的完整内容时调用此工具。"
                "归档目录: .agents/context/"
            ),
            parameters=schema,
        ),
        handler=handler,
    )


__all__ = ["build_recallContext_tool"]
