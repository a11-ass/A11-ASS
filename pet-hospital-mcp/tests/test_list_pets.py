"""Tests for the ``list_pets`` tool.

Covers: input validation, parameter forwarding, backend success/4xx/5xx,
timeout, connection error, invalid JSON, schema mismatch, log redaction.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import httpx
import pytest

from pet_hospital_mcp.errors import ErrorCode, ToolError
from pet_hospital_mcp.logging_config import redact_params
from pet_hospital_mcp.tools.list_pets import (
    ListPetsInput,
    handle_list_pets,
)


# ---------------------------------------------------------------------------
# 1. 正常调用 — 全部过滤/排序/分页参数正确转发
# ---------------------------------------------------------------------------

async def test_normal_call_forwards_all_params(make_client, make_response, sample_list_data, sample_pet_factory):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        items = [sample_pet_factory("PET-000001"), sample_pet_factory("PET-000002")]
        return make_response(data=sample_list_data(items, total=2, page=1, page_size=10, total_cost=760.0))

    client = make_client(handler)
    result = await handle_list_pets(
        {
            "q": "肠胃炎",
            "name": "旺财",
            "ownerName": "张三",
            "ownerPhone": "13800001111",
            "species": "犬",
            "doctor": "李医生",
            "disease": "急性",
            "status": "已康复",
            "min": 100,
            "max": 1000,
            "sortBy": "totalCost",
            "order": "desc",
            "page": 1,
            "pageSize": 10,
        },
        client=client,
    )

    assert captured["params"] == {
        "q": "肠胃炎",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "species": "犬",
        "doctor": "李医生",
        "disease": "急性",
        "status": "已康复",
        "min": "100.0",
        "max": "1000.0",
        "sortBy": "totalCost",
        "order": "desc",
        "page": "1",
        "pageSize": "10",
    }
    assert result["total"] == 2
    assert result["page"] == 1
    assert result["pageSize"] == 10
    assert result["totalPages"] == 1
    assert result["totalCost"] == 760.0
    assert len(result["items"]) == 2
    assert result["items"][0]["id"] == "PET-000001"


async def test_default_call_forwards_only_defaults(make_client, make_response, sample_list_data):
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response(data=sample_list_data([], total=0, page=1, page_size=20))

    client = make_client(handler)
    result = await handle_list_pets({}, client=client)
    assert result["items"] == []
    assert result["total"] == 0
    assert result["page"] == 1
    assert result["pageSize"] == 20


# ---------------------------------------------------------------------------
# 2. 输入校验失败
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "overrides, expected_code",
    [
        # 无效 species
        ({"species": "恐龙"}, ErrorCode.VALIDATION_ERROR),
        # 无效 status
        ({"status": "垂危"}, ErrorCode.VALIDATION_ERROR),
        # 无效 sortBy
        ({"sortBy": "weight"}, ErrorCode.VALIDATION_ERROR),
        # 无效 order
        ({"order": "up"}, ErrorCode.VALIDATION_ERROR),
        # page < 1
        ({"page": 0}, ErrorCode.VALIDATION_ERROR),
        # pageSize < 1
        ({"pageSize": 0}, ErrorCode.VALIDATION_ERROR),
        # pageSize > 500
        ({"pageSize": 501}, ErrorCode.VALIDATION_ERROR),
        # min 负数
        ({"min": -1}, ErrorCode.VALIDATION_ERROR),
        # max 负数
        ({"max": -1}, ErrorCode.VALIDATION_ERROR),
        # min > max
        ({"min": 1000, "max": 100}, ErrorCode.VALIDATION_ERROR),
        # 未知字段
        ({"color": "黑"}, ErrorCode.VALIDATION_ERROR),
        # 类型不正确
        ({"page": "abc"}, ErrorCode.VALIDATION_ERROR),
    ],
)
async def test_validation_errors(overrides, expected_code, make_client):
    client = make_client(lambda r: httpx.Response(200, json={"code": 200, "data": {}}))
    base: dict[str, Any] = {"page": 1, "pageSize": 10}
    base.update(overrides)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets(base, client=client)
    assert exc_info.value.code == expected_code


async def test_validation_rejects_nan(make_client):
    client = make_client(lambda r: httpx.Response(200, json={"data": {}}))
    # Bypass Pydantic to inject NaN via raw dict — handler validates internally
    raw = {"min": float("nan")}
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets(raw, client=client)
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


async def test_validation_rejects_infinity(make_client):
    client = make_client(lambda r: httpx.Response(200, json={"data": {}}))
    raw = {"min": float("inf")}
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets(raw, client=client)
    assert exc_info.value.code == ErrorCode.VALIDATION_ERROR


# ---------------------------------------------------------------------------
# 3. 后端 4xx / 5xx
# ---------------------------------------------------------------------------

async def test_backend_4xx_raises_api_error(make_client, make_response):
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response(status_code=400, message="bad request")

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_API_ERROR


async def test_backend_5xx_retries_then_raises(make_client, make_response, settings):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return make_response(status_code=500, message="boom")

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_API_ERROR
    # original attempt + retries
    assert call_count["n"] == settings.backend_retries + 1


async def test_backend_5xx_recovered_on_retry(make_client, make_response, sample_list_data):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            return make_response(status_code=500, message="boom")
        return make_response(data=sample_list_data([], total=0, page=1, page_size=20))

    client = make_client(handler)
    result = await handle_list_pets({}, client=client)
    assert result["items"] == []
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 4. 超时和连接异常
# ---------------------------------------------------------------------------

async def test_backend_timeout_raises_timeout_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated")

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_TIMEOUT


async def test_backend_connection_error_raises_unavailable(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated")

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_UNAVAILABLE


# ---------------------------------------------------------------------------
# 5. 后端返回非法 JSON / schema 不匹配
# ---------------------------------------------------------------------------

async def test_backend_invalid_json_raises_invalid_response(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", headers={"content-type": "text/plain"})

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_INVALID_RESPONSE


async def test_backend_missing_required_fields(make_client, make_response):
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response(data={"items": [], "page": 1})  # missing total/pageSize/totalPages/totalCost

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_INVALID_RESPONSE


async def test_backend_items_not_list(make_client, make_response):
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response(
            data={
                "items": "not-a-list",
                "total": 0,
                "page": 1,
                "pageSize": 20,
                "totalPages": 0,
                "totalCost": 0,
            }
        )

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_INVALID_RESPONSE


async def test_backend_null_data_raises_api_error(make_client, make_response):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 200, "message": "ok", "data": None, "time": "x"},
        )

    client = make_client(handler)
    with pytest.raises(ToolError) as exc_info:
        await handle_list_pets({}, client=client)
    assert exc_info.value.code == ErrorCode.BACKEND_API_ERROR


async def test_backend_null_records_and_charges_are_tolerated(make_client, make_response, sample_list_data, sample_pet_factory):
    """Backend may emit records=null / charges=null — must not fail validation."""
    def handler(request: httpx.Request) -> httpx.Response:
        items = [sample_pet_factory("PET-000001", records=None, charges=None)]
        return make_response(data=sample_list_data(items, total=1, page=1, page_size=20))

    client = make_client(handler)
    result = await handle_list_pets({}, client=client)
    assert result["items"][0]["records"] is None
    assert result["items"][0]["charges"] is None


# ---------------------------------------------------------------------------
# 日志脱敏
# ---------------------------------------------------------------------------

def test_log_redaction_masks_owner_phone():
    params = {"ownerPhone": "13800001111", "ownerAddr": "北京", "chipNo": "CHIP-X", "name": "旺财"}
    redacted = redact_params(params)
    assert redacted["ownerPhone"] == "***"
    assert redacted["ownerAddr"] == "***"
    assert redacted["chipNo"] == "***"
    assert redacted["name"] == "旺财"


def test_log_redaction_recursive():
    params = {
        "items": [{"ownerPhone": "13800001111", "nested": {"owner_phone": "13900002222"}}],
    }
    redacted = redact_params(params)
    assert redacted["items"][0]["ownerPhone"] == "***"
    assert redacted["items"][0]["nested"]["owner_phone"] == "***"


# ---------------------------------------------------------------------------
# 边界 — Pydantic 模型直测
# ---------------------------------------------------------------------------

def test_list_pets_input_accepts_valid_input():
    ListPetsInput.model_validate(
        {"species": "犬", "status": "已康复", "page": 1, "pageSize": 10, "min": 0, "max": 1000}
    )


def test_list_pets_input_rejects_extra_field():
    with pytest.raises(Exception):
        ListPetsInput.model_validate({"unknown": "x"})


def test_list_pets_input_rejects_nan_via_validator():
    with pytest.raises(Exception):
        ListPetsInput.model_validate({"min": float("nan")})


# ---------------------------------------------------------------------------
# Loop drift regression — RestApiClient must rebuild its httpx.AsyncClient
# when reused across different event loops (stateless MCP server scenario).
# ---------------------------------------------------------------------------

async def test_rest_client_rebuilds_when_loop_drifts(settings):
    """A client whose recorded loop differs from the running loop must
    transparently rebuild its ``httpx.AsyncClient`` instead of raising
    ``RuntimeError: ... attached to a different loop``.

    Uses a real ``RestApiClient`` (no injected transport) so that the rebuild
    path is exercised end-to-end; we only assert on ``_client``/``_loop``
    state, not on a successful HTTP call.
    """
    from pet_hospital_mcp.rest_client import RestApiClient

    client = RestApiClient(settings)
    # Prime it once — creates an httpx.AsyncClient bound to the current loop.
    first = await client._ensure_client()
    assert first is client._client
    assert client._loop is asyncio.get_running_loop()
    stale_client = client._client

    # Simulate loop drift: pretend the recorded loop is some other object.
    client._loop = object()  # not the running loop

    # _ensure_client must detect the drift and rebuild.
    rebuilt = await client._ensure_client()
    assert rebuilt is not stale_client
    assert client._client is rebuilt
    assert client._loop is asyncio.get_running_loop()

    await client.aclose()


async def test_rest_client_reuses_when_same_loop(make_client, make_response, sample_list_data):
    """When the loop hasn't changed, the existing client is reused (no rebuild)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response(data=sample_list_data([], total=0, page=1, page_size=20))

    client = make_client(handler)
    # Touch _ensure_client once so it records the current loop (injected
    # clients have _loop=None which means "trust and reuse", so simulate a
    # self-created client by setting _loop explicitly).
    client._loop = asyncio.get_running_loop()
    first_client = client._client
    assert first_client is not None

    await client.get_json("/api/v1/pets")
    # Same loop → same underlying httpx.AsyncClient instance.
    assert client._client is first_client


async def test_rest_client_reuses_injected_client_with_none_loop(make_client, make_response, sample_list_data):
    """Externally injected clients (tests) have ``_loop=None`` and must be
    trusted as-is — never rebuilt — so the mock transport stays in place."""
    def handler(request: httpx.Request) -> httpx.Response:
        return make_response(data=sample_list_data([], total=0, page=1, page_size=20))

    client = make_client(handler)
    assert client._loop is None  # fixture doesn't set _loop
    injected = client._client
    assert injected is not None

    await client.get_json("/api/v1/pets")
    # Injected client (signalled by _loop=None) must be reused verbatim.
    assert client._client is injected
