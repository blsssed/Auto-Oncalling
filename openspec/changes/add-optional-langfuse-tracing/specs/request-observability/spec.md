## ADDED Requirements

### Requirement: 可选的 Langfuse 追踪配置

系统 SHALL 支持通过项目配置的可选 `langfuse` 段（`enabled`/`publicKey`/`secretKey`/`host`）启用 LLM 链路追踪。配置 MUST 只从本地 JSON 配置加载，MUST NOT 读取环境变量作为配置源。

#### Scenario: 配置段缺失或未启用

- **WHEN** `langfuse` 段缺失或 `enabled=false`
- **THEN** 后端 MUST 静默禁用追踪——不导入、不连接 langfuse SDK，不向任何 LLM 调用传递 callbacks，聊天与诊断行为 MUST 与未引入该能力前一致

#### Scenario: 启用但缺少凭据

- **WHEN** `enabled=true` 且 `publicKey` 或 `secretKey` 为空或非法
- **THEN** 后端 MUST 抛出项目配置错误，MUST NOT 创建追踪 provider，且错误信息 MUST NOT 包含任何配置值

#### Scenario: 配置检查报告追踪段

- **WHEN** 客户端请求 `GET /config/check`
- **THEN** 响应的 configuration MUST 包含 `langfuse` 段（禁用或未配置时 `valid=true`），MUST NOT 序列化 `publicKey`/`secretKey`；`/ready` 的四个必需组件（sqlite/milvus/llm/mcp）MUST 不受追踪配置影响

### Requirement: 聊天与 AIOps 执行的追踪上报

系统 SHALL 在追踪启用时，为聊天 Agent 流、AIOps 诊断流与聊天记忆压缩调用创建 Langfuse trace：trace 名分别为 `chat-agent`、`aiops-diagnosis`、`chat-memory-compaction`，`sessionId` 分别为聊天会话 id、诊断任务 id、聊天会话 id，`userId` MUST 使用 `owner_user_id`，`metadata` MUST 携带当前 requestId。SSE 事件契约、顺序与终止语义 MUST 不变。

#### Scenario: 聊天 Agent 运行

- **WHEN** 追踪启用且一次聊天消息流开始
- **THEN** 聊天 Agent 的执行 MUST 携带绑定该 trace 的回调 handler，Agent 的 LLM 调用与工具调用（含 MCP 工具）MUST 记录在该 trace 的耗时树中

#### Scenario: AIOps 诊断运行

- **WHEN** 追踪启用且诊断任务执行（含后台 durable job 路径）
- **THEN** LangGraph 图执行 MUST 携带绑定 `aiops-diagnosis` trace 的回调 handler，节点内的 planner/replanner/report LLM 调用 MUST 进入同一 trace

#### Scenario: 记忆压缩调用

- **WHEN** 追踪启用且聊天记忆触发压缩
- **THEN** 该 LLM 调用 MUST 显式携带绑定 `chat-memory-compaction` trace 的回调 handler

### Requirement: 追踪故障不影响业务流

系统 SHALL 保证追踪链路的任何故障不影响聊天流、诊断流与任务终态。

#### Scenario: SDK 或网络错误

- **WHEN** langfuse SDK 导入、客户端构造或上报抛出异常
- **THEN** 回调 provider MUST 降级为不提供 handler，聊天流、诊断图执行与任务终态 MUST 不受影响，错误 MUST NOT 传播到 SSE 或诊断事件流

#### Scenario: 流或任务结束

- **WHEN** 一次聊天流、诊断流或记忆压缩调用结束（含失败路径）
- **THEN** 后端 MUST best-effort flush 追踪数据，且 flush 异常 MUST NOT 传播到调用方
