# 阶段3：无限循环对话，直到 Ctrl+C 退出（不携带历史）+ 等待转圈提示
import configparser
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

print("输入内容开始对话，按 Ctrl+C 退出")
while True:
    try:
        question = input("你: ")
        spinner = Spinner()
        spinner.start()
        resp = requests.post(
            base_url + "/chat/completions",
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "user", "content": question}],
                  "stream": False},
        )
        answer = resp.json()["choices"][0]["message"]["content"]
        spinner.stop()
        print("AI:", answer)
    except (KeyboardInterrupt, EOFError):
        print("\n再见！")
        break
