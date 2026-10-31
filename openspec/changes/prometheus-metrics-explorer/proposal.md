# Prometheus 数据源管理与指标浏览器

## Why

当前监控能力依赖文件配置的单一本机 Prometheus（`prometheus.baseUrl`），用户无法在界面上接入自己的 Prometheus 实例，也无法浏览、选择指标并查看真实时序图；前端导航中监控相关入口分散。需要新增 owner 作用域的 Prometheus 数据源管理与指标浏览器，并重组导航为「监控中心」。

## What Changes

- 新增 owner 作用域的 Prometheus 数据源 CRUD：`GET/POST /prometheus/sources`、`PUT/DELETE /prometheus/sources/{id}`、`POST /prometheus/sources/{id}:check`；password 只写不读，更新时空密码保留旧值；同名冲突返回 409。
- 新增查询代理：`GET /prometheus/labels/{label}/values?sourceId=`、`POST /prometheus/query`、`POST /prometheus/query-range`（stepSeconds 5–300，跨度 ≤ 3 天），复用 `HttpPromqlProvider` 真实查询；上游错误统一映射 SYSTEM_UNAVAILABLE 且不泄漏 URL/凭据/响应体。
- 首次列出数据源为空且文件配置 `prometheus.baseUrl` 有效时，自动播种「本机 Prometheus」。
- SQLite 新增 `prometheus_sources` 表（Alembic revision `202610290001`），仓储按 owner 过滤。
- 前端新增「数据源管理」与「指标浏览器」页面（`/monitor/sources`、`/monitor/metrics`），指标浏览器支持选源、指标名选择器（`__name__` label values）、PromQL 输入、时间范围与步长、ECharts 时序图（SVG 渲染）与序列明细表。
- 左侧导航新增「监控中心」分组（指标浏览器/数据源管理），移动端底栏改为 5 项紧凑形态，监控页面提供移动端子 tabs。
- 共享契约新增 `prometheus.ts` 类型与 OpenAPI 描述；智能诊断的 `promql_query` 工具本次不改，仍使用文件配置的 `prometheus` 节。

## Impact

- 后端：`super_ai/prometheus_sources.py`（新）、`super_ai/metrics.py`、`super_ai/api/app.py`、`super_ai/memory/*`、Alembic 迁移、`tests/test_prometheus_sources.py`（新）。
- 前端：`src/prometheus/`、`src/stores/prometheus.ts`、`src/components/MetricChart.vue`、`src/components/MonitorSubNav.vue`、`src/components/WorkspaceNavigation.vue`、`src/views/MetricsExplorerView.vue`、`src/views/PrometheusSourcesView.vue`、`src/layouts/WorkspaceLayout.vue`、`src/router/index.ts`。
- 共享契约：`packages/api-contracts/src/prometheus.ts`（新）、`index.ts`、`openapi.ts`、契约测试。
- 文档：README、OpenSpec 主规格新增 `prometheus-data-sources` 能力。
