# 任务

## 1. 共享契约

- [x] `errors.ts` 新增 `CHAT_MCP_TOOLS_UNAVAILABLE`、`CHAT_MEMORY_UNAVAILABLE`（category `business`，中文 message）。
- [x] `sse.ts` 事件联合新增 `notice`（channel `chat`，负载 `{ code, message }`）。
- [x] 补充契约测试（新错误码存在、notice 事件可解析）。
- [x] 同步 OpenAPI 描述（如 SSE 事件清单有列举处）。

## 2. 后端聊天流降级

- [x] MCP 工具发现独立 `try`：失败记录脱敏日志、发送 `notice`（`CHAT_MCP_TOOLS_UNAVAILABLE`）后继续无 MCP 工具对话。
- [x] `_maybe_generate_chat_title` 尽力而为：失败仅记日志。
- [x] 回答完整流出后：助手消息落库、用量刷新、标题生成包独立 `try`，失败记日志并正常 `complete`，不再发 `error`。
- [x] `_persist_tool_call_audit` 逐调用隔离：单条失败跳过并记日志。
- [x] `prepare_message` 非上下文超限故障：发送 `notice`（`CHAT_MEMORY_UNAVAILABLE`）后以仅当前消息继续。
- [x] 日志不含敏感凭据（复用现有脱敏工具）。
- [x] pytest 覆盖上述每条降级路径与「LLM 失败仍报 error」回归。

## 3. 前端展示

- [x] chat store 处理 `notice` 事件：feedback 非阻断警告 + 流继续，不清理乐观消息。
- [x] `userFacingError.ts` 增加两个新码的中文映射。
- [x] Vitest 覆盖 notice 处理与错误映射。

## 4. SQLite 并发韧性

- [x] `create_memory_engine` 连接事件监听启用 `journal_mode=WAL`、`busy_timeout`、`synchronous=NORMAL`。
- [x] pytest 覆盖 pragma 应用。

## 5. 验证与收尾

- [x] `openspec validate --all`
- [x] 后端：`uv run ruff check .`、`uv run pyright`、`uv run pytest`
- [x] 前端：`npm run frontend:typecheck`、`npm run frontend:test`、`npm run frontend:build`
- [x] 契约：`npm run contracts:typecheck` 与 package 测试
