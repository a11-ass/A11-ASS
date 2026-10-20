# 第六周（三）：在 isLeapYear 版本基础上，新增 10 个本地文件操作 function call 工具
# 最终共 12 个工具：getDate / isLeapYear + 10 个文件操作工具
import configparser
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import requests


# ---------- 基础类 ----------
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


# ---------- 工具 1：getDate（调本地命令） ----------
def getDate(args=None):
    date_str = subprocess.run("date /t", shell=True, capture_output=True, text=True).stdout.strip()
    time_str = subprocess.run("time /t", shell=True, capture_output=True, text=True).stdout.strip()
    return "当前电脑日期: %s，时间: %s" % (date_str, time_str)


# ---------- 工具 2：isLeapYear（Python 计算） ----------
def isLeapYear(args):
    year = int(args["year"])
    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return "%d 年%s闰年" % (year, "是" if leap else "不是")


# ---------- 工具 3：getCwd  获取当前工作目录 ----------
def getCwd(args=None):
    return os.getcwd()


# ---------- 工具 4：listDir  列出指定目录下所有文件和子目录 ----------
def listDir(args):
    path = args.get("path", ".")
    if not os.path.isdir(path):
        return "错误: 目录不存在 - %s" % path
    items = sorted(os.listdir(path))
    lines = []
    for name in items:
        full = os.path.join(path, name)
        t = "目录" if os.path.isdir(full) else "文件"
        lines.append("[%s] %s" % (t, name))
    return "\n".join(lines) if lines else "(空目录)"


# ---------- 工具 5：getFileType  获取指定文件的文件类型 ----------
def getFileType(args):
    path = args["path"]
    if not os.path.exists(path):
        return "错误: 文件不存在 - %s" % path
    ext = os.path.splitext(path)[1].lower()
    kind = "目录" if os.path.isdir(path) else "文件"
    size = os.path.getsize(path)
    return "类型: %s, 扩展名: %s, 大小: %d 字节" % (kind, ext or "(无)", size)


# ---------- 工具 6：readFile  获取指定文件的内容（仅支持纯文本） ----------
def readFile(args):
    path = args["path"]
    if not os.path.isfile(path):
        return "错误: 文件不存在 - %s" % path
    # 简单判断：二进制扩展名拒绝
    binary = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".pdf",
              ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
              ".exe", ".dll", ".pyc", ".db", ".sqlite", ".mp3", ".mp4"}
    if os.path.splitext(path)[1].lower() in binary:
        return "错误: 该文件为二进制格式，不支持直接读取"
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        return "错误: 文件非 UTF-8 编码或为二进制"
    # 限制长度，避免刷屏
    if len(content) > 8000:
        content = content[:8000] + "\n...(已截断)"
    return content


# ---------- 工具 7：createFile  在指定目录下创建新文件 ----------
def createFile(args):
    directory = args.get("directory", ".")
    filename = args["filename"]
    content = args.get("content", "")
    if not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    full = os.path.join(directory, filename)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return "已创建文件: %s (%d 字节)" % (full, len(content))


# ---------- 工具 8：editFile  编辑指定文件的内容（覆盖式写入） ----------
def editFile(args):
    path = args["path"]
    new_content = args.get("new_content", "")
    if not os.path.isfile(path):
        return "错误: 文件不存在 - %s" % path
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return "已更新文件: %s (%d 字节)" % (path, len(new_content))


# ---------- 工具 9：mkdir  创建新目录 ----------
def mkdir(args):
    path = args["path"]
    if os.path.exists(path):
        return "目录已存在: %s" % path
    os.makedirs(path, exist_ok=True)
    return "已创建目录: %s" % path


# ---------- 工具 10：rmdir  删除目录（非空） ----------
def rmdir(args):
    path = args["path"]
    if not os.path.isdir(path):
        return "错误: 目录不存在 - %s" % path
    shutil.rmtree(path)
    return "已删除目录(含内容): %s" % path


# ---------- 工具 11：deleteFile  删除文件 ----------
def deleteFile(args):
    path = args["path"]
    if not os.path.isfile(path):
        return "错误: 文件不存在 - %s" % path
    os.remove(path)
    return "已删除文件: %s" % path


