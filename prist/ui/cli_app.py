"""CLI 界面（备选）：简单的 input()/print() 循环。"""

from __future__ import annotations

import sys
import time
from typing import Iterator

from ..application.agent_service import AgentService
from ..domain.events import AgentEvent


class CliApp:
    """最简命令行：input() 逐轮交互。"""

    def __init__(self, agent: AgentService) -> None:
        self._agent = agent

    def run(self) -> None:
        print("prist CLI 启动（输入 quit 退出）")
        while True:
            try:
                question = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break
            if question.lower() in ("quit", "exit", ""):
                if question:
                    break
                continue
            try:
                self._handle_turn(question)
            except Exception as exc:
                print(f"[错误] {exc}")

    def _handle_turn(self, question: str) -> None:
        print("AI: ", end="", flush=True)
        started = False
        for event in self._agent.run_turn(question):
            if not started:
                started = True
            self._print_event(event)

    def _print_event(self, event: AgentEvent) -> None:
        from ..domain.events import (
            TextDelta, ToolStarted, ToolFinished, TurnCompleted, TurnFailed,
        )
        if isinstance(event, ToolStarted):
            args = ", ".join(f"{k}={v}" for k, v in event.arguments.items())
            print(f"\n  🔧 [{event.name}({args})]", end="")
        elif isinstance(event, ToolFinished):
            status = "✓" if event.ok else "✗"
            print(f" → {status} {event.output[:100]}")
        elif isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
        elif isinstance(event, TurnCompleted):
            print()
        elif isinstance(event, TurnFailed):
            print(f"\n  💥 {event.message}")
