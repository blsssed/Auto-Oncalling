# 诊断过程可视化打磨

## Why

当前执行链虽然按顺序展示 Planner、Executor、Replanner 步骤和工具调用，但步骤缺少阶段、状态与时间的整体视图；持久化证据只能逐条展开，无法快速判断证据类型分布，也看不出哪些证据真正被最终报告引用。operator 需要在长诊断中快速定位关键日志、指标和引用来源。

## What Changes

- 执行步骤增加中文阶段标记（计划/执行/重规划）、状态徽标和记录时间，形成可扫描的步骤时间线。
- 证据按 `kind` 分组（日志、指标、告警、工单、知识引用），显示真实分组计数，并保留稳定的 `evidence-<id>` 锚点供报告引用跳转。
- 只有存在于 `reportEvidenceLinks` 中的证据显示“报告引用”标记，包含被引用证据的分组默认展开；不伪造引用。
- 证据摘要中的失败、超时、异常、严重等关键词使用纯文本片段高亮，不使用 `v-html`，原始 `payload` 仍不展示。
- 实时诊断时间线补充事件总数、工具调用数和引用数，并为知识引用事件展示来源类型、相关度和截断摘要。
- 同步更新 OpenSpec 规格、README 与前端组件测试。

## Impact

- 前端：`AiopsEvidenceChain.vue`、`AiopsTimeline.vue`、`aiopsComponents.test.ts`。
- 文档：README AIOps 能力说明、OpenSpec `aiops-evidence-chain` 与 `aiops-diagnosis-ui` 规格。
- 后端、共享契约与数据库 schema 无变化。