# ---------- 工具 12：rename  重命名文件或目录 ----------
def rename(args):
    old_path = args["old_path"]
    new_path = args["new_path"]
    if not os.path.exists(old_path):
        return "错误: 源不存在 - %s" % old_path
    if os.path.exists(new_path):
        return "错误: 目标已存在 - %s" % new_path
    os.rename(old_path, new_path)
    return "已重命名: %s -> %s" % (old_path, new_path)


# ---------- 工具注册 ----------
TOOLS_IMPL = {
    "getDate": getDate,
    "isLeapYear": isLeapYear,
    "getCwd": getCwd,
    "listDir": listDir,
    "getFileType": getFileType,
    "readFile": readFile,
    "createFile": createFile,
    "editFile": editFile,
    "mkdir": mkdir,
    "rmdir": rmdir,
    "deleteFile": deleteFile,
    "rename": rename,
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间（调用本地 date/time 命令）",
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
                "properties": {"year": {"type": "integer", "description": "要计算的年份，例如 2024"}},
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getCwd",
            "description": "获取当前工作目录（脚本运行所在的目录）",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDir",
            "description": "列出指定目录下所有文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径，例如 . 或 D:/test"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的类型、扩展名和大小",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": "读取指定的纯文本文件内容（.py / .txt / .md / .json / .ini / .html / .mmd 等），二进制文件会拒绝读取",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "在指定目录下创建新的纯文本文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {"type": "string", "description": "目录路径，例如 ."},
                    "filename": {"type": "string", "description": "文件名，例如 result.mmd"},
                    "content": {"type": "string", "description": "文件初始内容（可空）"},
                },
                "required": ["directory", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editFile",
            "description": "覆盖式写入指定文件的完整新内容（仅支持纯文本）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "new_content": {"type": "string", "description": "新的完整内容"},
                },
                "required": ["path", "new_content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mkdir",
            "description": "创建新目录（支持多级嵌套）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rmdir",
            "description": "删除目录（即使目录非空也会一并删除）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "要删除的目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": "删除指定文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename",
            "description": "重命名文件或目录（可跨目录，等同于移动）",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "原路径"},
                    "new_path": {"type": "string", "description": "新路径"},
                },
                "required": ["old_path", "new_path"],
            },
        },
    },
]

# 系统提示：引导大模型在需要时调用工具，尤其是文件操作类
SYSTEM = (
    "你是一个具备本地文件操作能力的 AI 助手。当用户需要知道日期、时间时必须调用 getDate；"
    "计算闰年必须调用 isLeapYear；任何涉及本地文件或目录的操作（查看、读取、创建、编辑、删除、重命名、列出）"
    "都必须调用对应的 function call 工具，不要凭想象编造文件内容。"
    "涉及写文件时，先确认目录或文件路径，再调用 createFile 或 editFile。"
)

# ---------- 配置与请求 ----------
cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8")
base_url = cfg["llm"]["base_url"].rstrip("/")
api_key = cfg["llm"]["api_key"]
model = cfg["llm"]["model"]

HEADERS = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json"}


def ask_model(messages):
    """非流式：第一次调用，判断是否需要工具。"""
    resp = requests.post(
        base_url + "/chat/completions",
        headers=HEADERS,
        json={"model": model, "messages": messages, "tools": TOOLS, "stream": False},
    )
    return resp.json()["choices"][0]["message"]


def stream_answer(messages):
    """流式：打字机输出最终答案。"""
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


# ---------- 主循环 ----------
messages = [{"role": "system", "content": SYSTEM}]
print("已加载 12 个工具。输入开始对话，Ctrl+C 退出。")
print("试试：现在几点了？/ 2024年是闰年吗？/ 列出当前目录 / 读取 config.ini")
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
            messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
            for tc in tool_calls:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"] or "{}")
                print("  [调用工具] %s(%s)" % (name, args))
                result = TOOLS_IMPL[name](args)
                # 文件内容可能很长，打印前 200 字即可
                preview = result if len(result) <= 200 else result[:200] + "..."
                print("  [工具结果] %s" % preview)
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
            answer = stream_answer(messages)
            messages.append({"role": "assistant", "content": answer})
        else:
            print("AI:", msg.get("content", ""))
            messages.append({"role": "assistant", "content": msg.get("content", "")})
    except (KeyboardInterrupt, EOFError):
        print("\n再见！")
        break
