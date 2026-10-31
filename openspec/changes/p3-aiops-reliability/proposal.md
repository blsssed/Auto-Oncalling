## Why

P2 实机闭环暴露了四个相互独立但都影响可靠性的问题：

1. 单个 `llm` 配置同时驱动聊天、Embedding 与 Rerank。DeepSeek 聊天接口不提供 Embedding，导致知识检索、文档索引与 rerank 整体降级。
2. `AiOpsDiagnosticService` 构建失败（例如日志源配置缺失）时，后台任务失败，但诊断任务永远停留在 `accepted`，前端显示“排队中”。
3. `FileLogStore` 只是 JSON 数组 fixture 读取器：忽略 planner 的 `Query`，不支持 JSONL、目录/轮转和有界读取。
4. planner 直接输出 CLS CQL，日志查询语义与具体日志源耦合，无法平滑增加第二个 adapter。

本变更按上述顺序修复，不新增第二日志源，也不改变 HTTP/SSE 契约。

## 什么更改

- `llm` 下新增可选的 `embedding` / `rerank` 节，逐字段回退到顶层聊天配置；聊天、向量和精排可以使用不同供应商。
- 诊断 runner 构建失败时，把仍处于非终态的任务写为 `failed`，记录完成时间与脱敏错误，同时继续抛出异常以保留后台任务失败/重试语义。
- `FileLogStore` 支持 JSONL 与 JSON 数组、单文件/目录/glob、目录按 mtime 倒序、`maxBytes` 尾部有界读取、`maxRecords` 上限、坏行计数与 `time` 时间归一化。
- 新增 provider-neutral `LogQuery`：planner 使用 `service`、`incidentId`、`traceId`、`level`、`text`、`from`、`to`、`limit`；CLS adapter 翻译为 `SearchLog` 参数，本地 adapter 直接过滤。旧 `Query` 仍可解析。
- planner/replanner prompt 明确结构化字段，并禁止 CLS CQL、管道、括号、`OR`/`NOT`。
- 配置模板与后端 README 同步新增字段和安全默认值，模板凭据保持为空。

## 功能

### 新功能

无。

### 修改后的功能

- `qwen-openai-provider`：新增独立 Embedding/Rerank 供应商配置与回退规则。
- `aiops-diagnosis-tasks`：新增 runner 构建失败终态、结构化日志查询与本地日志源要求。
- `shared-user-project-configuration`：新增可选 `llm.embedding`、`llm.rerank` 与 `logStore` 读取限制字段。

## 影响

- 后端配置加载、LLM provider 工厂、AIOps job handler、诊断 planner 与日志 adapter。
- `config/project.template.json`（新增安全默认值）与后端 README。
- 后端测试：配置回退、runner 构建失败、日志查询模型、本地 JSONL/目录/glob/有界读取。
- 不涉及数据库 schema、HTTP 路径、SSE 事件字段或共享 TypeScript 契约。
