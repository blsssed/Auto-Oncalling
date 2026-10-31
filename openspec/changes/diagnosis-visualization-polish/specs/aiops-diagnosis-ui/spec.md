## MODIFIED Requirements

### Requirement: Compact AIOps execution chain presentation

AIOps 工作区 SHALL 以持久化 Planner、Executor 和 Replanner 步骤构成可扫描的步骤时间线，并将工具调用作为独立的可折叠列表、把证据作为按类型分组的可折叠面板展示。

#### Scenario: Persisted steps are available

- **WHEN** 选中诊断包含 Planner、Executor 或 Replanner 步骤
- **THEN** 右栏 MUST 按执行顺序显示每一步的中文阶段标记、状态、记录时间、一句话中文标题和缩进输出

#### Scenario: Evidence is available

- **WHEN** 选中诊断包含持久化证据
- **THEN** 右栏 MUST 按证据类型分组显示真实数量、来源和摘要，并保留报告引用定位锚点，MUST NOT 展示原始 evidence payload

#### Scenario: Evidence is linked from the report

- **WHEN** 选中诊断的 `reportEvidenceLinks` 引用了某条证据
- **THEN** 右栏 MUST 在该证据上显示“报告引用”标记，并同时显示被引用证据总数

#### Scenario: Tool calls are available

- **WHEN** 选中诊断包含工具调用审计
- **THEN** 右栏 MUST 默认只显示工具名和状态，工具输出 MUST 位于默认收起的缩进详情框中

#### Scenario: Tool output contains structured records

- **WHEN** 工具结果摘要包含 SearchLog records、知识检索结果或其他 JSON 结构
- **THEN** 前端 MUST 将其转换为有限的可读文本摘要，MUST NOT 直接展示 JSON 字符串或原始 payload

#### Scenario: Live tool event arrives

- **WHEN** 实时时间线收到包含 output 的 `tool.call` 事件
- **THEN** 时间线 MUST 只展示工具生命周期和状态，MUST NOT 重复展示工具输出正文

#### Scenario: Live reference event arrives

- **WHEN** 实时时间线收到 `reference.source` 事件
- **THEN** 时间线 MUST 展示引用标题，并在存在时展示来源类型、相关度和截断后的摘要
