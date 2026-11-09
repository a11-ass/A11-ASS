"""Skill 发现与元数据加载。

职责：
1. 在项目根目录下查找 .agents/skills/ 目录；
2. 扫描其中每个 Skill 子目录，读取 SKILL.md 的 YAML front-matter（name + description）；
3. 构建 SkillIndex：name -> SkillMeta 的轻量索引，供 System Prompt 注入和 loadSkill 工具使用。

本模块只加载元数据，不读取 Skill 的正文内容——正文延迟到 LLM 调用 loadSkill 时才读入上下文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml  # PyYAML 已随 Agent 依赖安装
except ImportError:  # pragma: no cover — 优雅降级，避免整项目崩
    yaml = None  # type: ignore[assignment]

# Skill 存放约定目录：与 Windows 风格 .agents\skills\ 等价，pathlib 统一处理
SKILLS_SUBDIR = ".agents/skills"


@dataclass(frozen=True)
class SkillMeta:
    """一个 Skill 的元数据。"""

    name: str
    description: str
    skill_dir: Path       # 该 Skill 所在目录（绝对路径）
    skill_md: Path        # SKILL.md 的绝对路径


@dataclass
class SkillIndex:
    """所有已发现 Skill 的索引。"""

    skills_dir: Path | None = None                         # 扫描到的 skills 目录（可能为 None）
    skills: dict[str, SkillMeta] = field(default_factory=dict)  # name -> SkillMeta

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self.skills)

    def get(self, name: str) -> SkillMeta | None:
        return self.skills.get(name)

    @property
    def empty(self) -> bool:
        return not self.skills


def discover_skills(project_root: Path | str | None = None) -> SkillIndex:
    """扫描项目根目录下的 .agents/skills，返回 SkillIndex。

    扫描失败（目录不存在 / 所有 SKILL.md 都读不了）时返回空索引，
    不抛异常——让 Agent 像没有 Skill 一样照常运行。
    """
    if project_root is None:
        project_root = Path.cwd()
    root = Path(project_root).resolve()
    skills_dir = root / SKILLS_SUBDIR
    idx = SkillIndex(skills_dir=skills_dir if skills_dir.is_dir() else None)

    if not skills_dir.is_dir():
        return idx

    for subdir in sorted(skills_dir.iterdir()):
        if not subdir.is_dir():
            continue
        skill_md = subdir / "SKILL.md"
        if not skill_md.is_file():
            continue
        meta = _load_meta(skill_md, subdir)
        if meta is None:
            continue
        # name 冲突：后发现的跳过，保留先发现的
        if meta.name in idx.skills:
            continue
        idx.skills[meta.name] = meta

    return idx


def _load_meta(skill_md: Path, skill_dir: Path) -> SkillMeta | None:
    """读取 SKILL.md 开头的 YAML front-matter，仅提取 name / description。"""
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None

    # front-matter 以 --- 开头并以 --- 结束
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm_text = text[3:end].strip()

    data: dict = {}
    if yaml is not None:
        try:
            parsed = yaml.safe_load(fm_text)
            if isinstance(parsed, dict):
                data = parsed
        except yaml.YAMLError:
            data = {}

    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()

    if not name or not description:
        return None

    return SkillMeta(
        name=name,
        description=description,
        skill_dir=skill_dir.resolve(),
        skill_md=skill_md.resolve(),
    )


# ---------- 路径安全工具（给 loadSkill 用） ----------

class SkillPathError(ValueError):
    """Skill 目录外部 / 无法解析的路径。"""


def safe_resolve(skill_dir: Path, raw_path: str) -> Path | None:
    """把 LLM 传入的路径解析到 skill_dir 内部。

    支持：skill-dir 相对路径、项目根相对路径、绝对路径。
    返回 None 表示无法解析或不在 skill_dir 下（安全拒绝）。
    """
    skill_dir = skill_dir.resolve()

    candidates: list[Path] = []
    # 1) 绝对路径
    p = Path(raw_path)
    if p.is_absolute():
        candidates.append(p)
    else:
        # 2) 相对于 skill_dir
        candidates.append(skill_dir / raw_path)
        # 3) 相对于项目根（cwd）
        candidates.append(Path.cwd() / raw_path)

    for cand in candidates:
        try:
            resolved = cand.resolve(strict=False)
        except OSError:
            continue
        # 安全：必须在 skill_dir 内
        try:
            resolved.relative_to(skill_dir)
        except ValueError:
            continue
        return resolved
    return None


def search_by_filename(skill_dir: Path, filename: str) -> list[Path]:
    """在 skill_dir 下递归搜索所有文件名为 filename 的文件，返回绝对路径列表。"""
    skill_dir = skill_dir.resolve()
    matches: list[Path] = []
    try:
        for p in skill_dir.rglob(filename):
            if p.is_file():
                matches.append(p.resolve())
    except OSError:
        return []
    return matches


def read_skill_file(path: Path) -> str:
    """读取指定文件（skill_dir 内部）的纯文本内容，最大 64KB。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillPathError("无法读取文件 %s: %s" % (path, exc)) from exc
    except UnicodeDecodeError:
        raise SkillPathError("文件 %s 不是 UTF-8 编码或为二进制" % path)
    limit = 64 * 1024
    if len(text) > limit:
        text = text[:limit] + "\n...(已截断 %d 字节)" % (len(text) - limit)
    return text
