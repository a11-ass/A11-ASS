"""配置加载：从 config.ini 读取大模型、搜索、应用等参数。

新增 [app] 段：所有之前硬编码在代码里的参数（上下文窗口、压缩阈值、TUI 刷新间隔等）
都可以从 config.ini 读取，并有合理默认值。
"""

from __future__ import annotations

import configparser
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..domain.errors import ConfigurationError

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# ---------- 新：应用层参数（之前硬编码的全在这） ----------

@dataclass(frozen=True)
class AppSettings:
    """应用层参数：从 [app] 段读取，有默认值。"""
    context_window: int = 128_000           # 模型上下文窗口（无法获取时用默认）
    compact_trigger_ratio: float = 0.80     # Token 达到窗口的 80% 时警告
    compact_keep_recent_turns: int = 2       # 压缩后保留最近 N 轮对话
    spinner_interval: float = 0.15          # Spinner 刷新间隔（秒）
    max_tool_in_sidebar: int = 5            # 侧栏最多显示几个工具名
    max_recent_in_sidebar: int = 2          # 侧栏最近调用条数
    archive_dir_name: str = ".agents/context"  # 归档目录相对项目根的路径


@dataclass(frozen=True)
class SearchSettings:
    """搜索服务配置。"""
    baidu_api_key: str = field(repr=False)
    baidu_base_url: str = "https://qianfan.baidubce.com"
    baidu_model: str = "ernie-4.5-turbo-32k"
    baidu_timeout: float = 30.0

    @property
    def enabled(self) -> bool:
        return bool(self.baidu_api_key)


@dataclass(frozen=True)
class Settings:
    """运行配置。"""
    base_url: str
    api_key: str = field(repr=False)
    model: str
    timeout: float = 120.0
    search: SearchSettings = field(default_factory=SearchSettings)
    app: AppSettings = field(default_factory=AppSettings)


# ---------- 默认 config.ini 模板 ----------

DEFAULT_CONFIG_TEMPLATE = """[llm]
# 大模型连接配置
base_url = https://open.bigmodel.cn/api/paas/v4
api_key = YOUR_API_KEY_HERE
model = glm-4-flash
timeout = 120

[search]
# 百度千帆搜索 API（留空则 searchWeb 工具不可用）
baidu_api_key =
baidu_base_url = https://qianfan.baidubce.com
baidu_model = ernie-4.5-turbo-32k
baidu_timeout = 30

[app]
# prist 应用层参数
# 模型上下文窗口大小（无法从 API 自动获取时使用此值）
context_window = 128000
# Token 达到窗口的多少比例时触发 /compact 警告
compact_trigger_ratio = 0.80
# 压缩后保留最近 N 轮完整对话
compact_keep_recent_turns = 2
# Spinner 刷新间隔（秒）
spinner_interval = 0.15
# 侧栏最多显示几个工具名
max_tool_in_sidebar = 5
# 侧栏最近调用条数
max_recent_in_sidebar = 2
# 归档目录相对项目根的路径
archive_dir_name = .agents/context
"""


