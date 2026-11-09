"""联网工具：searchWeb（百度千帆搜索）+ fetchWeb（curl + trafilatura 提取 Markdown）。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import requests

from ...application.registry import FunctionTool
from ...domain.models import ToolSpec
from ..config import SearchSettings

MAX_FETCH_MD = 16000   # Markdown 上限 16KB，给 LLM 留足上下文
MAX_SEARCH_RESULTS = 8  # 最多返回 8 条搜索结果，避免 token 爆炸


# ============================================================
# searchWeb：百度千帆智能搜索插件
# ============================================================

def search_web(args: dict, settings: SearchSettings) -> str:
    if not settings.enabled:
        return "错误: 搜索工具未启用（config.ini 的 [search] baidu_api_key 未配置）"

    query = str(args.get("query", "")).strip()
    if not query:
        return "错误: searchWeb 需要提供 query 参数"

    # 百度 AI 开放平台 wenxinworkshop 搜索插件
    # 老域名 aip.baidubce.com + plugin/websearch/ 可用（新域名 qianfan.baidubce.com 的 plugin 需要在千帆控制台单独开通）
    url = f"{settings.baidu_base_url}/rpc/2.0/ai_custom/v1/wenxinworkshop/plugin/{settings.baidu_model}/"

    # Key 格式判断：bce-v3/ 开头 → 当成完整 Authorization 头；否则 Bearer
    api_key = settings.baidu_api_key.strip()
    if api_key.lower().startswith("bce-v3/"):
        headers = {"Authorization": api_key, "Content-Type": "application/json"}
    else:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload = {"query": query}

    try:
        resp = requests.post(
            url, headers=headers, json=payload, timeout=settings.baidu_timeout
        )
        if resp.status_code >= 400:
            return (
                f"错误: 百度搜索 API 返回 HTTP {resp.status_code}\n"
                f"响应: {resp.text[:800]}\n"
                f"请检查 [search] baidu_api_key 是否为有效的千帆 API Key"
            )
        data = resp.json()
    except requests.Timeout:
        return f"错误: 百度搜索请求超时（{settings.baidu_timeout}秒），请稍后重试"
    except requests.ConnectionError as exc:
        return f"错误: 无法连接百度搜索服务 - {exc}"
    except requests.RequestException as exc:
        return f"错误: 搜索请求失败 - {exc}"
    except json.JSONDecodeError:
        return f"错误: 搜索响应不是合法 JSON - {resp.text[:500]}"

    return _format_search_results(data, query)


def _format_search_results(data: dict, query: str) -> str:
    """把百度千帆的搜索响应格式化为 LLM 友好的 Markdown 摘要。"""
    results: list[dict] = []

    # 百度千帆插件返回的结构可能有多种，兼容几种常见格式
    raw = data.get("result", [])
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                results.append(item)
            elif isinstance(item, str):
                results.append({"title": item, "content": item})
    elif isinstance(raw, dict):
        # 嵌套结构
        for key in ("results", "items", "web_results"):
            if key in raw and isinstance(raw[key], list):
                results.extend(raw[key])
    elif isinstance(raw, str):
        # 纯文本摘要
        results = [{"title": query, "content": raw}]

    if not results:
        return (
            f"(搜索未返回结果)\n"
            f"原始响应结构: {json.dumps(list(data.keys()), ensure_ascii=False)}"
        )

    lines = [f"## 搜索: {query}\n"]
    for i, item in enumerate(results[:MAX_SEARCH_RESULTS], 1):
        title = str(item.get("title", "")).strip() or f"结果 {i}"
        content = str(item.get("content", item.get("snippet", ""))).strip()
        link = str(item.get("url", item.get("link", ""))).strip()

        lines.append(f"### {i}. {title}")
        if content:
            # 截断过长摘要
            if len(content) > 400:
                content = content[:400] + "…"
            lines.append(content)
        if link:
            lines.append(f"来源: {link}")
        lines.append("")

    return "\n".join(lines).strip()


# ============================================================
# fetchWeb：subprocess curl 抓 HTML → trafilatura 提取 Markdown
# ============================================================

def fetch_web(args: dict) -> str:
    url = str(args.get("url", "")).strip()
    if not url:
        return "错误: fetchWeb 需要提供 url 参数"
    if not (url.startswith("http://") or url.startswith("https://")):
        return f"错误: URL 必须以 http:// 或 https:// 开头（收到: {url}）"

    # 第一步：curl 抓 HTML（subprocess 参数列表，不 shell=True）
    html, err = _curl_fetch(url)
    if html is None:
        return f"错误: curl 抓取失败 - {err}"

    # 第二步：trafilatura 提取 Markdown
    try:
        import trafilatura
    except ImportError:
        return (
            "错误: 缺少 trafilatura 库，请执行 `pip install trafilatura`\n"
            f"（已抓到 HTML {len(html)} 字节但无法解析）"
        )

    try:
        markdown = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_images=False,
            deduplicate=True,
            favor_precision=True,
        )
    except Exception as exc:
        return f"错误: trafilatura 解析失败 - {exc}\n（原始 HTML {len(html)} 字节）"

    if not markdown or not markdown.strip():
        return (
            f"错误: 无法从该页面提取正文（可能是纯 JS 渲染页、登录页或反爬页面）\n"
            f"URL: {url}\nHTML 大小: {len(html)} 字节"
        )

    # 截断超长内容
    if len(markdown) > MAX_FETCH_MD:
        markdown = markdown[:MAX_FETCH_MD] + "\n\n…(正文已截断)"

    return f"## {url}\n\n{markdown.strip()}"


def _curl_fetch(url: str, timeout: int = 20) -> tuple[str | None, str]:
    """用 curl 命令抓取 URL HTML，返回 (html_text, error_message)。

    参数：
    - url: 目标 URL
    - timeout: 秒

    使用参数列表形式（subprocess.run 的 args 是 list），绝不 shell=True，避免命令注入。
    """
    cmd = [
        "curl",
        "-sS",            # 静默模式 + 出错显示
        "-L",             # 跟随重定向
        "--max-time", str(timeout),
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "-H", "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "-o", "-",         # stdout 输出
        "-w", "\n__HTTP_CODE__:%{http_code}",  # 最后一行输出 HTTP 状态码
        url,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,  # 给 curl 多留 5 秒兜底
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return None, "curl 命令未找到，请确保 curl 在系统 PATH 中"
    except subprocess.TimeoutExpired:
        return None, f"curl 执行超时（{timeout + 5}秒）"
    except OSError as exc:
        return None, f"无法执行 curl - {exc}"

    # 拆分响应体和状态码
    stdout = proc.stdout or ""
    marker = "__HTTP_CODE__:"
    if marker in stdout:
        html, code_line = stdout.rsplit(marker, 1)
        try:
            http_code = int(code_line.strip())
        except ValueError:
            http_code = 0
    else:
        html, http_code = stdout, proc.returncode

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return None, f"curl 退出码 {proc.returncode}: {stderr[:300]}"

    if http_code >= 400:
        return None, f"HTTP {http_code}（页面不可访问）"

    html = html.strip()
    if not html:
        return None, "curl 返回了空内容"

    return html, ""


# ============================================================
# 工具注册表构建
# ============================================================

def _tool(name: str, description: str, parameters: dict, handler) -> FunctionTool:
    return FunctionTool(
        spec=ToolSpec(name=name, description=description, parameters=parameters),
        handler=handler,
    )


def build_web_tools(settings: SearchSettings) -> list[FunctionTool]:
    tools: list[FunctionTool] = []

    if settings.enabled:
        def _search(args, s=settings):
            return search_web(args, s)
        tools.append(
            _tool(
                name="searchWeb",
                description=(
                    "通过百度千帆搜索互联网最新信息（新闻/天气/赛事/股价/实体信息/技术参数等）。"
                    "返回带标题、摘要和来源 URL 的结构化结果。"
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词或完整问题，例如 '2026年诺贝尔物理学奖得主'",
                        }
                    },
                    "required": ["query"],
                },
                handler=_search,
            )
        )

    # fetchWeb 始终注册（不依赖搜索 Key）
    tools.append(
        _tool(
            name="fetchWeb",
            description=(
                "抓取指定网页的正文内容并转换为 Markdown。"
                "使用 curl 获取 HTML，用 trafilatura 提取正文（保留标题/段落/列表/表格/链接，去除导航/广告/页脚）。"
                "在 searchWeb 返回的链接上调用此工具可以看到完整原文。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "网页的完整 URL（必须以 http:// 或 https:// 开头）",
                    }
                },
                "required": ["url"],
            },
            handler=fetch_web,
        )
    )
    return tools
