"""Office 文档生成工具：createPPTX + createDOCX。

使用 python-pptx / python-docx 正确生成二进制 Office 文件，
避免 LLM 用 createFile 把纯文本写进 .pptx/.docx 后缀文件导致损坏。
"""

from __future__ import annotations

import os
import traceback

from ...application.registry import FunctionTool
from ...domain.models import ToolSpec


def _office_tool(name: str, description: str, parameters: dict, handler) -> FunctionTool:
    return FunctionTool(
        spec=ToolSpec(name=name, description=description, parameters=parameters),
        handler=handler,
    )


# ==========================================================================
# createPPTX
# ==========================================================================

def create_pptx(args) -> str:
    """生成 .pptx PowerPoint 文件。

    args:
        filename: str          — 文件名（自动补 .pptx）
        title: str             — PPT 封面标题（可选）
        slides: list[slide]    — 幻灯片列表
            slide 可以是:
              "纯标题字符串"
              {"title": "...", "bullets": ["要点1", "要点2", ...]}
              {"title": "...", "content": "长段落文本"}
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except ImportError:
        return "错误: python-pptx 未安装，请先 pip install python-pptx"

    filename = args.get("filename", "presentation")
    if not filename.lower().endswith(".pptx"):
        filename += ".pptx"

    directory = args.get("directory", ".")
    os.makedirs(directory, exist_ok=True)
    full_path = os.path.join(directory, filename)

    prs = Presentation()

    # 封面（如果有 title）
    cover_title = args.get("title")
    if cover_title:
        slide = prs.slides.add_slide(prs.slide_layouts[0])
        slide.shapes.title.text = cover_title
        if slide.placeholders[1]:
            slide.placeholders[1].text = "由 prist AI 智能体生成"

    # 幻灯片列表
    slides_arg = args.get("slides", [])
    if not slides_arg and not cover_title:
        # 至少加一页
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = "空白幻灯片"
        slide.placeholders[1].text = ""

    for slide_data in slides_arg:
        prs_slide = prs.slides.add_slide(prs.slide_layouts[1])  # 标题 + 内容布局

        if isinstance(slide_data, str):
            # 纯标题
            prs_slide.shapes.title.text = slide_data
            prs_slide.placeholders[1].text = ""
        elif isinstance(slide_data, dict):
            title = slide_data.get("title", "")
            prs_slide.shapes.title.text = title

            if "bullets" in slide_data and slide_data["bullets"]:
                tf = prs_slide.placeholders[1].text_frame
                tf.text = slide_data["bullets"][0]
                for bullet in slide_data["bullets"][1:]:
                    p = tf.add_paragraph()
                    p.text = bullet
                    p.level = 0
            elif "content" in slide_data and slide_data["content"]:
                prs_slide.placeholders[1].text = slide_data["content"]

    prs.save(full_path)
    size = os.path.getsize(full_path)

    # 验证是合法 ZIP (PPTX 本质是 ZIP)
    with open(full_path, "rb") as f:
        sig = f.read(4)
    if sig[:2] != b"PK":
        os.remove(full_path)
        return f"错误: 生成的 PPTX 文件不合法（签名: {sig}），已删除"

    return f"✅ 已创建 PowerPoint 文件: {full_path} ({size} bytes)"


# ==========================================================================
# createDOCX
# ==========================================================================

def create_docx(args) -> str:
    """生成 .docx Word 文件。

    args:
        filename: str               — 文件名（自动补 .docx）
        title: str                  — 文档标题
        sections: list[section]     — 段落列表
            section 可以是:
              "纯文本段落"
              {"heading": "小标题", "content": "段落内容"}
              {"heading": "小标题", "bullets": ["列表项1", "列表项2"]}
    """
    try:
        from docx import Document
    except ImportError:
        return "错误: python-docx 未安装，请先 pip install python-docx"

    filename = args.get("filename", "document")
    if not filename.lower().endswith(".docx"):
        filename += ".docx"

    directory = args.get("directory", ".")
    os.makedirs(directory, exist_ok=True)
    full_path = os.path.join(directory, filename)

    doc = Document()

    # 文档标题
    doc_title = args.get("title")
    if doc_title:
        doc.add_heading(doc_title, level=0)

    # 段落列表
    sections = args.get("sections", [])
    if not sections and not doc_title:
        doc.add_paragraph("（空文档）")

    for section in sections:
        if isinstance(section, str):
            doc.add_paragraph(section)
        elif isinstance(section, dict):
            heading = section.get("heading")
            content = section.get("content")
            bullets = section.get("bullets", [])

            if heading:
                doc.add_heading(heading, level=1)
            if content:
                doc.add_paragraph(content)
            for bullet in bullets:
                doc.add_paragraph(bullet, style="List Bullet")

    doc.save(full_path)
    size = os.path.getsize(full_path)

    # 验证是合法 ZIP (DOCX 本质是 ZIP)
    with open(full_path, "rb") as f:
        sig = f.read(4)
    if sig[:2] != b"PK":
        os.remove(full_path)
        return f"错误: 生成的 DOCX 文件不合法（签名: {sig}），已删除"

    return f"✅ 已创建 Word 文件: {full_path} ({size} bytes)"


# ==========================================================================
# 导出
# ==========================================================================

def build_office_tools() -> list[FunctionTool]:
    return [
        _office_tool(
            name="createPPTX",
            description=(
                "【专用工具】用 python-pptx 生成合法的 .pptx PowerPoint 文件。"
                "不要用 createFile 创建 .pptx 文件——那只会写入纯文本，文件会损坏！"
                "参数 slides 是数组，每个元素可以是字符串（纯标题）或对象 {title, bullets, content}。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "保存目录，例如 ."},
                    "filename": {"type": "string", "description": "文件名，例如 春天介绍"},
                    "title": {"type": "string", "description": "PPT 封面标题"},
                    "slides": {
                        "type": "array",
                        "description": "幻灯片列表",
                        "items": {
                            "oneOf": [
                                {"type": "string", "description": "纯标题字符串"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "bullets": {"type": "array", "items": {"type": "string"}},
                                        "content": {"type": "string"},
                                    },
                                },
                            ]
                        },
                    },
                },
                "required": ["filename", "slides"],
            },
            handler=create_pptx,
        ),
        _office_tool(
            name="createDOCX",
            description=(
                "【专用工具】用 python-docx 生成合法的 .docx Word 文件。"
                "不要用 createFile 创建 .docx 文件——那只会写入纯文本，文件会损坏！"
                "参数 sections 是数组，每个元素可以是字符串（纯段落）或对象 {heading, content, bullets}。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "保存目录，例如 ."},
                    "filename": {"type": "string", "description": "文件名，例如 通知"},
                    "title": {"type": "string", "description": "文档大标题"},
                    "sections": {
                        "type": "array",
                        "description": "段落列表",
                        "items": {
                            "oneOf": [
                                {"type": "string", "description": "纯文本段落"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "heading": {"type": "string"},
                                        "content": {"type": "string"},
                                        "bullets": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                            ]
                        },
                    },
                },
                "required": ["filename", "sections"],
            },
            handler=create_docx,
        ),
    ]


__all__ = ["build_office_tools"]
