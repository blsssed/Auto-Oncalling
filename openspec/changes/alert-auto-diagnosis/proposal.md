# 告警自动诊断（开关控制）

## Why

当前活跃告警只能由操作员手动点击“诊断”才能进入 AIOps 流程，严重告警在无人值守时可能长时间得不到根因分析。告警轮询本身已经是 durable recurring job，具备自动触发诊断的基础，但需要明确的责任用户、级别过滤、去重与节流，避免误触发和诊断风暴。

## What Changes

- 新增 `aiopsAutoDiagnosis` 项目配置段（默认关闭）：`enabled`、`ownerEmail`、`severities`、`dedupeWindowSeconds`、`maxPerPoll`。
- `alert_poll` 每次成功后对比上一份快照，只为“新出现”且级别匹配的告警创建诊断任务，并通过现有 durable job runtime 执行。
- 按告警 id 在去重窗口内跳过重复诊断，并限制每轮最多创建数量。
- 活跃告警 REST 与 SSE 载荷增加可选的 `diagnosticId`、`diagnosisStatus`，按当前认证用户作用域返回。
- 前端告警列表展示自动诊断状态，并在诊断排队/执行期间禁用重复触发按钮。
- 自动诊断的任何失败都不会中断告警轮询链。

## Impact

- 配置：`config/project.template.json`、配置加载与校验、运维文档。
- 后端：AIOps 自动诊断策略、告警轮询 handler、告警载荷与 SSE 事件。
- 共享契约：`ActiveAlert` 类型与 OpenAPI schema。
- 前端：告警列表状态展示与按钮状态。
