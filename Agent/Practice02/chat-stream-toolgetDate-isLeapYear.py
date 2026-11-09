# 第六周（二）：在上一份代码基础上，新增 function call 工具 isLeapYear
# —— 计算输入的年份是否为闰年（用 python 代码计算）
# 现在共两个工具：getDate（调本地 date 命令）、isLeapYear（python 计算）
import configparser
import json
import subprocess
import sys
import threading
import time

import requests


class Spinner:
    """等待 AI 回复时，在控制台显示转圈提示。"""

    def __init__(self, msg="AI 正在思考"):
        self.msg = msg
        self._stop = False
        self._t = None

    def _run(self):
        chars = "|/-="
        i = 0
        while not self._stop:
            sys.stdout.write("\r" + self.msg + " " + chars[i % 4])
            sys.stdout.flush()
            i += 1
            time.sleep(0.12)
        sys.stdout.write("\r" + " " * 30 + "\r")
        sys.stdout.flush()

    def start(self):
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self):
        self._stop = True
        if self._t:
            self._t.join()


def getDate(args=None):
    """调用本地 date / time 命令获取当前电脑的日期和时间。"""
    date_str = subprocess.run("date /t", shell=True, capture_output=True, text=True).stdout.strip()
    time_str = subprocess.run("time /t", shell=True, capture_output=True, text=True).stdout.strip()
    return "当前电脑日期: %s，时间: %s" % (date_str, time_str)


def isLeapYear(args):
    """用 python 代码计算某一年是否为闰年（能被4整除但不能被100整除，或能被400整除）。"""
    year = int(args["year"])
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return "%d 年%s闰年" % (year, "是" if leap else "不是")


# 工具名 -> 真正执行的函数
TOOLS_IMPL = {"getDate": getDate, "isLeapYear": isLeapYear}

# 工具声明（告诉大模型有哪些工具可用）
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "计算输入的年份是否为闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "要计算的年份，例如 2024"}
                },
                "required": ["year"],
            },
        },
    },
]

# 系统提示：引导大模型在需要时调用工具，避免它凭记忆瞎猜
SYSTEM = "当用户询问当前日期、时间、今天几号等问题时，必须调用 getDate 工具；当用户询问某一年是否为闰年时，必须调用 isLeapYear 工具计算。不要凭记忆或猜测回答，必须通过工具得到确切结果。"

cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8")
base_url = cfg["llm"]["base_url"].rstrip("/")
api_key = cfg["llm"]["api_key"]
model = cfg["llm"]["model"]

HEADERS = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}


def ask_model(messages):
    """第一次调用：非流式，用来判断大模型是否需要调用工具。"""
    resp = requests.post(
        base_url + "/chat/completions",
        headers=HEADERS,
        json={"model": model, "messages": messages, "tools": TOOLS, "stream": False},
    )
    return resp.json()["choices"][0]["message"]


def stream_answer(messages):
    """第二次调用：流式（打字机）输出最终答案，返回完整文本。"""
    spinner = Spinner()
    spinner.start()
    resp = requests.post(
        base_url + "/chat/completions",
        headers=HEADERS,
        json={"model": model, "messages": messages, "stream": True},
        stream=True,
    )
    full = ""
    first = True
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            break
        delta = json.loads(data)["choices"][0]["delta"].get("content", "")
        if delta:
            if first:
                spinner.stop()
                sys.stdout.write("AI: ")
                first = False
            sys.stdout.write(delta)
            sys.stdout.flush()
            full += delta
    spinner.stop()
    print()
    return full


messages = [{"role": "system", "content": SYSTEM}]
print("输入内容开始对话，按 Ctrl+C 退出（可以试试：2024年是闰年吗？/ 今年是闰年吗？）")
while True:
    try:
        question = input("你: ")
        messages.append({"role": "user", "content": question})

        spinner = Spinner()
        spinner.start()
        msg = ask_model(messages)
        spinner.stop()

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            # 大模型决定调用工具：本地执行后把结果回传，再让它给出最终回答
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"] or "{}")
                print("  [调用工具] %s(%s)" % (name, args))
                result = TOOLS_IMPL[name](args)
                print("  [工具结果] %s" % result)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            answer = stream_answer(messages)
            messages.append({"role": "assistant", "content": answer})
        else:
            print("AI:", msg.get("content", ""))
            messages.append({"role": "assistant", "content": msg.get("content", "")})
    except (KeyboardInterrupt, EOFError):
        print("\n再见！")
        break
