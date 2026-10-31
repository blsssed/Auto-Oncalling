# 任务

## 实现

- [x] `AiopsEvidenceChain.vue` 增加步骤阶段、状态与时间标记。
- [x] 证据按 kind 分组、显示真实计数，并按 `reportEvidenceLinks` 标记报告引用。
- [x] 证据摘要关键词安全高亮（文本切片 + `<mark>`，不使用 `v-html`）。
- [x] 保留 `evidence-<id>` 锚点与原始 payload 隐藏行为。
- [x] `AiopsTimeline.vue` 增加事件/工具调用/引用计数与引用来源详情。
- [x] README 同步可视化能力说明。

## 验证

- [x] `npx vitest run tests/aiopsComponents.test.ts --pool=forks --poolOptions.forks.singleFork=true`
- [x] `npm run frontend:typecheck`
- [x] 全量前端测试（22 文件/82 测试）与 `npm run frontend:build`
- [ ] `openspec validate --all`（当前环境未安装 OpenSpec CLI，待可执行时补跑）
