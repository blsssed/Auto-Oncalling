# 任务

## 实现

- [x] 新增 `aiopsAutoDiagnosis` 配置段、加载与校验（`AutoDiagnosisSettings`）。
- [x] 告警轮询对比上一份快照，只处理新出现且级别匹配的告警。
- [x] 按告警 id 去重并限制每轮创建数量，复用 durable `aiops_diagnosis` job。
- [x] 自动诊断失败不影响告警轮询链继续调度。
- [x] REST 与 SSE 告警载荷附加当前用户的 `diagnosticId`/`diagnosisStatus`。
- [x] 共享契约 `ActiveAlert` 与 OpenAPI schema 同步。
- [x] 前端告警列表展示自动诊断状态并禁用重复触发。
- [x] README 与真实告警教程补充开关配置说明。

## 验证

- [x] `uv run pytest tests/test_auto_diagnosis.py tests/test_active_alerts.py`
- [x] `uv run pytest`
- [x] `uv run ruff check .`
- [x] `uv run pyright`
- [x] `npm run contracts:typecheck` 与 api-contracts 测试
- [x] `npm run frontend:typecheck`、相关 Vitest 与 `npm run frontend:build`
- [ ] `openspec validate --all`（当前环境未安装 OpenSpec CLI，待可执行时补跑）
