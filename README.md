# A11-ASS

课程项目作品集 —— 定制 Agent（prist）、宠物医院 MCP、AnythingLLM MCP 与文档上传网页。

## 目录说明

| 目录/文件 | 说明 |
|---|---|
| `prist/` | 定制 Agent 包：主循环、工具注册、Skill 系统、MCP 客户端、上下文压缩 |
| `main.py` | prist 入口（加载 config.ini → Skill 扫描 → AGENTS.md 注入 → TUI 启动） |
| `config.ini` | Agent 运行配置（不入库，首次运行由模板自动生成） |
| `.mcp.json` | MCP Server 连接配置（不入库） |
| `.agents/skills/` | Skill 库（SKILL.md + 资源文件，启动时仅注入名称与描述） |
| `pet-hospital-server/` | 宠物医院后端（Go，REST API，课程提供模板基础上运行） |
| `pet-hospital-mcp/` | 宠物医院 MCP Server（Python，MCP 2026-07-28 协议） |
| `anythingllm-mcp/` | AnythingLLM MCP Server（Python，工作区/对话/文档上传 3 个工具） |
| `upload.html` | AnythingLLM 文档上传 + 向量化网页（API Key 页面输入，不硬编码） |
| `AgentPractice01/` | 练习一：架构图（Mermaid） |
| `Agent/` | 练习二材料 |
| `tests/` | 自测与诊断脚本（上下文压缩、Token 估算等） |

## 技术栈

- Python 3.13 + Textual —— prist Agent（TUI 交互界面）
- Python + MCP SDK 2.0 —— 两个 MCP Server（Streamable HTTP 无状态）
- Go —— 宠物医院 REST API 后端
- HTML/JS —— AnythingLLM 文档上传前端

## 启动顺序

1. `pet-hospital-server/`：Go 后端先启动（见该目录 README）
2. `pet-hospital-mcp/`：`python -m pet_hospital_mcp`（默认 `:8100`）
3. `anythingllm-mcp/`：AnythingLLM 桌面端运行中 → `python -m anythingllm_mcp`（默认 `:8101`）
4. `upload.html`：浏览器直接打开，填入 AnythingLLM 地址与 API Key 即可上传
5. `prist`：`python main.py`（首次运行自动生成 `config.ini`，填入 LLM 的 `api_key` 后重启）

## prist Agent 能力速览

- **主循环多轮闭环**：模型 tool_calls → 本地执行 → 结果回填 → 再次请求，直到模型给出最终回答；`max_tool_steps`（默认 12）防死循环
- **22+ 工具**：日期/闰年、文件与目录全操作（10 类语义）、CLI、网页抓取（trafilatura 正文提取）、搜索（百度千帆）、Office 文档生成、Skill 加载/创建、上下文检索
- **Skill 系统**：`createSkill` 落盘（frontmatter 强校验）、`loadSkill` 按需读取（目录内路径限制 + 64KB 上限）、启动扫描仅注入名称与描述
- **MCP 客户端**：stdio + Streamable HTTP 双传输，工具名加 server 前缀，异步连接失败降级不阻塞
- **上下文管理**：Token 估算（中文 len//2）、80% 阈值自动压缩（JSONL 归档 + LLM 摘要）、`recallContext` 关键词检索归档
- **AGENTS.md 注入**：启动时读取工作目录/项目根的指令文件注入系统提示（文件名可在 `config.ini [app] agents_md_name` 配置）

## 安全说明

- 文件工具路径白名单：仅允许项目根目录、当前工作目录及 `config.ini [app] file_allowed_roots` 配置的额外目录，越界一律拒绝
- `config.ini` / `.mcp.json` / `.agents/context/*.jsonl` 已由 `.gitignore` 排除，真实密钥不入库
- `upload.html` 的 API Key 由用户在页面输入，前端代码无任何硬编码密钥

## 测试

- `pet-hospital-mcp/tests/`：pytest + httpx.MockTransport，覆盖参数校验、后端异常、超时
- `tests/`：prist 上下文压缩与 Token 估算的自测脚本
