## ADDED Requirements

### Requirement: Diagnostic task reaches a terminal state when runner setup fails

AIOps 诊断 SHALL 在诊断 runner 无法构建时把仍处于非终态的任务写为 `failed`，并保留后台任务的失败/重试语义。

#### Scenario: Runner construction fails

- **WHEN** 后台 `aiops_diagnosis` job 构建 `AiOpsDiagnosticService` 时抛出配置错误
- **THEN** 任务状态 MUST 从 `accepted`/`running` 变为 `failed`，`completed_at` MUST 非空，结果负载 MUST 包含脱敏后的失败原因

#### Scenario: Error payload is sanitized

- **WHEN** 构建异常消息包含 API key、token、密码或云凭据
- **THEN** 持久化的错误 MUST NOT 包含这些敏感值

#### Scenario: Task already reached a terminal state

- **WHEN** runner 已把任务写为 `failed`、`succeeded` 或 `cancelled` 后发生异常
- **THEN** handler MUST NOT 用通用失败消息覆盖已有的终态与更具体的失败原因

#### Scenario: Background job still fails

- **WHEN** runner 构建失败且任务已写为 `failed`
- **THEN** handler MUST 继续抛出异常，让 durable job runtime 记录失败或重试

### Requirement: Provider-neutral log query arguments

AIOps planner SHALL 使用与日志供应商无关的结构化参数查询日志，adapter 负责翻译为具体日志源的原生查询。

#### Scenario: Planner emits structured log arguments

- **WHEN** Planner 或 Replanner 生成 `SearchLog` 步骤
- **THEN** 参数 MUST 使用 `service`、`incidentId`、`traceId`、`level`、`text`、`from`、`to`、`limit`，且 MUST NOT 要求模型输出 CLS CQL、管道、括号、`OR` 或 `NOT`

#### Scenario: Scope is mandatory

- **WHEN** 查询参数中的 service、incident ID 或 trace ID 与任务 scope 冲突，或 scope 缺少全部定位字段
- **THEN** 查询 MUST 失败并且 MUST NOT 扩大日志检索范围

#### Scenario: CLS adapter translates arguments

- **WHEN** 日志源为 CLS
- **THEN** adapter MUST 把中性参数翻译为 `SearchLog` 的 `Region`、`TopicId`、`From`、`To`、`Query` 和 `Limit`，并把 `text` 渲染为 `message:"..."`

#### Scenario: Legacy query remains readable

- **WHEN** 历史计划只提供 CQL 风格 `Query`
- **THEN** CLS adapter MUST 继续解析或以原有 scope 包裹方式执行，本地 adapter MUST 对不支持的语法明确失败

#### Scenario: Time and limit are bounded

- **WHEN** 查询提供 `from`、`to` 或 `limit`
- **THEN** 时间 MUST 与任务范围取交集且无交集时失败，`limit` MUST 被限制在 1–100

### Requirement: Bounded local log evidence source

本地 `FileLogStore` SHALL 从配置路径读取 JSONL 或 JSON 数组日志，并在有限内存与有限延迟内返回作用域过滤后的证据。

#### Scenario: Directory or glob contains rotated files

- **WHEN** `filePath` 指向目录或 glob
- **THEN** store MUST 读取匹配的 `*.jsonl`、`*.ndjson`、`*.json`、`*.log` 和 `*.log.*` 文件，并按 mtime 倒序处理

#### Scenario: Large JSONL file is read from the tail

- **WHEN** JSONL 文件大于 `maxBytes`
- **THEN** store MUST 只读取文件末尾 `maxBytes`，丢弃可能不完整的第一行，并 MUST NOT 把整个文件载入内存

#### Scenario: JSON array file exceeds the limit

- **WHEN** JSON 数组文件大于 `maxBytes`
- **THEN** store MUST 失败并提示改用 JSONL

#### Scenario: Records are bounded and sanitized

- **WHEN** 文件包含超过 `maxRecords` 条记录、坏行或敏感字段
- **THEN** store MUST 限制解析总数、跳过坏行并计入排除数，且结果 MUST 继续经过作用域过滤、字段白名单和脱敏

#### Scenario: Record time is not ISO formatted

- **WHEN** 记录只包含 `time` 字段，值为 ISO 字符串、epoch 秒或 epoch 毫秒
- **THEN** store MUST 将其归一化为 `timestamp` 后再应用时间范围过滤

#### Scenario: Local query uses unsupported syntax

- **WHEN** 本地查询包含管道、括号、`OR`、`NOT`、未知字段或裸关键词
- **THEN** store MUST 返回清晰的 `ValueError`，MUST NOT 静默忽略条件或扩大结果集
