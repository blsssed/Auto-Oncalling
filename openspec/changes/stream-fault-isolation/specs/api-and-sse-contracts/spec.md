## ADDED Requirements

### Requirement: Chat notice SSE event

共享 SSE 契约 SHALL 提供 `notice` 事件（channel `chat`），用于在流内传递非致命的降级提示；`notice.code` SHALL 取自统一错误目录。

#### Scenario: Notice event is representable

- **WHEN** 后端在聊天流中报告一次可选依赖降级
- **THEN** 事件 MUST 使用 `type: "notice"`、`channel: "chat"`，负载 MUST 包含目录内错误码 `code` 与用户可读中文 `message`

#### Scenario: Notice does not terminate the stream

- **WHEN** 前端收到 `notice` 事件
- **THEN** 流 MUST 继续消费后续事件，最终仍以 `complete` 或（真正失败时的）`error` 结束

### Requirement: Chat MCP tool source degrade codes

错误目录 SHALL 提供 `CHAT_MCP_TOOLS_UNAVAILABLE` 与 `CHAT_MEMORY_UNAVAILABLE`（category `business`），并附带用户可读中文默认消息。

#### Scenario: Error codes exist in the catalog

- **WHEN** 前端或后端引用这两个错误码
- **THEN** 它们 MUST 在 `API_ERROR_CODES` 中存在，包含 `category`、`httpStatus` 与中文 `message`
