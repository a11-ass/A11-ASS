# 阶段2：打字机样式的流式（Stream）输出 + 等待转圈提示
import configparser
import json
import requests

import threading
import time
import sys


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

cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8")
base_url = cfg["llm"]["base_url"].rstrip("/")
api_key = cfg["llm"]["api_key"]
model = cfg["llm"]["model"]

question = input("你: ")
spinner = Spinner()
spinner.start()
resp = requests.post(
    base_url + "/chat/completions",
    headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    json={"model": model,
          "messages": [{"role": "user", "content": question}],
          "stream": True},
    stream=True,
)
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
spinner.stop()
print()
