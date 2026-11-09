"""prist 启动器 —— 运行此脚本会弹一个**独立的 cmd 窗口**来跑 main.py。

用法：
  python run.py          ← 推荐，敲一条命令就弹新窗口
  或双击 run.vbs（隐藏黑框）

原理：用 CREATE_NEW_CONSOLE 标志 fork 一个新的 cmd 窗口，
      当前终端立即释放，不阻塞。
"""
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    main_py = os.path.join(here, "main.py")

    if not os.path.isfile(main_py):
        print(f"❌ 找不到 main.py: {main_py}", file=sys.stderr)
        return 1

    # CREATE_NEW_CONSOLE = 0x00000010  → 强制弹新的控制台窗口
    # DETACHED_PROCESS = 0x00000008    → （备选）完全脱离父进程
    CREATE_NEW_CONSOLE = 0x00000010

    # 用 cmd /k 包一层，窗口跑完后不自动关闭（方便看报错）
    cmd_line = f'cmd /k "cd /d "{here}" && python "{main_py}""'

    try:
        subprocess.Popen(
            cmd_line,
            creationflags=CREATE_NEW_CONSOLE,
            cwd=here,
        )
        print("✅ prist 已在新窗口中启动！")
        print(f"   路径: {here}")
    except OSError as exc:
        print(f"❌ 启动失败: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
