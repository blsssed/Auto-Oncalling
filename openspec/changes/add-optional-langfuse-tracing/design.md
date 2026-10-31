# 设计：可选 Langfuse 追踪接入

## 决策

### 1. 配置语义沿用 aiopsAutoDiagnosis 的可选模式

`langfuse` 段缺失或 `enabled=false` → `load_tracing_settings` 返回 `None`，功能静默关闭；`enabled=true` 但 `publicKey`/`secretKey` 为空 → 抛 `ProjectConfigurationError`（文案固定，不含配置值）；`host` 缺省用 `https://cloud.langfuse.com`。理由：与 `aiops/auto_diagnosis.py` 的既有语义一致，模板默认 `enabled: false` 保证新检出仓库行为不变、`/config/check` 保持绿色。

### 2. 懒导入与共享客户端

`tracing.py` 模块级不得 import langfuse（项目约定：模块导入不得建立外部连接）。`LangfuseTracingProvider` 在首次 `handler_for` 时懒导入 SDK 并构建一个共享 `Langfuse` 客户端（持有凭据、后台批量上报）；每个聊天流/诊断流/记忆压缩调用创建一个 `CallbackHandler`（Langfuse 的 trace 语义要求 handler 绑定 session/user/trace 元数据）。SDK 构造或导入抛异常 → `handler_for` 返回 `None`，调用方按无追踪继续。具体构造参数名以安装的 SDK 版本为准，实现时先验证签名。

### 3. 注入 provider 工厂而非 handler 实例

`LangChainChatAgentRunner` 与 `AiopsDiagnosticService` 是缓存于 `app.state` 的单例，`ChatMemoryService` 每请求构建；统一注入 `TracingCallbackProvider | None`，handler 在每次 `stream()`/压缩调用时创建。默认 `None` 时所有现有构造与测试不受影响。

### 4. 回调传递点与 LangGraph 上下文传播

- 聊天：`agent.astream_events(..., version="v2", config={"callbacks": [handler], ...})`（handler 存在时才传 `config`，否则与现状完全一致）。
- AIOps：`graph.astream(..., stream_mode="updates", config=...)`。节点内 6 处直调 `ainvoke`（planner/replanner/report 及其文本回退）**不显式传 config**：LangGraph 节点执行会设置 langchain-core 的子运行配置上下文，节点内调用继承 `graph.astream` 的 callbacks；双层传递存在同一 handler 重复注册风险。以真实小型 StateGraph + 记录型 handler 的回归测试为门禁，若传播失败则回退为 6 处显式传参。
- 记忆压缩（`chat/memory.py`）不在任何图内，必须显式传 `config`。
- `user_id` 使用 `owner_user_id`（不透传 email，避免 PII 扩面）；`metadata.requestId` 取自 `observability.current_request_id()`，与现有 JSON 日志互查。

### 5. flush 与故障隔离

每条流（含失败路径）结束时 best-effort `flush()`；`flush` 与 `handler_for` 内部吞掉所有异常。追踪的任何故障不得改变 SSE 事件顺序、诊断任务终态或错误文案。

### 6. 观测面收敛在 /config/check

`/config/check` 的 `configuration` 新增 `langfuse` 键：禁用时 `{"valid": true, "enabled": false}`；启用且配置完整时附 `host`；非法时 `valid=false`（与其他段一致参与整体 503）。共享契约中 `configuration` 为 `additionalProperties: true`，无需契约变更。`/ready` 的 sqlite/milvus/llm/mcp 四组件不变——追踪是可选旁路，不作为就绪门槛。

### 7. Protocol 放宽而非绕过

`ChatModel`/`StructuredOutputRunnable` 的 `ainvoke` 增加 `config: Mapping[str, object] | None = None`（与 `ChatOpenAI.ainvoke` 实际签名兼容），测试 fake 同步更新，不引入新的 `cast` 逃逸。

## 风险

- Langfuse SDK 版本差异：v3 的 `CallbackHandler`/`Langfuse` 构造参数名与 env 行为需在实现首步验证；凭据只经构造参数显式传入，不读环境变量。
- LangGraph 回调传播是设计假设：回归测试先行验证；失败回退显式传参。
- 严格 Pyright：Protocol 放宽波及测试 fakes 的 `ainvoke` 签名，需同步修改，不得放宽检查。
- 双层传参重复注册风险：按决策 4 单层传递规避。
