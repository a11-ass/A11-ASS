"""本地文件工具：目录浏览、读写、创建、删除与重命名。

安全边界：所有路径必须落在「项目根目录 / 当前工作目录 / config.ini
[app] file_allowed_roots 额外允许的根目录」之内，越界一律拒绝。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ...application.registry import FunctionTool
from ...domain.models import ToolSpec
from ..config import PROJECT_ROOT

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".pdf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
    ".exe", ".dll", ".pyc", ".db", ".sqlite", ".mp3", ".mp4",
}

MAX_READ_CHARS = 8000

_EXTRA_ROOTS: list[Path] = []


def set_extra_roots(csv: str) -> None:
    """从 config.ini [app] file_allowed_roots 追加允许的根目录（逗号分隔）。"""
    _EXTRA_ROOTS.clear()
    for part in csv.split(","):
        part = part.strip()
        if part:
            _EXTRA_ROOTS.append(Path(part).expanduser().resolve())


def _allowed_roots() -> list[Path]:
    return [PROJECT_ROOT.resolve(), Path.cwd().resolve(), *_EXTRA_ROOTS]


def _safe(path: str) -> str | None:
    """解析为绝对路径并校验在允许根目录内；越界返回 None。"""
    try:
        full = Path(path).expanduser()
        if not full.is_absolute():
            full = Path.cwd() / full
        full = full.resolve()
    except OSError:
        return None
    for root in _allowed_roots():
        if full == root or root in full.parents:
            return str(full)
    return None


def _reject(path: str) -> str:
    return (
        "错误: 路径越界，仅允许在项目根目录、当前工作目录"
        "或 config.ini [app] file_allowed_roots 指定的目录内操作 - %s" % path
    )


def get_cwd(args=None) -> str:
    return os.getcwd()


def list_dir(args) -> str:
    raw = args.get("path", ".")
    path = _safe(raw)
    if path is None:
        return _reject(raw)
    if not os.path.isdir(path):
        return "错误: 目录不存在 - %s" % path
    items = sorted(os.listdir(path))
    lines = []
    for name in items:
        full = os.path.join(path, name)
        kind = "目录" if os.path.isdir(full) else "文件"
        lines.append("[%s] %s" % (kind, name))
    return "\n".join(lines) if lines else "(空目录)"


def get_file_type(args) -> str:
    raw = args["path"]
    path = _safe(raw)
    if path is None:
        return _reject(raw)
    if not os.path.exists(path):
        return "错误: 文件不存在 - %s" % path
    ext = os.path.splitext(path)[1].lower()
    kind = "目录" if os.path.isdir(path) else "文件"
    size = os.path.getsize(path)
    return "类型: %s, 扩展名: %s, 大小: %d 字节" % (kind, ext or "(无)", size)


def read_file(args) -> str:
    raw = args["path"]
    path = _safe(raw)
    if path is None:
        return _reject(raw)
    if not os.path.isfile(path):
        return "错误: 文件不存在 - %s" % path
    if os.path.splitext(path)[1].lower() in BINARY_EXTENSIONS:
        return "错误: 该文件为二进制格式，不支持直接读取"
    try:
        with open(path, "r", encoding="utf-8") as file:
            content = file.read()
    except UnicodeDecodeError:
        return "错误: 文件非 UTF-8 编码或为二进制"
    if len(content) > MAX_READ_CHARS:
        content = content[:MAX_READ_CHARS] + "\n...(已截断)"
    return content


def create_file(args) -> str:
    directory = args.get("directory", ".")
    filename = args["filename"]
    content = args.get("content", "")
    base = _safe(directory)
    if base is None:
        return _reject(directory)
    full = _safe(os.path.join(base, filename))
    if full is None:
        return _reject(os.path.join(directory, filename))
    if not os.path.isdir(base):
        os.makedirs(base, exist_ok=True)
    with open(full, "w", encoding="utf-8") as file:
        file.write(content)
    return "已创建文件: %s (%d 字节)" % (full, len(content))


def edit_file(args) -> str:
    raw = args["path"]
    new_content = args.get("new_content", "")
    path = _safe(raw)
    if path is None:
        return _reject(raw)
    if not os.path.isfile(path):
        return "错误: 文件不存在 - %s" % path
    with open(path, "w", encoding="utf-8") as file:
        file.write(new_content)
    return "已更新文件: %s (%d 字节)" % (path, len(new_content))


def mkdir(args) -> str:
    raw = args["path"]
    path = _safe(raw)
    if path is None:
        return _reject(raw)
    if os.path.exists(path):
        return "目录已存在: %s" % path
    os.makedirs(path, exist_ok=True)
    return "已创建目录: %s" % path


def rmdir(args) -> str:
    raw = args["path"]
    path = _safe(raw)
    if path is None:
        return _reject(raw)
    if not os.path.isdir(path):
        return "错误: 目录不存在 - %s" % path
    shutil.rmtree(path)
    return "已删除目录(含内容): %s" % path


def delete_file(args) -> str:
    raw = args["path"]
    path = _safe(raw)
    if path is None:
        return _reject(raw)
    if not os.path.isfile(path):
        return "错误: 文件不存在 - %s" % path
    os.remove(path)
    return "已删除文件: %s" % path


def rename(args) -> str:
    old_raw, new_raw = args["old_path"], args["new_path"]
    old_path = _safe(old_raw)
    if old_path is None:
        return _reject(old_raw)
    new_path = _safe(new_raw)
    if new_path is None:
        return _reject(new_raw)
    if not os.path.exists(old_path):
        return "错误: 源不存在 - %s" % old_path
    if os.path.exists(new_path):
        return "错误: 目标已存在 - %s" % new_path
    os.rename(old_path, new_path)
    return "已重命名: %s -> %s" % (old_path, new_path)


def _tool(name: str, description: str, parameters: dict, handler) -> FunctionTool:
    return FunctionTool(
        spec=ToolSpec(name=name, description=description, parameters=parameters),
        handler=handler,
    )


FILE_TOOLS = [
    _tool(
        name="getCwd",
        description="获取当前工作目录（脚本运行所在的目录）",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_cwd,
    ),
    _tool(
        name="listDir",
        description="列出指定目录下所有文件和子目录",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径，例如 . 或 D:/test",
                }
            },
            "required": [],
        },
        handler=list_dir,
    ),
    _tool(
        name="getFileType",
        description="获取指定文件的类型、扩展名和大小",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件路径"}},
            "required": ["path"],
        },
        handler=get_file_type,
    ),
    _tool(
        name="readFile",
        description=(
            "读取指定的纯文本文件内容（.py / .txt / .md / .json / .ini / .html / .mmd 等），"
            "二进制文件会拒绝读取"
        ),
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件路径"}},
            "required": ["path"],
        },
        handler=read_file,
    ),
    _tool(
        name="createFile",
        description="在指定目录下创建新的纯文本文件",
        parameters={
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "目录路径，例如 ."},
                "filename": {
                    "type": "string",
                    "description": "文件名，例如 result.mmd",
                },
                "content": {"type": "string", "description": "文件初始内容（可空）"},
            },
            "required": ["directory", "filename"],
        },
        handler=create_file,
    ),
    _tool(
        name="editFile",
        description="覆盖式写入指定文件的完整新内容（仅支持纯文本）",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "new_content": {"type": "string", "description": "新的完整内容"},
            },
            "required": ["path", "new_content"],
        },
        handler=edit_file,
    ),
    _tool(
        name="mkdir",
        description="创建新目录（支持多级嵌套）",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录路径"}},
            "required": ["path"],
        },
        handler=mkdir,
    ),
    _tool(
        name="rmdir",
        description="删除目录（即使目录非空也会一并删除）",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要删除的目录路径"}
            },
            "required": ["path"],
        },
        handler=rmdir,
    ),
    _tool(
        name="deleteFile",
        description="删除指定文件",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "文件路径"}},
            "required": ["path"],
        },
        handler=delete_file,
    ),
    _tool(
        name="rename",
        description="重命名文件或目录（可跨目录，等同于移动）",
        parameters={
            "type": "object",
            "properties": {
                "old_path": {"type": "string", "description": "原路径"},
                "new_path": {"type": "string", "description": "新路径"},
            },
            "required": ["old_path", "new_path"],
        },
        handler=rename,
    ),
]
