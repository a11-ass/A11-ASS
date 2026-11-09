# Pet Hospital MCP

Stage 1 — wraps the Go pet hospital REST API as an MCP service, exposing a
single tool ``list_pets`` that proxies ``GET /api/v1/pets``.

## 技术栈

| 项 | 值 |
|---|---|
| Python | 3.11+ |
| MCP SDK | 官方 Python SDK **`mcp==2.0.0`** |
| 协议版本 | **`2026-07-28`** |
| Server 类 | **`MCPServer`**（不使用 1.x 的 `FastMCP`） |
| Transport | 无状态 Streamable HTTP（无 `initialize`、无 `Mcp-Session-Id`、无会话存储） |
| HTTP 框架 | Starlette + uvicorn（SDK 提供 `streamable_http_app()`） |
| 校验 | Pydantic v2 |
| HTTP 客户端 | httpx |
| 日志 | structlog（JSON，含 `timestamp`/`tool_name`/`params`/`status`/`duration_ms`，敏感字段递归脱敏） |
| 测试 | pytest + pytest-asyncio + httpx.MockTransport |

## 前置依赖

1. **Go 宠物医院后端必须先启动**，默认监听 `http://127.0.0.1:8080`。
   启动方式见 [`pet-hospital-mcp-teaching-main`](../pet-hospital-mcp-teaching-main)：
   ```powershell
   cd D:\学校用的\大模型\ai项目\pet-hospital-mcp-teaching-main\pet-hospital-mcp-teaching-main
   go run . -seed
   ```
2. Python 3.11+（开发环境使用 3.13.9）。

## 安装

```bash
cd D:\学校用的\大模型\自创mcp\pet_hospital_mcp
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | MCP 监听地址 |
| `MCP_PORT` | `8100` | MCP 监听端口 |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go REST API 地址 |
| `BACKEND_TIMEOUT_SECONDS` | `5` | 后端 HTTP 超时 |
| `BACKEND_RETRIES` | `2` | 重试次数（5xx/网络错误） |
| `BACKEND_BACKOFF_SECONDS` | `0.2` | 重试退避基数 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## 启动

```bash
# 1. 先启动 Go 后端（另一个终端）
cd D:\学校用的\大模型\ai项目\pet-hospital-mcp-teaching-main\pet-hospital-mcp-teaching-main
$env:GOROOT = 'D:\学校用的\大模型\ai项目\go'
$env:PATH  = "$env:GOROOT\bin;$env:PATH"
go run . -seed

# 2. 再启动 MCP 服务
cd D:\学校用的\大模型\自创mcp\pet_hospital_mcp
.venv\Scripts\activate
python -m pet_hospital_mcp
# 或: pet-hospital-mcp
```

服务起来后：
- MCP HTTP 端点：`http://127.0.0.1:8100/mcp`
- 健康检查：`http://127.0.0.1:8100/health`

## 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/mcp` | MCP JSON-RPC 端点（`tools/list`、`tools/call`、`server/discover`） |
| GET  | `/health` | 健康检查（未鉴权，供容器探针用） |

## 验证

### 1. `/health`

```bash
curl -s http://127.0.0.1:8100/health
```

预期输出（示例）：
```json
{"status":"healthy","service":"pet-hospital-mcp","sdk_version":"2.0.0","protocol_version":"2026-07-28","backend":"http://127.0.0.1:8080"}
```

### 2. 无状态 MCP 连接流程（SDK 2.x / 2026-07-28）

```bash
# server/discover — 不发送旧 initialize
curl -s -X POST http://127.0.0.1:8100/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{}}'

# tools/list
curl -s -X POST http://127.0.0.1:8100/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

**断言**：响应中**不出现** `Mcp-Session-Id` 响应头；请求中**不发送** `initialize`。

### 3. 调用 `list_pets`

```bash
# 不带任何过滤 — 返回第一页
curl -s -X POST http://127.0.0.1:8100/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_pets","arguments":{}}}'

# 带过滤、排序、分页
curl -s -X POST http://127.0.0.1:8100/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"list_pets","arguments":{"species":"犬","status":"已康复","sortBy":"totalCost","order":"desc","page":1,"pageSize":10}}}'
```

预期 `result.content[0].text` 是一个 JSON 字符串，反序列化后形如：
```json
{
  "items": [...],
  "total": 3,
  "page": 1,
  "pageSize": 10,
  "totalPages": 1,
  "totalCost": 12345.00
}
```

### 4. MCP Inspector

```bash
npx @modelcontextprotocol/inspector http://127.0.0.1:8100/mcp
```

## 单元测试

```bash
cd D:\学校用的\大模型\自创mcp\pet_hospital_mcp
.venv\Scripts\activate
pytest -q
```

预期：全部测试通过，且**不访问真实的 Go 服务**（所有 HTTP 通过 `httpx.MockTransport` 注入）。

覆盖范围：
1. 正常调用：所有过滤/排序/分页参数正确转发；
2. 输入校验失败（无效枚举、page<1、pageSize 越界、min>max、未知字段、NaN/Infinity）；
3. 后端 4xx/5xx；
4. 超时与连接异常；
5. 非法 JSON / schema 不匹配；
6. 工具注册（名称、JSON Schema、annotations）；
7. 无状态连接流程（无 `initialize`、无 `Mcp-Session-Id`、`/health` 可访问）。

## 目录结构

```text
pet_hospital_mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py
│       ├── __main__.py        # CLI 入口 (uvicorn)
│       ├── config.py          # 环境变量 → Settings
│       ├── server.py          # create_server / create_app
│       ├── rest_client.py     # httpx 包装：超时、重试、错误转换
│       ├── errors.py          # ErrorCode / ToolError / MCPErrorPayload
│       ├── logging_config.py  # structlog + 敏感字段递归脱敏
│       └── tools/
│           ├── __init__.py
│           └── list_pets.py   # 唯一工具
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_list_pets.py
    └── test_server.py
```

后续阶段新增工具时，只需在 `tools/` 下增加模块并复用 `rest_client.py` / `logging_config.py` / `errors.py`。

## 阶段范围声明

**Stage 1 仅实现 `list_pets` 一个工具。** 阶段二（病历、消费、统计等）的工具**未实现**。
