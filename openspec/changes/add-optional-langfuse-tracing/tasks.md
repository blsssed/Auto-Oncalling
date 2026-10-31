# 任务

## 实现

- [x] `apps/backend` 执行 `uv add langfuse`，验证安装版本的 `Langfuse`/`CallbackHandler` 构造签名（凭据经构造参数显式传入，不读环境变量）。
- [x] 新增 `super_ai/tracing.py`：`TracingSettings`、`load_tracing_settings`（缺失/禁用 → None；启用缺凭据 → ProjectConfigurationError 且文案不含值）、`TracingCallbackProvider` Protocol、`LangfuseTracingProvider`（懒导入、懒建共享客户端、`handler_for` 异常返回 None、`flush` 吞异常）。
- [x] `super_ai/llm/provider.py`：`ChatModel` 与 `StructuredOutputRunnable` 的 `ainvoke` 增加 `config: Mapping[str, object] | None = None`。
- [x] `super_ai/observability.py`：新增 `current_request_id()` 访问器。
- [x] `super_ai/chat/streaming.py`：`LangChainChatAgentRunner` 注入可选 `tracing_provider`，`astream_events` 在 handler 存在时携带 `config`，流结束 best-effort flush。
- [x] `super_ai/chat/memory.py`：`ChatMemoryService` 注入可选 `tracing_provider`，记忆压缩调用显式传 config 并 flush。
- [x] `super_ai/aiops/diagnostics.py`：`AiopsDiagnosticService` 注入可选 `tracing_provider`，`graph.astream` 携带 config（节点内直调不改），流结束（含失败路径）best-effort flush。
- [x] `super_ai/api/app.py`：`_tracing_provider` 惰性 helper 并注入三个 runner/服务；`_configuration_check_payload` 新增 `langfuse` 段（禁用 valid=true；非法 valid=false；不序列化密钥）。
- [x] `config/project.template.json` 与 `config/user.project.template.json` 新增 `langfuse` 段（模板默认 `enabled: false`、密钥为空）。
- [x] `docs/operations-and-monitoring.md`：配置表新增 langfuse 字段行，补充查看 trace 与降级说明。

## 测试

- [x] 新增 `tests/test_tracing_config.py`：配置缺失/禁用/启用缺凭据（错误信息不含值）/完整配置/非 bool enabled 五种语义。
- [x] 扩展 `tests/test_environment_examples.py`：断言两份模板 langfuse 密钥为空且 `enabled is False`。
- [x] 新增 `tests/test_tracing_provider.py`：禁用返回 None；handler 携带 session_id/user_id/trace_name；SDK 异常降级为 None；flush 永不抛（含未建客户端时）。
- [x] 聊天 runner 测试：注入 fake provider，断言 `astream_events` 收到/不收到 `config`；`handler_for` 抛异常时流仍正常。
- [x] 记忆压缩测试：fake chat model 捕获 `config` kwarg，断言显式传/不传两种行为。
- [x] 诊断服务测试：fake graph 捕获 `astream` kwargs，断言 callbacks/metadata 与 `session_id=task.id`，流结束（含失败路径）flush 恰一次。
- [x] LangGraph 回调传播回归测试：真实小型 StateGraph + 记录型 handler，验证节点内 LLM 调用继承 `graph.astream` 的 callbacks（失败则回退显式传参）。
- [x] 扩展 `tests/test_readiness_api.py`：/config/check 三态（禁用 valid / 启用缺凭据 invalid 且整体 503 / 无段 valid），响应不含 publicKey；/ready 仍四组件。

## 验证

- [x] `cd apps/backend && uv run ruff check . && uv run pyright && uv run pytest`
- [x] `openspec validate --all`
- [x] `npm run docs:build`
- [x] 实测（用户提供 Langfuse 云密钥写入本地 user.project.json 后）：一次聊天 + 一次诊断在 Langfuse 控制台生成 `chat-agent` / `aiops-diagnosis` trace，metadata.requestId 与本地日志一致；`enabled=false` 后行为与本次变更前一致。
