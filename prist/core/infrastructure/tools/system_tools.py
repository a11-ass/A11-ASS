"""系统工具：日期时间与闰年判断。"""

from __future__ import annotations

import subprocess

from ...application.registry import FunctionTool
from ...domain.models import ToolSpec


def get_date(args=None) -> str:
    date_str = subprocess.run(
        "date /t", shell=True, capture_output=True, text=True
    ).stdout.strip()
    time_str = subprocess.run(
        "time /t", shell=True, capture_output=True, text=True
    ).stdout.strip()
    return "当前电脑日期: %s，时间: %s" % (date_str, time_str)


def is_leap_year(args) -> str:
    year = int(args["year"])
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return "%d 年%s闰年" % (year, "是" if leap else "不是")


def _tool(name: str, description: str, parameters: dict, handler) -> FunctionTool:
    return FunctionTool(
        spec=ToolSpec(name=name, description=description, parameters=parameters),
        handler=handler,
    )


SYSTEM_TOOLS = [
    _tool(
        name="getDate",
        description="获取当前电脑的日期和时间（调用本地 date/time 命令）",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_date,
    ),
    _tool(
        name="isLeapYear",
        description="计算输入的年份是否为闰年",
        parameters={
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "要计算的年份，例如 2024",
                }
            },
            "required": ["year"],
        },
        handler=is_leap_year,
    ),
]
