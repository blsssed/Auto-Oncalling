## ADDED Requirements

### Requirement: Optional dependency degrade in chat streaming

聊天流 SHALL 把可选依赖的故障与核心对话链路解耦：MCP 工具源、会话标题生成、工具调用审计、回答后的落库与用量刷新失败时，流 MUST NOT 以 `error` 结束；真正影响回答生成的故障（如 LLM 本身不可用）仍按原 `error` 语义报错。

#### Scenario: MCP tool source unavailable

- **WHEN** 聊天流执行 MCP 工具发现失败（如 CLS MCP Server 未启动）
- **THEN** runner MUST 记录脱敏日志、发送一条 `notice`（`CHAT_MCP_TOOLS_UNAVAILABLE`，含中文提示），并继续执行不加载 MCP 工具的对话；MUST NOT 发送 `error` 终止流

#### Scenario: Title generation fails

- **WHEN** 回答完成后生成会话标题失败
- **THEN** 失败 MUST 仅记录日志，流 MUST 正常以 `complete` 结束，MUST NOT 产生 `error` 或用户可见错误

#### Scenario: Post-answer persistence fails

- **WHEN** 助手回答已完整流出后，助手消息落库或用量刷新失败
- **THEN** 失败 MUST 记录日志，流 MUST 正常以 `complete` 结束，MUST NOT 发送 `error`

#### Scenario: Tool call audit write fails

- **WHEN** 单条工具调用审计写入失败
- **THEN** runner MUST 跳过该条审计并记录日志，回答 MUST 继续

#### Scenario: Memory preparation fails without context limit

- **WHEN** `prepare_message` 因上下文超限以外的故障失败
- **THEN** runner MUST 发送一条 `notice`（`CHAT_MEMORY_UNAVAILABLE`，含中文提示），以仅含当前消息的上下文继续执行，MUST NOT 发送 `error`

#### Scenario: LLM itself fails

- **WHEN** 回答生成期间 LLM 调用失败
- **THEN** 流 MUST 按原语义发送 `error` 并终止，MUST NOT 用降级掩盖核心链路故障

#### Scenario: Errors are sanitized

- **WHEN** 任一降级路径记录日志
- **THEN** 日志与提示 MUST NOT 包含 API key、token、密码或云凭据

### Requirement: Frontend notice presentation

前端 chat store SHALL 以非阻断方式展示 `notice` 事件：中文提示通过全局反馈呈现，流继续；错误目录新码 SHALL 有中文映射。

#### Scenario: Notice arrives during streaming

- **WHEN** 聊天流收到 `notice` 事件
- **THEN** 前端 MUST 展示对应中文提示，MUST NOT 清空乐观消息或中止消费后续事件

#### Scenario: Notice codes map to Chinese text

- **WHEN** 提示码为 `CHAT_MCP_TOOLS_UNAVAILABLE` 或 `CHAT_MEMORY_UNAVAILABLE`
- **THEN** 展示文本 MUST 为对应用户可读中文，MUST NOT 原样展示英文目录消息
