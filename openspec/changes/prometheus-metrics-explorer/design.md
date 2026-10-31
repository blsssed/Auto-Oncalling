# 设计：Prometheus 数据源管理与指标浏览器

## 决策

### 1. 后端完全镜像 MCP 连接模式

数据源 CRUD 复用既有栈：`PrometheusSourceRecord`（frozen dataclass）+ `PrometheusSourceRepository` Protocol（全部按 `owner_user_id` 过滤）+ `SQLitePrometheusSourceRepository` + Alembic 迁移 + `PrometheusSourceService` + `app.py` 内联路由。表上加 `UniqueConstraint(owner_user_id, name)`，服务层在写入前显式检查重名返回 BUSINESS_CONFLICT，避免裸 IntegrityError 变 500。

### 2. password 只写不读

记录保留 `password` 字段供查询时 BasicAuth，但序列化 payload 永不含 password；更新请求中空 password 表示保留旧值。认证用户名与密码必须同时提供或同时为空，避免半配置凭据产生不可预测的认证行为。

### 3. 查询代理复用 HttpPromqlProvider

`HttpPromqlProvider` 新增 `label_values` 方法（仅具体类，不加入 `PromqlProvider` Protocol，避免破坏测试中的 fake）。range 查询约束 stepSeconds ∈ [5,300]、跨度 ≤ 3 天；label 名按 Prometheus 标识符正则校验。上游错误统一映射 SYSTEM_UNAVAILABLE，固定文案不泄漏上游 URL、凭据或响应体。

### 4. 首次播种「本机 Prometheus」

服务 `list` 在用户无数据源且文件配置 `prometheus.baseUrl` 有效时自动播种，保证本地体验开箱即用；播种按用户生效，失败不阻断列表。诊断链路 `promql_query` 本次不改，继续读文件配置。

### 5. 前端复用 MCP 域组织方式

`prometheusClient.ts` + `stores/prometheus.ts`（含 `setPrometheusClientFactoryForTests` 测试 seam）镜像 MCP 域。指标浏览器通过 `label_values("__name__")` 提供真实指标名选择器，PromQL 手输优先。图表用 ECharts `echarts/core` tree-shaken + SVGRenderer（jsdom 可测），配色复用暗色监控 token，ResizeObserver 自适应（测试环境缺省时跳过），卸载时 dispose。

### 6. 导航监控化重组

左侧新增「监控中心」组（指标浏览器/数据源管理），「智能诊断」及其 4 个子页保持 `/aiops*` 路由不动以减少破坏面。移动端底栏切到 `compact` 形态：对话/知识库/监控/诊断/MCP 五项平铺，监控页面内部用 `MonitorSubNav` 提供子 tabs（镜像 AiopsSubNav 的移动端-only 行为）。

## 风险

- 数据源 URL 允许 http/https 且禁止内嵌 userinfo；不阻止内网地址（本工具本质是本机 AIOps 工作台），依赖 owner 作用域与凭据不落盘日志。
- label values 结果按 1000 条有界截断，防超大 cardinality 撑爆内存。
- ECharts 引入增加前端体积；已通过 chunk 警告提示，必要时后续可拆 manualChunks。
