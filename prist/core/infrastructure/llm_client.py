"""OpenAI 兼容的大模型客户端。

支持非流式（complete）和流式（stream）两种调用，
适配智谱、通义、DeepSeek 等 OpenAI 兼容 API。
"""

from __future__ import annotations

import json
from typing import Iterator, Sequence

import requests

from ..domain.models import (
    AssistantMessage,
    ChatMessage,
    ToolCall,
)
from ..domain.ports import LLMClient
from .config import Settings


class OpenAICompatibleClient(LLMClient):
    """基于 requests 实现的 OpenAI 兼容客户端。"""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.base_url
        self._api_key = settings.api_key
        self._model = settings.model
        self._timeout = settings.timeout

    # ---------- 公共接口 ----------

    def complete(
        self, messages: Sequence[ChatMessage], tools: Sequence
    ) -> AssistantMessage:
        """非流式调用，返回完整响应（含 tool_calls）。"""
        api_msgs = [m.to_api() for m in messages]
        payload = {
            "model": self._model,
            "messages": api_msgs,
            "stream": False,
        }
        if tools:
            payload["tools"] = [t.to_api() for t in tools]

        data = self._post("/chat/completions", payload)
        choice = data["choices"][0]
        msg = choice["message"]

        content = msg.get("content")
        raw_calls = msg.get("tool_calls") or []
        tool_calls = []
        for call in raw_calls:
            func = call.get("function", {})
            tool_calls.append(
                ToolCall(
                    id=call.get("id", ""),
                    name=func.get("name", ""),
                    arguments=_parse_args(func.get("arguments", "{}")),
                )
            )

        return AssistantMessage(content=content, tool_calls=tool_calls)

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """流式调用，逐段产出文本。"""
        api_msgs = [m.to_api() for m in messages]
        payload = {
            "model": self._model,
            "messages": api_msgs,
            "stream": True,
        }

        with self._post_stream("/chat/completions", payload) as resp:
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("data: "):
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    chunk = delta.get("content") or delta.get("reasoning_content")
                    if chunk:
                        yield chunk

    # ---------- 内部实现 ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer %s" % self._api_key,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict) -> dict:
        url = self._base_url + path
        resp = requests.post(
            url, headers=self._headers(), json=payload, timeout=self._timeout
        )
        self._raise_for_status(resp)
        return resp.json()

    def _post_stream(self, path: str, payload: dict) -> requests.Response:
        url = self._base_url + path
        resp = requests.post(
            url, headers=self._headers(), json=payload,
            timeout=self._timeout, stream=True,
        )
        self._raise_for_status(resp)
        return resp

    @staticmethod
    def _raise_for_status(resp: requests.Response) -> None:
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise RuntimeError(
                "LLM API 返回错误 %d: %s" % (resp.status_code, body)
            )


def _parse_args(raw: str) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
