# 任务

## 实现

- [x] 共享契约：`prometheus.ts` 类型、index 导出、OpenAPI paths/schemas、契约测试（含 password 不落盘断言）。
- [x] SQLite：`prometheus_sources` 表 ORM 模型 + Alembic revision `202610290001`。
- [x] 仓储：`PrometheusSourceRecord`/`PrometheusSourceRepository` Protocol + `SQLitePrometheusSourceRepository` + `create_sqlite_memory_repositories` 接线。
- [x] 服务：`PrometheusSourceService`（校验、重名 409、密码只写不读、check 探测 `up`、首次播种、查询代理）。
- [x] `HttpPromqlProvider` 增加 `label_values`（含 label 标识符校验与 1000 条有界截断）。
- [x] API 路由：`/prometheus/sources` CRUD + `:check` + `/prometheus/labels/{label}/values` + `/prometheus/query` + `/prometheus/query-range`。
- [x] 前端基建：`prometheusClient.ts`、`stores/prometheus.ts`（含测试 seam）、`MetricChart.vue`（ECharts + SVG + ResizeObserver）。
- [x] 视图：`MetricsExplorerView.vue`、`PrometheusSourcesView.vue`、`MonitorSubNav.vue`。
- [x] 导航：`WorkspaceNavigation.vue` 监控中心分组 + compact 形态；`WorkspaceLayout.vue` 移动端 5 项底栏；路由 `/monitor/metrics`、`/monitor/sources`。

## 验证

- [x] `cd apps/backend && uv run ruff check . && uv run pyright`（0 错误）
- [x] `uv run pytest tests/test_prometheus_sources.py`（4 通过：CRUD/作用域/密码语义、check 上下行、播种、查询与 label values 校验）
- [x] `uv run pytest` 全量：除 2 个既有 readiness 用例外全部通过（该用例使用默认 `var/memory.sqlite3`，被本地运行中的后端进程锁定，属环境性失败）
- [x] `npm run frontend:typecheck`、`npm run frontend:test`（25 文件/97 测试全过）、`npm run frontend:build`
- [x] `npm run contracts:typecheck`、`npm --workspace packages/api-contracts run test`（27 通过）
- [ ] `openspec validate --all`（当前环境未安装 OpenSpec CLI，待可执行时补跑）
- [x] `python .codex/skills/publish-openspec-wiki/scripts/sync_wiki.py active prometheus-metrics-explorer`（wiki-sync complete，导航已验证）
- [x] README 同步监控中心导航与 `/monitor/*` 路由
- [x] 实测端到端（2026-10-29）：`alembic upgrade head` 应用 `202610290001`；注册→首次 list 自动播种「本机 Prometheus」→`:check` 通过→`__name__` label values 返回真实指标→`query-range` 返回毫秒时间戳真实序列；期间发现并修复 label values 路径缺失 `/label/` 的缺陷（补 `test_promql_provider_label_values_uses_label_endpoint` 断言请求路径）。
- [x] 浏览器目检（Playwright MCP，2026-10-30）：登录→数据源管理（新建「目检测试源」→检查连接真实通过→删除）；指标浏览器（`__name__` 下拉约 200 个真实指标→选 `go_goroutines` 查询→ECharts 曲线 + 序列明细 46 点）；移动端 390px（底栏 5 项平铺、监控子 tabs 互跳正常）。截图存于仓库根 `monitor-sources-desktop.png`、`monitor-metrics-chart.png`、`monitor-metrics-mobile.png`。
