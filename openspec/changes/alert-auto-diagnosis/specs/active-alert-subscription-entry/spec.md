## ADDED Requirements

### Requirement: Configurable automatic diagnosis of newly active alerts

系统 SHALL 仅在 `aiopsAutoDiagnosis.enabled=true` 时，将新出现的、级别匹配的活跃告警自动转换为指定用户的 durable AIOps 诊断任务，并遵守去重窗口与每轮上限。

#### Scenario: 新严重告警出现

- **WHEN** 告警轮询成功，且某条 critical 告警不在上一份快照中，同时配置的 `ownerEmail` 对应已注册用户
- **THEN** 后端 MUST 为该用户创建一个 `accepted` 诊断任务并入队 `aiops_diagnosis` durable job，任务输入 MUST 保留告警 id、来源、服务、级别和原始上下文

#### Scenario: 级别未启用

- **WHEN** 新告警的级别不在 `aiopsAutoDiagnosis.severities` 中
- **THEN** 后端 MUST NOT 创建诊断任务

#### Scenario: 去重窗口内重复出现

- **WHEN** 同一告警 id 在 `dedupeWindowSeconds` 内已存在诊断任务
- **THEN** 后端 MUST NOT 再次创建诊断任务

#### Scenario: 每轮创建数量受限

- **WHEN** 一轮轮询中符合条件的新告警超过 `maxPerPoll`
- **THEN** 后端 MUST 最多创建 `maxPerPoll` 个诊断任务，并在后续轮询中继续处理其余告警

#### Scenario: 功能关闭或所属用户不存在

- **WHEN** 配置缺失、`enabled=false` 或 `ownerEmail` 未匹配任何用户
- **THEN** 后端 MUST NOT 创建诊断任务，且轮询 MUST 继续按计划调度

#### Scenario: 自动诊断失败

- **WHEN** 自动诊断创建或入队过程抛出错误
- **THEN** 后端 MUST 记录失败并继续入队下一次告警轮询，不得中断轮询链

### Requirement: Alert payloads expose scoped automatic diagnosis status

活跃告警载荷 SHALL 按当前认证用户附带其最近一次关联诊断的 `diagnosticId` 与 `diagnosisStatus`，且不得暴露其他用户的诊断归属。

#### Scenario: 当前用户存在关联诊断

- **WHEN** 已认证用户读取活跃告警或接收 `alerts.snapshot` SSE 事件，且其名下存在该告警 id 的诊断任务
- **THEN** 对应告警项 MUST 包含 `diagnosticId` 和 `diagnosisStatus`

#### Scenario: 其他用户查看同一告警

- **WHEN** 另一用户读取同一活跃告警
- **THEN** 载荷 MUST NOT 包含该告警的 `diagnosticId` 或 `diagnosisStatus`

#### Scenario: 诊断正在执行

- **WHEN** 前端收到 `accepted` 或 `running` 的 `diagnosisStatus`
- **THEN** 告警列表 MUST 展示自动诊断状态，并 MUST 禁用该告警的重复诊断按钮
