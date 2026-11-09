"""Skill 动态加载工具：loadSkill。

与其他工具不同，loadSkill 的 handler 依赖一个已经扫描好的 SkillIndex。
因此这里提供一个 build_loadSkill_tool 工厂，由上层在组装时注入索引。
"""

from __future__ import annotations

from ...application.registry import FunctionTool
from ...domain.models import ToolSpec
from ...domain.skill_loader import (
    SkillIndex,
    SkillPathError,
    read_skill_file,
    safe_resolve,
    search_by_filename,
)


_NAME = "loadSkill"
_DESCRIPTION = (
    "【必须调用】当用户请求匹配 System Prompt 中列出的任意 Skill 时，"
    "必须第一时间调用本工具读取该 Skill 的完整指令（SKILL.md），"
    "拿到指令后再按 Skill 中的规则继续执行。"
    "禁止跳过本工具直接处理 Skill 覆盖场景。"
)
_PARAMETERS = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": "要加载的 Skill 名称（与 System Prompt 中的技能列表一致）。必须传。",
        },
        "filename": {
            "type": "string",
            "description": (
                "可选。读取 Skill 附带的其他文件（非 SKILL.md）。"
                "可以是 Skill 目录内的相对路径、纯文件名（会递归搜索）。"
                "不传则默认读取该 Skill 的 SKILL.md 全文。"
            ),
        },
    },
    "required": ["name"],
}


def build_loadSkill_tool(skills: SkillIndex) -> FunctionTool:
    """构造 loadSkill FunctionTool。skills 可以是空索引（SkillIndex.empty=True）。"""

    def handler(args: dict) -> str:
        return _handle_load_skill(args, skills)

    return FunctionTool(
        spec=ToolSpec(name=_NAME, description=_DESCRIPTION, parameters=_PARAMETERS),
        handler=handler,
    )


def _handle_load_skill(args: dict, skills: SkillIndex) -> str:
    name = str(args.get("name", "")).strip()
    filename = args.get("filename")

    if not name:
        return "错误: loadSkill 需要提供 name 参数"

    meta = skills.get(name)
    if meta is None:
        available = ", ".join(skills.names) if not skills.empty else "(当前没有可用 Skill)"
        return "错误: 未找到名为 '%s' 的 Skill。当前可用: %s" % (name, available)

    skill_dir = meta.skill_dir

    # 只传 name：加载 SKILL.md 全文
    if not filename:
        try:
            body = read_skill_file(meta.skill_md)
        except SkillPathError as exc:
            return "错误: 无法读取 SKILL.md - %s" % exc
        return (
            "# Skill: %s\n\n"
            "> 描述: %s\n\n"
            "---\n\n"
            "%s"
        ) % (meta.name, meta.description, body)

    # 传了 filename：尝试精确解析 → 失败则做文件名模糊搜索
    filename_str = str(filename).strip()
    exact = safe_resolve(skill_dir, filename_str)
    if exact is not None and exact.is_file():
        # 精确路径匹配成功（且确实是文件）
        try:
            return read_skill_file(exact)
        except SkillPathError as exc:
            return "错误: %s" % exc
    # exact is None / 路径不存在 / 是目录 → 继续下面的模糊搜索分支

    # 精确解析失败：当 filename 是纯文件名（无路径分隔符）时，做递归搜索
    if "/" not in filename_str and "\\" not in filename_str:
        matches = search_by_filename(skill_dir, filename_str)
        if len(matches) == 1:
            try:
                return read_skill_file(matches[0])
            except SkillPathError as exc:
                return "错误: %s" % exc
        if len(matches) > 1:
            lines = ["在 Skill '%s' 下找到多个名为 '%s' 的文件，请在下次 loadSkill 时传入更精确的路径：" % (name, filename_str)]
            for m in matches:
                lines.append("  - %s" % m)
            return "\n".join(lines)
        # 搜索也没找到
        return "错误: 在 Skill '%s' 中未找到 '%s'（已尝试精确路径与文件名搜索）" % (name, filename_str)

    # 非纯文件名、精确路径也不成立
    return (
        "错误: 路径 '%s' 不在 Skill '%s' 的目录内或无法解析。"
        "所有文件必须位于 %s 之下。"
    ) % (filename_str, name, skill_dir)
