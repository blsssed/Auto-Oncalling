## Why

实机验证暴露了一类共同问题：聊天流中的多个非核心依赖失败时，会把整条流打成 `SYSTEM_INTERNAL_ERROR`，用户只看到「系统暂时无法完成该请求」：

1. CLS MCP Server 未启动时，`discover_tools()` 抛出连接拒绝异常，直接终止整条聊天流——用户连纯对话都不可用。
2. `_maybe_generate_chat_title`（标题生成）没有独立异常处理，LLM 抖动会让已正常完成的回答以错误结尾。
3. 助手回答已完整流出后，`refresh_usage` 与助手消息落库仍在主 `try` 内，回答之后的失败把整条流标记为错误。
4. `_persist_tool_call_audit` 在主 `try` 内逐调用执行，单条审计写入失败会中止回答。
5. `prepare_message` 只处理上下文超限；记忆仓储的其他故障同样会让流失败。
6. 另一条独立问题：SQLite 引擎未启用 WAL/busy_timeout，后台任务与 HTTP 请求并发写入时出现 `database is locked`，登录等无关功能随之 500。

共性根因是「可选依赖的故障与核心链路耦合」+「失败信息不具体」。本变更消除这些耦合，并让降级/失败都有用户可读的中文提示。

## 什么更改

- 共享契约新增 SSE 事件类型 `notice`（channel `chat`），负载为 `{ code, message }`，`code` 取自错误目录；错误目录新增 `CHAT_MCP_TOOLS_UNAVAILABLE` 与 `CHAT_MEMORY_UNAVAILABLE`。
- 聊天 runner 在 MCP 工具发现失败时记录脱敏日志、发送 `notice` 事件，并继续执行不加载 MCP 工具的对话；LLM 本身失败仍然按原语义报错。
- `_maybe_generate_chat_title` 变为尽力而为：失败仅记录日志，不影响流。
- 助手回答完整流出后，助手消息落库、用量刷新、标题生成均为尽力而为；失败记录日志并正常发送 `complete`，不再发送 `error`。
- 单条工具调用审计写入失败只跳过该条并记录日志，不中止回答。
- `prepare_message` 在非上下文超限故障时降级为「仅使用当前消息」，发送 `CHAT_MEMORY_UNAVAILABLE` 通知后继续执行。
- 前端 chat store 处理 `notice` 事件：以非阻断警告（feedback store）展示中文提示，流继续；`userFacingError` 为两个新错误码补中文映射。
- SQLite 记忆库引擎启用 WAL、`busy_timeout` 与 `synchronous=NORMAL`，消除并发 `database is locked`。

## 功能

### 新功能

- `api-and-sse-contracts`：SSE `notice` 事件契约与两个新错误码。
- `chat-experience`：聊天流可选依赖降级与明确提示。
- `memory-repositories`：SQLite 并发韧性（WAL/busy_timeout）。

### 修改后的功能

无既有 Requirement 的语义修改；本变更只新增 Requirement。

## 影响

- `packages/api-contracts`（`sse.ts`、`errors.ts`）与其契约测试；前后端同步更新。
- 后端 `super_ai/chat/streaming.py`、`super_ai/memory/database.py` 及对应 pytest。
- 前端 `src/stores/chat.ts`、`src/ui/userFacingError.ts` 及对应 Vitest。
- 不涉及数据库 schema 变更（无新 Alembic revision，PRAGMA 为运行时设置）、不改变现有 SSE 事件的字段与顺序、不新增 HTTP 路径。
