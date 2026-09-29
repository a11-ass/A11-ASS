# AnythingLLM MCP Server (MVP)

把本机 AnythingLLM 的**第一个工作区**包装成 MCP 工具，向它提问并返回 AI 回答。

- 协议：MCP `2026-07-28`（Streamable HTTP，无状态）
- 传输：HTTP（非 stdio），端点 `POST http://127.0.0.1:8101/mcp`
- 唯一工具：`ask_first_workspace(message)` — 取第一个工作区 → 发消息 → 返回回答文本
- 语言：Python 3.10+

## 1. 前置条件

1. AnythingLLM 已在本机运行（默认 `http://localhost:3001`）
2. 在 AnythingLLM 里 **Settings → API Keys** 创建一个 API Key
3. 至少建一个 workspace（第一个会被自动使用）

## 2. 安装（一次性）

```powershell
cd D:\damoxwenjian
# 已附带 .venv；若不存在则创建：
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install mcp==2.0.0 httpx uvicorn
```

## 3. 配置 API Key

复制 `.env.example` 为 `.env`，填入 API Key：

```
ANYTHINGLLM_BASE_URL=http://localhost:3001
ANYTHINGLLM_API_KEY=你刚创建的key
MCP_PORT=8101
```

> 也可以不建 `.env`，直接在启动前用环境变量传入（见下）。

## 4. 启动 MCP 服务

**PowerShell**（前台）：

```powershell
cd D:\damoxwenjian
$env:PYTHONPATH = 'D:\damoxwenjian\src'
$env:ANYTHINGLLM_API_KEY = '你的key'
.\.venv\Scripts\python.exe -m anythingllm_mcp
```

**后台运行**：

```powershell
Start-Process -WindowStyle Hidden -FilePath 'D:\damoxwenjian\.venv\Scripts\python.exe' `
  -ArgumentList '-m','anythingllm_mcp' `
  -WorkingDirectory 'D:\damoxwenjian' `
  -Environment @{ PYTHONPATH='D:\damoxwenjian\src'; ANYTHINGLLM_API_KEY='你的key' }
```

启动后看到 uvicorn 的 `Uvicorn running on http://127.0.0.1:8101` 即成功。

**健康检查**：

```powershell
Invoke-WebRequest http://127.0.0.1:8101/health -UseBasicParsing
# {"status":"healthy","service":"anythingllm-mcp","protocol_version":"2026-07-28",...}
```

## 5. 停止 MCP 服务

**前台运行**：在终端按 `Ctrl+C`。

**后台运行**：按端口杀进程：

```powershell
Get-NetTCPConnection -LocalPort 8101 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

## 6. 项目级 MCP 配置

已写好 [.trae/mcp.json](./.trae/mcp.json)：

```json
{
  "mcpServers": {
    "anythingllm": {
      "url": "http://127.0.0.1:8101/mcp",
      "type": "streamable_http"
    }
  }
}
```

Trae CN 打开本项目时会自动加载这个配置。**先启动 MCP 服务，再让 Trae 连接**（否则连不上）。

## 7. 直接调用验证（不依赖客户端）

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:8101/mcp' -Method POST `
  -ContentType 'application/json' `
  -Headers @{ Accept='application/json, text/event-stream' } `
  -Body '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"ask_first_workspace","arguments":{"message":"你好"}}}'
```

## 8. 目录结构

```
D:\damoxwenjian\
├── pyproject.toml
├── README.md
├── .env.example
├── .trae\
│   └── mcp.json              # 项目级 MCP 配置
├── src\
│   └── anythingllm_mcp\
│       ├── __init__.py
│       ├── __main__.py       # uvicorn 入口
│       ├── config.py         # 环境变量 → Settings
│       └── server.py         # MCPServer + ask_first_workspace 工具
└── .venv\                    # 独立虚拟环境
```

## 9. 工具说明

| 工具 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `ask_first_workspace` | `message: string`（必填） | AI 回答文本 | 自动选第一个工作区并发问 |

流程：`GET /api/v1/workspaces` → 取 `workspaces[0].slug` → `POST /api/v1/workspace/{slug}/chat`（`{message, mode:"chat"}`）→ 返回 `textResponse`。

## 10. 常见问题

- **`403 Forbidden`**：API Key 错误或未设。检查 `ANYTHINGLLM_API_KEY` 环境变量。
- **`AnythingLLM has no workspaces`**：AnythingLLM 里还没建工作区，先去 UI 建一个。
- **Trae 连不上**：先确认 `http://127.0.0.1:8101/health` 能访问，再让 Trae 重连。