def create_default_config(path: Path) -> None:
    """在指定路径创建默认 config.ini。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")


def load_settings(config_path: str | Path | None = None) -> Settings:
    """加载配置。如果 config.ini 不存在，先创建默认模板并提示用户。"""
    path = _resolve_path(config_path)

    parser = configparser.ConfigParser()
    if not parser.read(path, encoding="utf-8"):
        raise ConfigurationError("无法读取配置文件: %s" % path)
    if not parser.has_section("llm"):
        raise ConfigurationError("配置文件缺少 [llm] 段落: %s" % path)

    base_url = _required(parser, "base_url", path).rstrip("/")
    api_key = _resolve_api_key(parser, path)
    model = _required(parser, "model", path)
    timeout = _parse_timeout(parser, path)

    search = _parse_search(parser)
    app = _parse_app(parser)

    return Settings(
        base_url=base_url, api_key=api_key, model=model, timeout=timeout,
        search=search, app=app,
    )


# ---------- 解析 [app] 段 ----------

def _parse_app(parser: configparser.ConfigParser) -> AppSettings:
    """解析 [app] 段，缺失时全部用默认值。"""
    if not parser.has_section("app"):
        return AppSettings()

    section = parser["app"]

    def _int(key: str, default: int) -> int:
        raw = section.get(key, fallback=str(default)).strip()
        try:
            v = int(raw)
            return v if v > 0 else default
        except ValueError:
            return default

    def _float(key: str, default: float) -> float:
        raw = section.get(key, fallback=str(default)).strip()
        try:
            v = float(raw)
            return v if v > 0 else default
        except ValueError:
            return default

    return AppSettings(
        context_window=_int("context_window", AppSettings.context_window),
        compact_trigger_ratio=_float("compact_trigger_ratio", AppSettings.compact_trigger_ratio),
        compact_keep_recent_turns=_int("compact_keep_recent_turns", AppSettings.compact_keep_recent_turns),
        spinner_interval=_float("spinner_interval", AppSettings.spinner_interval),
        max_tool_in_sidebar=_int("max_tool_in_sidebar", AppSettings.max_tool_in_sidebar),
        max_recent_in_sidebar=_int("max_recent_in_sidebar", AppSettings.max_recent_in_sidebar),
        archive_dir_name=section.get("archive_dir_name", AppSettings.archive_dir_name).strip(),
    )


# ---------- 解析 [search] 段 ----------

def _parse_search(parser: configparser.ConfigParser) -> SearchSettings:
    env_key = os.environ.get("PRIST_SEARCH_API_KEY", "").strip()
    file_key = ""
    base_url = "https://qianfan.baidubce.com"
    model = "ernie-4.5-turbo-32k"
    timeout = 30.0

    if parser.has_section("search"):
        file_key = parser.get("search", "baidu_api_key", fallback="").strip()
        base_url = parser.get("search", "baidu_base_url", fallback=base_url).strip()
        model = parser.get("search", "baidu_model", fallback=model).strip()
        raw = parser.get("search", "baidu_timeout", fallback=str(timeout)).strip()
        try:
            timeout = float(raw)
        except ValueError:
            pass

    api_key = env_key or file_key
    return SearchSettings(
        baidu_api_key=api_key,
        baidu_base_url=base_url.rstrip("/"),
        baidu_model=model,
        baidu_timeout=timeout,
    )


# ---------- 路径解析 ----------

def _resolve_path(config_path: str | Path | None) -> Path:
    if config_path is not None:
        path = Path(config_path).expanduser()
        return path

    env_path = os.environ.get("PRIST_CONFIG")
    if env_path:
        return Path(env_path).expanduser()

    # 优先当前目录，其次项目根
    for candidate in (Path.cwd() / "config.ini", PROJECT_ROOT / "config.ini"):
        if candidate.is_file():
            return candidate

    # 都不存在 → 在 PROJECT_ROOT 创建默认模板
    default_path = PROJECT_ROOT / "config.ini"
    create_default_config(default_path)
    return default_path


def config_exists() -> bool:
    """检查 config.ini 是否存在（用于启动流程判断）。"""
    for candidate in (Path.cwd() / "config.ini", PROJECT_ROOT / "config.ini"):
        if candidate.is_file():
            return True
    return False


def config_is_mock(path: Path) -> bool:
    """判断 config.ini 是否还是默认模板（api_key 未改）。"""
    if not path.is_file():
        return True
    text = path.read_text(encoding="utf-8")
    return "YOUR_API_KEY_HERE" in text or "your_api_key" in text.lower()


# ---------- 内部 ----------

def _resolve_api_key(parser: configparser.ConfigParser, path: Path) -> str:
    env_key = os.environ.get("PRIST_API_KEY", "").strip()
    if env_key:
        return env_key
    file_key = parser.get("llm", "api_key", fallback="").strip()
    if not file_key or "YOUR_API_KEY" in file_key:
        raise ConfigurationError(
            "未配置 API Key：请在 %s 的 [llm] api_key 中填写，"
            "或设置环境变量 PRIST_API_KEY" % path
        )
    return file_key


def _required(parser: configparser.ConfigParser, key: str, path: Path) -> str:
    value = parser.get("llm", key, fallback="").strip()
    if not value:
        raise ConfigurationError("配置文件 %s 缺少 [llm] %s" % (path, key))
    return value


def _parse_timeout(parser: configparser.ConfigParser, path: Path) -> float:
    raw = parser.get("llm", "timeout", fallback="120").strip()
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ConfigurationError("配置文件 %s 的 [llm] timeout 不是数字" % path) from exc
    if timeout <= 0:
        raise ConfigurationError("配置文件 %s 的 [llm] timeout 必须大于 0" % path)
    return timeout
