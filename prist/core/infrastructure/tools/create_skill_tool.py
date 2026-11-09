"""createSkill 工具：让 Agent 能够根据用户要求创建新 Skill。

职责：
1. 规范化 Skill 名称（只允许小写字母、数字、连字符）；
2. 在 .agents/skills/<name>/ 下创建目录与 SKILL.md；
3. 校验 SKILL.md 内容必须包含合法的 YAML frontmatter（name + description）；
4. 目标已存在时拒绝覆盖，返回明确提示。

设计原则：
- 只创建 SKILL.md，其他目录（references/、scripts/）或文件由 LLM 继续用 file ops 工具创建；
- 幂等安全：绝不覆盖已有 Skill。
"""

from __future__ import annotations

import re
from pathlib import Path

from ...application.registry import FunctionTool
from ...domain.models import ToolSpec


_NAME = "createSkill"
_DESCRIPTION = (
    "根据用户要求创建一个新的 Skill。"
    "当用户要求「创建一个 Skill / 新增技能 / 给 Agent 加一个能力」时必须调用。"
    "在 .agents/skills/<name>/ 目录下生成 SKILL.md 文件。"
    "Skill 创建后会被自动识别，下次对话即可通过 loadSkill 使用。"
)
_PARAMETERS = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "Skill 英文名称。只允许小写字母、数字和连字符（如 mini-encryption、office-cli）。"
                "不要写中文或大写。"
            ),
        },
        "skillContext": {
            "type": "string",
            "description": (
                "要写入 SKILL.md 的完整内容。"
                "必须以 YAML frontmatter 开头，至少包含 name 和 description 字段，"
                "然后是正文（告诉 Agent 如何使用这个 Skill 的详细说明）。"
                "frontmatter 格式：\n"
                "---\n"
                "name: <skill-name>\n"
                "description: <一句话描述这个 Skill 能做什么>\n"
                "---\n"
                "\n"
                "正文...\n"
            ),
        },
    },
    "required": ["name", "skillContext"],
}


# 合法 Skill 名称：小写字母、数字、连字符，开头结尾都是字母/数字
_VALID_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _normalize_name(raw: str) -> str | None:
    """把用户给的 name 规范化为合法格式。

    策略：
    1. 小写化；
    2. 把非字母数字替换为连字符；
    3. 清理前后和连续的连字符；
    4. 检查是否符合模式。
    返回 None 表示无法规范化。
    """
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    s = re.sub(r"-+", "-", s)
    if not s or not _VALID_NAME_RE.match(s):
        return None
    return s


