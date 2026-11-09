"""``list_pets`` MCP tool — wraps ``GET /api/v1/pets`` from the Go backend.

Stage 1: this is the only tool the service exposes. Adding future tools is a
matter of dropping a new module under ``tools/`` and registering it from
``server.py`` — the REST client, logging and error conventions are reused.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field, model_validator

from ..errors import ErrorCode, ToolError
from ..logging_config import log_tool_call
from ..rest_client import RestApiClient, default_client

# Mirror of the Go backend's ``ValidSpecies`` (see internal/model/model.go).
VALID_SPECIES: frozenset[str] = frozenset(
    {"犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"}
)
VALID_STATUS: frozenset[str] = frozenset(
    {"待就诊", "就诊中", "住院中", "已康复", "慢性病随访"}
)
VALID_SORT_BY: frozenset[str] = frozenset(
    {
        "id", "name", "ownerName", "species", "doctor", "disease",
        "status", "totalCost", "visitCount", "createdAt", "updatedAt",
    }
)
VALID_ORDER: frozenset[str] = frozenset({"asc", "desc"})

TOOL_NAME = "list_pets"


# ---------------------------------------------------------------------------
# Pydantic models — input, success output, error output
# ---------------------------------------------------------------------------

class ListPetsInput(BaseModel):
    """Input schema for ``list_pets``.

    Field names are kept in camelCase to match the Go query parameters
    verbatim (``ownerName``, ``pageSize`` ...). Pydantic v2 validates enum
    membership, numeric ranges and cross-field invariants via
    :meth:`_validate_cross_fields`.
    """

    model_config = {"extra": "forbid"}

    q: str | None = Field(default=None, description="全文模糊匹配（跨字段）")
    name: str | None = Field(default=None, description="宠物姓名模糊")
    ownerName: str | None = Field(default=None, description="主人姓名模糊")
    ownerPhone: str | None = Field(default=None, description="电话模糊")
    species: str | None = Field(default=None, description="种类精确匹配")
    doctor: str | None = Field(default=None, description="医生姓名模糊")
    disease: str | None = Field(default=None, description="疾病模糊")
    status: str | None = Field(default=None, description="就诊状态精确匹配")
    min: float | None = Field(default=None, ge=0, description="最低总花费")
    max: float | None = Field(default=None, ge=0, description="最高总花费")
    sortBy: str | None = Field(default=None, description="排序字段")
    order: str | None = Field(default=None, description="排序方向 asc/desc")
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    pageSize: int = Field(default=20, ge=1, le=500, description="每页条数 1-500")

    @model_validator(mode="after")
    def _validate_cross_fields(self) -> "ListPetsInput":
        # Reject NaN / Infinity explicitly — Pydantic v2 accepts them by default.
        for field_name in ("min", "max"):
            value = getattr(self, field_name)
            if value is not None:
                if value != value:  # NaN check
                    raise ValueError(f"{field_name} must not be NaN")
                if value in (float("inf"), float("-inf")):
                    raise ValueError(f"{field_name} must be finite")

        if self.species is not None and self.species not in VALID_SPECIES:
            raise ValueError(
                f"species must be one of {sorted(VALID_SPECIES)}, got {self.species!r}"
            )
        if self.status is not None and self.status not in VALID_STATUS:
            raise ValueError(
                f"status must be one of {sorted(VALID_STATUS)}, got {self.status!r}"
            )
        if self.sortBy is not None and self.sortBy not in VALID_SORT_BY:
            raise ValueError(
                f"sortBy must be one of {sorted(VALID_SORT_BY)}, got {self.sortBy!r}"
            )
        if self.order is not None and self.order not in VALID_ORDER:
            raise ValueError(
                f"order must be one of {sorted(VALID_ORDER)}, got {self.order!r}"
            )
        if (
            self.min is not None
            and self.max is not None
            and self.min > self.max
        ):
            raise ValueError("min must be <= max")
        return self


class PetItem(BaseModel):
    """Single pet record returned by the backend.

    ``records`` and ``charges`` are nullable on the Go side (``omitempty``),
    so they are typed as ``Optional[List[...]]`` and normalized to ``[]``
    when the backend emits ``null``.
    """

    model_config = {"extra": "allow"}

    id: str
    name: str
    species: str
    ownerName: str
    ownerPhone: str
    doctor: str
    disease: str
    status: str
    totalCost: float = 0.0
    visitCount: int = 0
    createdAt: str = ""
    updatedAt: str = ""
    records: list[dict[str, Any]] | None = None
    charges: list[dict[str, Any]] | None = None
    breed: str | None = None
    gender: str | None = None
    ageMonths: int | None = None
    color: str | None = None
    chipNo: str | None = None
    ownerAddr: str | None = None
    allergy: str | None = None
    note: str | None = None


class ListPetsSuccess(BaseModel):
    """Successful ``list_pets`` output — maps 1:1 to the Go ``data`` envelope."""

    model_config = {"extra": "allow"}

    items: list[PetItem]
    total: int
    page: int
    pageSize: int
    totalPages: int
    totalCost: float


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

def _build_query_params(params: ListPetsInput) -> dict[str, Any]:
    """Translate the validated input into query parameters for the Go API.

    ``None`` values are omitted so the backend applies its own defaults.
    """
    raw: dict[str, Any] = params.model_dump(exclude_none=True)
    # Only forward fields the Go API actually understands.
    allowed: set[str] = {
        "q", "name", "ownerName", "ownerPhone", "species", "doctor",
        "disease", "status", "min", "max", "sortBy", "order", "page", "pageSize",
    }
    return {k: v for k, v in raw.items() if k in allowed}


def _normalize_pet_item(raw_item: Any) -> PetItem:
    """Coerce one backend record into a :class:`PetItem`.

    Backend guarantees ``records``/``charges`` may be ``null`` or arrays;
    Pydantic handles both. Any structural mismatch becomes a
    :class:`BACKEND_INVALID_RESPONSE` tool error.
    """
    if not isinstance(raw_item, dict):
        raise ToolError(
            ErrorCode.BACKEND_INVALID_RESPONSE,
            "backend returned a non-object pet item",
            details={"item_type": type(raw_item).__name__},
        )
    try:
        return PetItem.model_validate(raw_item)
    except Exception as exc:
        raise ToolError(
            ErrorCode.BACKEND_INVALID_RESPONSE,
            "backend pet item failed schema validation",
            details={"error": str(exc)[:300]},
        ) from exc


async def _call_backend(
    params: ListPetsInput,
    client: RestApiClient | None,
) -> ListPetsSuccess:
    """Issue the request, validate the response and return the success model."""
    query = _build_query_params(params)
    active_client = client or default_client

    data = await active_client.get_json("/api/v1/pets", params=query)

    if not isinstance(data, dict):
        raise ToolError(
            ErrorCode.BACKEND_INVALID_RESPONSE,
            "backend data envelope is not an object",
            details={"data_type": type(data).__name__},
        )

    required_fields = ("items", "total", "page", "pageSize", "totalPages", "totalCost")
    missing = [f for f in required_fields if f not in data]
    if missing:
        raise ToolError(
            ErrorCode.BACKEND_INVALID_RESPONSE,
            "backend data is missing required fields",
            details={"missing": missing},
        )

    items_raw = data["items"]
    if not isinstance(items_raw, list):
        raise ToolError(
            ErrorCode.BACKEND_INVALID_RESPONSE,
            "backend items is not a list",
            details={"items_type": type(items_raw).__name__},
        )

    items = [_normalize_pet_item(raw) for raw in items_raw]

    try:
        return ListPetsSuccess(
            items=items,
            total=int(data["total"]),
            page=int(data["page"]),
            pageSize=int(data["pageSize"]),
            totalPages=int(data["totalPages"]),
            totalCost=float(data["totalCost"]),
        )
    except (TypeError, ValueError) as exc:
        raise ToolError(
            ErrorCode.BACKEND_INVALID_RESPONSE,
            "backend pagination metadata has wrong type",
            details={"error": str(exc)[:300]},
        ) from exc


async def handle_list_pets(
    raw_input: dict[str, Any],
    client: RestApiClient | None = None,
    logger: Any = None,
) -> dict[str, Any]:
    """Entry point invoked by the SDK's tool dispatcher.

    Returns a plain ``dict`` that the SDK serializes as structured content.
    On failure it raises :class:`ToolError` — :func:`register` wraps that into
    the unified error envelope.
    """
    # 1. Validate input — produces VALIDATION_ERROR on any schema failure.
    try:
        params = ListPetsInput.model_validate(raw_input)
    except Exception as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"invalid input for {TOOL_NAME}",
            details={"errors": str(exc)[:500]},
        ) from exc

    # 2. Call backend + normalize.
    start = time.perf_counter()
    try:
        success = await _call_backend(params, client)
    except ToolError as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        if logger is not None:
            log_tool_call(
                logger, TOOL_NAME, raw_input, "error", duration_ms, exc.code.value
            )
        raise
    except Exception as exc:
        duration_ms = (time.perf_counter() - start) * 1000
        if logger is not None:
            log_tool_call(
                logger, TOOL_NAME, raw_input, "error", duration_ms,
                ErrorCode.INTERNAL_ERROR.value,
            )
        raise ToolError(
            ErrorCode.INTERNAL_ERROR,
            f"unexpected internal error: {exc.__class__.__name__}",
            details={"error": str(exc)[:300]},
        ) from exc

    duration_ms = (time.perf_counter() - start) * 1000
    if logger is not None:
        log_tool_call(logger, TOOL_NAME, raw_input, "ok", duration_ms)

    # SDK 2.x derives structured_content from the return value.
    return success.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(mcp: Any, client: RestApiClient | None = None, logger: Any = None) -> None:
    """Attach ``list_pets`` to the given MCPServer instance.

    The tool signature uses **flat keyword arguments** (not a single
    ``BaseModel`` parameter) so the SDK's auto-generated JSON Schema exposes
    each filter/sort/pagination field directly under ``arguments`` — clients
    call ``{"arguments": {"species": "犬", "page": 1}}`` rather than the
    nested ``{"arguments": {"input": {...}}}`` shape. Validation is still
    done through :class:`ListPetsInput` inside the handler.
    """

    description = (
        "查询宠物医院档案列表，对应 Go REST API 的 GET /api/v1/pets。\n\n"
        "支持按种类/状态/医生/疾病等过滤，按多种字段升/降序排序，并分页返回。\n"
        "适用场景：AI 助手为前台/医生/运营人员查询档案、做客户回访、生成报表等。\n\n"
        "返回 data：items(档案数组)、total、page、pageSize、totalPages、totalCost。"
    )

    @mcp.tool(name=TOOL_NAME, description=description)
    async def _list_pets(
        q: str | None = None,
        name: str | None = None,
        ownerName: str | None = None,
        ownerPhone: str | None = None,
        species: str | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: str | None = None,
        min: float | None = None,  # noqa: A002 — name dictated by the Go API
        max: float | None = None,  # noqa: A002
        sortBy: str | None = None,
        order: str | None = None,
        page: int = 1,
        pageSize: int = 20,
    ) -> dict[str, Any]:
        raw_input: dict[str, Any] = {
            "q": q, "name": name, "ownerName": ownerName, "ownerPhone": ownerPhone,
            "species": species, "doctor": doctor, "disease": disease, "status": status,
            "min": min, "max": max, "sortBy": sortBy, "order": order,
            "page": page, "pageSize": pageSize,
        }
        raw_input = {k: v for k, v in raw_input.items() if v is not None}
        return await handle_list_pets(raw_input, client=client, logger=logger)
