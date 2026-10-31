## MODIFIED Requirements

### Requirement: Operator-facing evidence is an execution trace

前端 SHALL 将 operator 可见的诊断证据链组织为 Planner、Executor、Replanner 的持久化执行步骤时间线和按类型分组的证据面板，而后端仍保留完整原始 evidence 供持久化和报告追溯。前端 MUST NOT 展示 evidence `payload`、工具原始输出或工具结果中的 JSON 结构。

#### Scenario: Operator reviews the evidence panel

- **WHEN** operator 查看一个已有完整证据链的诊断任务
- **THEN** 界面 MUST 按步骤顺序展示阶段、状态、时间、步骤标题和步骤输出，并按 `kind` 分组展示真实证据条目、来源、摘要和稳定标识

#### Scenario: Evidence is grouped by kind

- **WHEN** 选中的证据链包含日志、指标、告警、工单或知识引用证据
- **THEN** 界面 MUST 按日志、指标、告警、工单、知识引用的固定顺序分组，显示每组真实条目数量，未知类型排在末尾并显示原始 kind

#### Scenario: Evidence is cited by the report

- **WHEN** 某条证据存在于 `reportEvidenceLinks` 中
- **THEN** 界面 MUST 为该证据显示“报告引用”标记，并默认展开其所属分组；未出现在链接中的证据 MUST NOT 显示引用标记

#### Scenario: Evidence summary contains risk keywords

- **WHEN** 证据摘要包含失败、超时、异常、错误、告警或严重等关键词
- **THEN** 界面 MUST 以纯文本片段方式高亮这些关键词，MUST NOT 使用 `v-html` 渲染证据内容

#### Scenario: Report citation jumps to evidence

- **WHEN** operator 点击报告中的证据引用
- **THEN** 界面 MUST 打开并滚动到对应的 `evidence-<id>` 条目，且该条目所在分组 MUST 可见

#### Scenario: Tool details are collapsed

- **WHEN** operator 尚未主动展开某个工具调用
- **THEN** 该工具的参数和结果内容 MUST 保持隐藏，仅显示工具名称和状态

#### Scenario: Operator expands a tool

- **WHEN** operator 展开某个工具调用
- **THEN** 界面 MUST 在缩进容器中展示经过长度限制和语义格式化的结果，并保持页面无水平溢出