def _strip_wrapping_codeblock(text: str) -> str:
    """LLM 经常把 markdown 内容包在 ```yaml ... ``` 里，剥掉它。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        # 去掉开头的 ```yaml / ```markdown / ``` 等
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1:]
        # 去掉结尾的 ```
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
    return stripped


def _ensure_frontmatter_wrapped(content: str) -> tuple[str, str]:
    """确保 content 被合法的 YAML frontmatter 包裹。

    三种情况：
    1. 已经有 --- 包裹 → 原样返回；
    2. 有 name:/description: 但没 --- → 自动补上；
    3. 都没有 → 返回 ("", "错误信息")。

    返回 (wrapped_content, "") 或 ("", error_msg)。
    """
    content = content.strip()

    # 情况 1：已经有合法 frontmatter
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            return content, ""

    # 情况 2：没有 --- 但有 YAML key:value → 自动补
    first_line = content.splitlines()[0] if content else ""
    if first_line.startswith("name:") or first_line.startswith("description:"):
        # 找到 YAML 段结束位置（遇到第一个空行后第一个非空行不以空格开头，即正文开始）
        lines = content.splitlines()
        yaml_lines: list[str] = []
        body_start = len(lines)  # 默认没有正文
        for i, line in enumerate(lines):
            if not line.strip():
                # 空行：如果后面还有非空行且不以空格开头，说明 YAML 段结束
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and not lines[j].startswith(" ") and not lines[j].startswith("\t"):
                    # 非空且非缩进 → 正文开始
                    body_start = j
                    break
                # 否则还是 YAML 内部的空行
                yaml_lines.append(line)
            else:
                yaml_lines.append(line)

        yaml_block = "\n".join(yaml_lines).strip()
        body = "\n".join(lines[body_start:]).strip()
        wrapped = f"---\n{yaml_block}\n---\n\n{body}" if body else f"---\n{yaml_block}\n---"
        return wrapped, ""

    # 情况 3：都没有
    return "", (
        "skillContext 无法识别 YAML frontmatter。"
        "请以 '---' 开头写 YAML（至少包含 name 和 description），然后再写正文。"
    )


def _extract_fm_name_desc(content: str) -> tuple[bool, str]:
    """从已经有合法 --- 包裹的 frontmatter 里提取 name / description。"""
    if not content.startswith("---"):
        return False, "SKILL.md 必须以 '---' 开头的 YAML frontmatter 开始"
    end = content.find("\n---", 3)
    if end == -1:
        return False, "SKILL.md 的 YAML frontmatter 缺少结束标记 '---'"
    fm_text = content[3:end].strip()

    name_val = None
    desc_val = None
    for line in fm_text.splitlines():
        line = line.strip()
        if line.startswith("name:") and name_val is None:
            name_val = line[5:].strip().strip("'\"")
        elif line.startswith("description:") and desc_val is None:
            desc_val = line[12:].strip().strip("'\"")

    if not name_val:
        return False, "frontmatter 缺少必填字段 'name'"
    if not desc_val:
        return False, "frontmatter 缺少必填字段 'description'"
    return True, name_val


def _has_valid_frontmatter(content: str) -> tuple[bool, str]:
    """完整校验：自动补 --- 包裹 → 提取检查 → 返回。"""
    wrapped, err = _ensure_frontmatter_wrapped(content)
    if err:
        return False, err
    return _extract_fm_name_desc(wrapped)


def build_createSkill_tool(project_root: Path) -> FunctionTool:
    """构造 createSkill 工具。

    Args:
        project_root: 项目根目录（.agents/skills 的父目录）。
    """
    skills_dir = Path(project_root).resolve() / ".agents" / "skills"

    def handler(args: dict) -> str:
        raw_name = str(args.get("name", "")).strip()
        skill_context = str(args.get("skillContext", ""))

        if not raw_name:
            return "❌ 创建失败：缺少参数 name"
        if not skill_context:
            return "❌ 创建失败：缺少参数 skillContext"

        # 1. 规范化名称
        norm = _normalize_name(raw_name)
        if norm is None:
            return (
                f"❌ 创建失败：名称 '{raw_name}' 不合法。"
                "Skill 名称只能由小写字母、数字和连字符组成（如 mini-encryption）。"
            )

        # 2. 剥掉 LLM 可能包的 ```yaml 外壳 + 自动补 --- frontmatter 包裹
        skill_context = _strip_wrapping_codeblock(skill_context)
        wrapped, wrap_err = _ensure_frontmatter_wrapped(skill_context)
        if wrap_err:
            return f"❌ 创建失败：{wrap_err}"
        skill_context = wrapped  # 用补好的内容（有 --- 分隔符）

        # 3. 从 frontmatter 中提取 name / description 做校验
        fm_ok, fm_result = _extract_fm_name_desc(skill_context)
        if not fm_ok:
            return f"❌ 创建失败：{fm_result}"

        # 4. 检查目标是否已存在
        target_dir = skills_dir / norm
        target_md = target_dir / "SKILL.md"

        if target_md.exists():
            return (
                f"⚠️ Skill '{norm}' 已存在（路径: {target_dir}），拒绝覆盖。\n"
                f"如需更新，请先删除原 Skill，或换一个新名称。"
            )
        if target_dir.exists():
            # 目录存在但没 SKILL.md（半成品），也拒绝
            return (
                f"⚠️ 目录 '{target_dir}' 已存在但不是完整 Skill（缺少 SKILL.md），拒绝写入。"
            )

        # 5. 创建目录 + 写入
        try:
            target_dir.mkdir(parents=True, exist_ok=False)
            target_md.write_text(skill_context, encoding="utf-8")
        except OSError as exc:
            return f"❌ 创建失败：无法写入 {target_md} — {exc}"

        return (
            f"✅ Skill 创建成功！\n"
            f"   名称: {norm}\n"
            f"   路径: {target_dir}\n"
            f"   大小: {len(skill_context)} 字符\n\n"
            f"💡 补充说明：\n"
            f"   - 下次对话开始时会自动识别此 Skill；\n"
            f"   - 如需 references/、scripts/ 等目录，请用 file ops 工具继续创建；\n"
            f"   - 可以立即用 loadSkill(name='{norm}') 测试。"
        )

    return FunctionTool(
        spec=ToolSpec(name=_NAME, description=_DESCRIPTION, parameters=_PARAMETERS),
        handler=handler,
    )
