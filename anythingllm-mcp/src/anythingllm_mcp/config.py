"""Configuration loaded from environment variables.

Env vars:
    ANYTHINGLLM_BASE_URL  default http://localhost:3001
    ANYTHINGLLM_API_KEY    required — create in AnythingLLM Settings > API Keys
    MCP_PORT               default 8101
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    port: int


def load_settings() -> Settings:
    base = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3001").rstrip("/")
    key = os.getenv("ANYTHINGLLM_API_KEY", "")
    port = int(os.getenv("MCP_PORT", "8101"))
    return Settings(base_url=base, api_key=key, port=port)
