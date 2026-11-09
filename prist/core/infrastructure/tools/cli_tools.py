"""CLI 工具：RunCli 执行本地命令。"""

from __future__ import annotations

import subprocess

from ...application.registry import FunctionTool
from ...domain.models import ToolSpec

DEFAULT_TIMEOUT = 30
MAX_OUTPUT = 6000


def run_cli(args: dict) -> str:
    command = args.get("command", "")
    cmd_args = args.get("args", [])
    timeout = float(args.get("timeout", DEFAULT_TIMEOUT))

    if not command:
        return "错误: RunCli 需要提供 command 参数"
    if not isinstance(cmd_args, list):
        return "错误: args 必须是数组类型"

    full_cmd = [command, *cmd_args]
    try:
        proc = subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return "错误: 未找到命令 '%s'（可能未安装或不在 PATH 中）" % command
    except subprocess.TimeoutExpired:
        return "错误: 命令执行超时（%.0f 秒）" % timeout
    except OSError as exc:
        return "错误: 无法执行命令 - %s" % exc

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    exit_code = proc.returncode

    # 截断超长输出
    if len(stdout) > MAX_OUTPUT:
        stdout = stdout[:MAX_OUTPUT] + "\n...(stdout 已截断)"
    if len(stderr) > MAX_OUTPUT:
        stderr = stderr[:MAX_OUTPUT] + "\n...(stderr 已截断)"

    lines = ["[exit_code: %d]" % exit_code]
    if stdout:
        lines.append("--- stdout ---")
        lines.append(stdout)
    if stderr:
        lines.append("--- stderr ---")
        lines.append(stderr)
    return "\n".join(lines)


def _tool(name: str, description: str, parameters: dict, handler) -> FunctionTool:
    return FunctionTool(
        spec=ToolSpec(name=name, description=description, parameters=parameters),
        handler=handler,
    )


def build_cli_tools() -> list[FunctionTool]:
    return [
        _tool(
            name="RunCli",
            description=(
                "执行本地命令行程序（pip install / python xxx.py / git / curl / ffmpeg 等）。"
                "接收 command（程序名）、args（参数数组）和可选的 timeout（秒，默认30）。"
                "返回 exit_code、stdout 和 stderr。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的程序名，例如 pip"},
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参数数组，例如 ['install', 'flask']",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "超时秒数（默认 30）",
                    },
                },
                "required": ["command"],
            },
            handler=run_cli,
        ),
    ]
