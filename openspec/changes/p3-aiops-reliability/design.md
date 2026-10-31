## Context

四个问题共享一个目标：让实机诊断在配置、任务状态和日志证据三个层面都可解释、可恢复。改动必须保持：

- 配置只来自 `config/project.json` + `config/user.project.json`；
- 模板中的密钥、CLS 凭据和密码为空；
- owner 作用域过滤不放松；
- 长任务继续使用 durable background job；
- HTTP/SSE 契约不变。

## Decisions

### 1. 独立 Embedding/Rerank 配置采用逐字段回退

`llm.embedding` 与 `llm.rerank` 是可选对象。字段为空或缺失时回退：

| 嵌套字段 | 回退目标 |
| --- | --- |
| `embedding.apiKey` | `llm.apiKey` |
| `embedding.baseUrl` | `llm.baseUrl` |
| `embedding.model` | `llm.embeddingModel` |
| `embedding.dimensions` | `llm.embeddingDimensions` |
| `rerank.apiKey` | `llm.apiKey` |
| `rerank.baseUrl` | `llm.rerankUrl` |
| `rerank.model` | `llm.rerankModel` |

理由：现有单 `llm` 配置必须完全兼容；逐字段回退允许只替换 API key 或 base URL。嵌套节不是对象、`dimensions` 非正整数时返回不含密钥的 `LlmConfigurationError`。

替代方案是要求三个完整配置节，但会破坏现有用户配置。未采用。

### 2. runner 构建失败写失败终态

`aiops_job_handler` 把 `_aiops_diagnostic_runner(...)` 构建放入独立 `try`。构建异常时：

- 重新读取任务，只有 `accepted`/`running` 才写 `failed`；
- 写 `completed_at` 与 `{"failure": "Diagnostic runner could not be initialized.", "error": <redacted 500 chars>}`；
- 继续抛出异常，让 `BackgroundJobRuntime` 记录 job failure/retry。

如果任务已经由 `stream` 写成 `failed`/`succeeded`/`cancelled`，不覆盖更具体的失败原因。

替代方案是在 handler 内吞掉异常并标记 job 成功，但会丢失后台任务的可观测性和重试语义。未采用。

### 3. 本地日志读取是“有界尾部读取”，不是通用日志引擎

`FileLogStore`：

- `filePath` 支持单文件、目录或 glob；目录读取 `*.jsonl`、`*.ndjson`、`*.json`、`*.log`、`*.log.*`，按 mtime 倒序、再按文件名排序。
- `format` 为 `auto`/`jsonl`/`json-array`。JSON 数组超过 `maxBytes` 时明确报错并提示改用 JSONL。
- JSONL 只读取文件末尾 `maxBytes`；若尾部从记录中间开始，丢弃第一条不完整行。
- `maxRecords` 限制跨文件解析总数。
- `time` 归一化为 `timestamp`：ISO 字符串、epoch 秒或毫秒。
- 坏行跳过并计入 `excludedRecordCount`。
- 结果仍经过 `scoped_records` 的作用域过滤、字段白名单和脱敏。

理由：本地优先场景需要有限内存和有限延迟，而不是完整日志检索。未采用递归目录扫描或索引文件，避免配置路径之外的读取。

### 4. `LogQuery` 是 adapter 边界，不是新的查询语言

`LogQuery` 冻结字段：

```text
service, incidentId, traceId, level, text, from, to, limit
```

- 结构化参数优先；没有结构化字段时解析旧 `Query`。
- scope 的 service/incident/trace 是强制过滤；结构化值与 scope 冲突时失败。
- 时间取 scope 与查询交集，无交集失败；`limit` 限制 1–100。
- 只接受白名单字段；未知结构化字段忽略，不拼接任意 CQL。
- `to_cls_arguments` 渲染 CLS `Region`/`TopicId`/`From`/`To`/`Query`/`Limit`；`text` 渲染为 `message:"..."`。
- `FileLogStore.matches` 本地精确匹配标识字段，`text` 大小写不敏感匹配 `message`/`event`/`exception`。

旧 `Query` 兼容分两层：

- 本地 adapter 使用严格子集：仅 `AND` 连接的 `field:value`，拒绝管道、括号、`OR`/`NOT`。
- CLS adapter 使用宽松模式：无法解析为子集时，在完成管道/控制字符/括号/引号安全校验后，按原样包裹到 scope 条件后，以兼容历史计划和外部调用。

替代方案是立即删除旧 `Query`，但会让历史任务和现有测试失效。未采用。

### 5. planner prompt 只描述中性字段

Planner 与 Replanner 明确要求：

- `SearchLog` 使用 `service`/`incidentId`/`traceId`/`level`/`text`/`from`/`to`/`limit`；
- `from`/`to` 是任务范围内的 epoch 毫秒；
- `text` 是普通关键词；
- 不输出 CLS CQL、管道、括号、`OR`/`NOT`。

计划步骤的 dict 形状不变，因此 SSE 与前端无需改动。

## Risks

- 真实 RAG 恢复仍依赖用户提供可用的 Embedding 供应商；本轮只验证配置加载与工厂注入。
- 宽松 CLS passthrough 保留了旧 CQL 能力；新增 adapter 必须使用严格模式或自行实现语义。
- 本地目录/glob 只读取配置路径；`maxBytes` 与 `maxRecords` 是硬限制。
- `openspec validate --all` 依赖 CLI，当前环境可能不可用。
