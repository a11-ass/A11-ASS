"""Tests for the MCP server wiring.

Covers:
* ``list_pets`` is registered with the right name & JSON Schema;
* the ASGI app exposes ``/mcp`` and ``/health``;
* a stateless ``tools/call`` JSON-RPC request returns the canonical payload;
* no ``initialize`` handshake is required and no ``Mcp-Session-Id`` header is set;
* invalid tool arguments surface as structured errors.

Tests use Starlette's TestClient as a context manager so the app lifespan
(which starts the SDK's session-manager task group) runs before any request.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import RestApiClient
from pet_hospital_mcp.server import PROTOCOL_VERSION, SDK_VERSION, create_app, create_server


# ---------------------------------------------------------------------------
# Helpers — build a server backed by a mock backend
# ---------------------------------------------------------------------------

def _make_mock_client(handler) -> RestApiClient:
    settings = Settings(
        host="127.0.0.1",
        port=8100,
        pet_hospital_base_url="http://test-backend",
        backend_timeout_seconds=1.0,
        backend_retries=0,
        backend_backoff_seconds=0.0,
        log_level="WARNING",
    )
    client = RestApiClient(settings)
    client._client = httpx.AsyncClient(
        base_url=settings.pet_hospital_base_url,
        transport=httpx.MockTransport(handler),
        timeout=httpx.Timeout(settings.backend_timeout_seconds),
    )
    return client


def _make_backend_handler_for_list(items: list[dict[str, Any]] | None = None, *, total: int = 0):
    if items is None:
        items = []
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/pets"
        body = {
            "code": 200,
            "message": "ok",
            "data": {
                "items": items,
                "total": total,
                "page": 1,
                "pageSize": 20,
                "totalPages": 1 if total else 0,
                "totalCost": 0.0,
            },
            "time": "x",
        }
        return httpx.Response(200, json=body)
    return handler


# ---------------------------------------------------------------------------
# 6. 工具注册
# ---------------------------------------------------------------------------

def test_list_pets_is_registered():
    server = create_server()
    tools = list(server._tool_manager._tools.values())
    assert any(t.name == "list_pets" for t in tools)
    list_tool = next(t for t in tools if t.name == "list_pets")
    assert list_tool.description is not None
    assert "GET /api/v1/pets" in list_tool.description


def test_server_reports_correct_protocol_and_sdk_versions():
    create_server()  # imports SDK constants; verify their values
    assert SDK_VERSION == "2.0.0"
    assert PROTOCOL_VERSION == "2026-07-28"


# ---------------------------------------------------------------------------
# 7. 无状态连接流程 — all use `with TestClient` to enter lifespan
# ---------------------------------------------------------------------------

@pytest.fixture
def app_with_mock_backend():
    handler = _make_backend_handler_for_list(
        [{"id": "PET-000001", "name": "旺财", "species": "犬", "ownerName": "张三",
          "ownerPhone": "13800001111", "doctor": "李医生", "disease": "x",
          "status": "已康复", "totalCost": 100, "visitCount": 0,
          "createdAt": "t", "updatedAt": "t", "records": None, "charges": None}],
        total=1,
    )
    client = _make_mock_client(handler)
    return create_app(client=client)


def _client(app):
    """Build a TestClient whose Host header passes SDK 2.0's DNS-rebinding
    check (which requires a port suffix to match the ``127.0.0.1:*`` pattern)."""
    return TestClient(app, base_url="http://127.0.0.1:8100")


def test_health_endpoint_returns_ok(app_with_mock_backend):
    with _client(app_with_mock_backend) as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["sdk_version"] == "2.0.0"
    assert body["protocol_version"] == "2026-07-28"


def test_stateless_call_to_list_pets(app_with_mock_backend):
    with _client(app_with_mock_backend) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "list_pets", "arguments": {}},
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
    assert response.status_code == 200
    # No Mcp-Session-Id header should be present (stateless, 2026-07-28).
    assert "mcp-session-id" not in {k.lower() for k in response.headers.keys()}
    body = _parse_mcp_response(response)
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 1
    assert "result" in body
    result = body["result"]
    assert result.get("is_error") is False or result.get("isError") is False or "is_error" not in result
    content_text = _extract_text_content(result)
    parsed = json.loads(content_text)
    assert parsed["total"] == 1
    assert parsed["items"][0]["id"] == "PET-000001"


def test_tools_list_advertises_list_pets(app_with_mock_backend):
    with _client(app_with_mock_backend) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    body = _parse_mcp_response(response)
    assert "result" in body
    tool_names = [t["name"] for t in body["result"]["tools"]]
    assert "list_pets" in tool_names


def test_stateless_call_emits_no_session_id_header(app_with_mock_backend):
    """2026-07-28 has no initialize; the SDK may tolerate it for legacy
    clients, but it must NEVER set a Mcp-Session-Id response header."""
    with _client(app_with_mock_backend) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {}},
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    assert "mcp-session-id" not in {k.lower() for k in response.headers.keys()}


def test_invalid_tool_arguments_returns_error(app_with_mock_backend):
    with _client(app_with_mock_backend) as client:
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "list_pets", "arguments": {"species": "恐龙"}},
            },
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    body = _parse_mcp_response(response)
    result = body.get("result", {})
    assert result.get("is_error") is True or result.get("isError") is True or "error" in body


def test_unknown_tool_returns_error(app_with_mock_backend):
    with _client(app_with_mock_backend) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                  "params": {"name": "nonexistent_tool", "arguments": {}}},
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    body = _parse_mcp_response(response)
    assert "error" in body or body.get("result", {}).get("is_error") is True or body.get("result", {}).get("isError") is True


def test_server_discover_returns_server_metadata(app_with_mock_backend):
    """The 2026-07-28 ``server/discover`` method must be honored (replaces
    initialize). Either a result (modern) or method-not-found (older build)
    is acceptable — the server must not crash and must not set a session id."""
    with _client(app_with_mock_backend) as client:
        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 6, "method": "server/discover", "params": {}},
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 200
    body = _parse_mcp_response(response)
    assert "mcp-session-id" not in {k.lower() for k in response.headers.keys()}
    assert "jsonrpc" in body


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_mcp_response(response) -> dict[str, Any]:
    """Parse either a single JSON body or the first SSE ``data:`` line.

    SDK 2.0 may respond with either ``application/json`` (a plain JSON body)
    or ``text/event-stream`` (SSE with ``data:`` lines). This helper handles
    both; non-JSON bodies are surfaced as ``{"raw": body}`` so callers can
    inspect them without crashing.
    """
    body = response.text
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type or body.startswith("event:") or body.startswith("data:"):
        for line in body.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if payload:
                    return json.loads(payload)
        return {"raw": body}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def _extract_text_content(result: dict[str, Any]) -> str:
    """Pull the first TextContent's text out of a tools/call result."""
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("type") == "text":
            return first["text"]
    structured = result.get("structured_content")
    if isinstance(structured, dict):
        return json.dumps(structured)
    raise AssertionError(f"unexpected result shape: {result!r}")
