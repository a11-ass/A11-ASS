"""Shared pytest fixtures.

Every HTTP interaction in the test suite is routed through
``httpx.MockTransport`` — no test ever touches the real Go backend.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from pet_hospital_mcp.config import Settings
from pet_hospital_mcp.rest_client import RestApiClient


def make_backend_response(
    *,
    data: Any = None,
    status_code: int = 200,
    message: str = "ok",
) -> httpx.Response:
    """Build a Go-style envelope response."""
    body: dict[str, Any] = {"code": status_code, "message": message, "time": "2026-09-15T00:00:00Z"}
    if data is not None:
        body["data"] = data
    return httpx.Response(
        status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(body).encode(),
    )


def make_list_data(
    items: list[dict[str, Any]] | None = None,
    *,
    total: int | None = None,
    page: int = 1,
    page_size: int = 20,
    total_cost: float = 0.0,
) -> dict[str, Any]:
    """Build a canonical ``data`` payload for GET /api/v1/pets."""
    if items is None:
        items = []
    if total is None:
        total = len(items)
    total_pages = (total + page_size - 1) // page_size if page_size else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "totalCost": total_cost,
    }


def sample_pet(pet_id: str = "PET-000001", **overrides: Any) -> dict[str, Any]:
    """A minimal valid pet record."""
    base: dict[str, Any] = {
        "id": pet_id,
        "name": "旺财",
        "species": "犬",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "doctor": "李医生",
        "disease": "急性肠胃炎",
        "status": "已康复",
        "totalCost": 380.0,
        "visitCount": 1,
        "createdAt": "2025-01-01T00:00:00Z",
        "updatedAt": "2025-01-02T00:00:00Z",
        "records": None,  # backend may send null
        "charges": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def settings() -> Settings:
    return Settings(
        host="127.0.0.1",
        port=8100,
        pet_hospital_base_url="http://test-backend",
        backend_timeout_seconds=1.0,
        backend_retries=1,
        backend_backoff_seconds=0.0,
        log_level="WARNING",
    )


@pytest.fixture
def mock_transport_factory() -> Callable[[Callable[[httpx.Request], httpx.Response]], httpx.MockTransport]:
    """Return a factory that builds an httpx.MockTransport from a handler."""
    def _factory(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
        return httpx.MockTransport(handler)
    return _factory


@pytest.fixture
def make_client(settings, mock_transport_factory):
    """Build a RestApiClient wired to a custom transport handler."""
    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> RestApiClient:
        transport = mock_transport_factory(handler)
        http_client = httpx.AsyncClient(
            base_url=settings.pet_hospital_base_url,
            transport=transport,
            timeout=httpx.Timeout(settings.backend_timeout_seconds),
        )
        client = RestApiClient(settings)
        client._client = http_client
        return client
    return _make


@pytest.fixture
def sample_list_data():
    """Return the data-builder for tests to call with their own items."""
    return make_list_data


@pytest.fixture
def sample_pet_factory():
    return sample_pet


@pytest.fixture
def make_response():
    return make_backend_response
