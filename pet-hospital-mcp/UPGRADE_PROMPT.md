# Stage 2 — Upgrade Prompt

> 本文件仅作为后续阶段扩展时的提示词模板。Stage 1 已交付，**未实现** 阶段二。

请在现有 `pet_hospital_mcp/` 目录下扩展 MCP 服务，新增以下工具（每个工具一个
`tools/<name>.py` 模块），复用已有的 `rest_client.py` / `errors.py` /
`logging_config.py`：

1. `get_pet` — `GET /api/v1/pets/{id}`
2. `create_pet` — `POST /api/v1/pets`
3. `update_pet` — `PUT /api/v1/pets/{id}`
4. `patch_pet` — `PATCH /api/v1/pets/{id}`
5. `delete_pet` — `DELETE /api/v1/pets/{id}`
6. `search_pets` — `GET /api/v1/pets/search`
7. `list_records` — `GET /api/v1/pets/{id}/records`
8. `add_record` — `POST /api/v1/pets/{id}/records`
9. `list_charges` — `GET /api/v1/pets/{id}/charges`
10. `add_charge` — `POST /api/v1/pets/{id}/charges`
11. `hospital_stats` — `GET /api/v1/stats`
12. `meta` — `GET /api/v1/meta`

要求（与 Stage 1 一致）：

- 沿用 `mcp==2.0.0` + `MCPServer` + 协议 `2026-07-28` + 无状态 Streamable HTTP；
- 每个工具的输入/成功/错误输出用 Pydantic 建模；
- 所有错误走统一 `ToolError`/`MCPErrorPayload` 通道，错误码集合可在 `errors.py`
  扩充（如 `NOT_FOUND`、`CONFLICT`）；
- 敏感字段（`ownerPhone`、`ownerAddr`、`chipNo` 及 snake_case 变体）日志脱敏；
- 测试沿用 `httpx.MockTransport`/`respx`，禁止访问真实 Go 服务；
- 工具描述必须说明用途、参数、适用场景、返回值。
