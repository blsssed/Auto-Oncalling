# 可选 Langfuse 追踪接入

## Why

当前后端观测能力只有散点 JSON 日志（`durationMs`/`latencyMs`）、诊断报告内的 `llmUsage` 聚合和 `/metrics` 全局平均延迟，没有按调用链聚合的 trace 视图：要还原「一次诊断里 planner、每次 CLS 工具调用各花了多久」或「一次聊天里 agent 各轮 LLM 调用的耗时分布」，只能靠 requestId 手工串联单行日志。需要接入 Langfuse 云端追踪，把聊天链与 AIOps 诊断链的 LLM 调用、工具调用层级耗时树自动上报。

## What Changes

- 新增可选 `langfuse` 配置段（`enabled`/`publicKey`/`secretKey`/`host`）：缺失或 `enabled=false` 时静默禁用，不导入、不连接 langfuse；`enabled=true` 但凭据为空时抛 `ProjectConfigurationError`（不泄露值）。
- 新增 `super_ai/tracing.py`：`TracingCallbackProvider` Protocol + `LangfuseTracingProvider`（懒导入 SDK、懒建共享客户端、每请求 handler；SDK 任何异常降级为空 handler，永不影响业务流）。
- 聊天 Agent 流、AIOps 诊断图、聊天记忆压缩三处经 langchain `config={"callbacks": [...]}` 携带追踪 handler；trace 名分别为 `chat-agent`、`aiops-diagnosis`、`chat-memory-compaction`；`user_id` 使用 `owner_user_id`，`metadata.requestId` 与现有 JSON 日志互查。
- `/config/check` 新增 `langfuse` 段（禁用时 `valid=true`，不序列化密钥）；`/ready` 四个必需组件不变。
- `ChatModel`/`StructuredOutputRunnable` Protocol 的 `ainvoke` 增加 `config` 可选参数。
- 配置模板新增 `langfuse` 段（默认 `enabled: false`、密钥为空）；运维文档新增配置行与查看说明。

## Impact

- 后端：`super_ai/tracing.py`（新）、`super_ai/llm/provider.py`、`super_ai/observability.py`、`super_ai/chat/streaming.py`、`super_ai/chat/memory.py`、`super_ai/aiops/diagnostics.py`、`super_ai/api/app.py`、`tests/test_tracing_config.py`（新）、`tests/test_tracing_provider.py`（新）、既有模板/就绪/聊天/诊断测试扩展。
- 配置：`config/project.template.json`、`config/user.project.template.json`。
- 文档：`docs/operations-and-monitoring.md`、OpenSpec 主规格 `request-observability` 能力。
- 非目标：不改 SSE 事件契约；不加 compose 服务；不从环境变量读配置；不做文档 embedding 索引追踪；不引入 LangSmith。
