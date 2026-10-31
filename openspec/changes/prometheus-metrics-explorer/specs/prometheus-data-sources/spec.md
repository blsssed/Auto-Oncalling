## ADDED Requirements

### Requirement: Owner-scoped Prometheus data source management

系统 SHALL 提供 owner 作用域的 Prometheus 数据源管理接口：`GET/POST /prometheus/sources`、`PUT/DELETE /prometheus/sources/{id}`、`POST /prometheus/sources/{id}:check`，全部要求 Bearer 认证，所有读写 MUST 按已认证用户过滤，MUST NOT 接受客户端提交的 `ownerUserId` 作为授权依据。

#### Scenario: Create a data source

- **WHEN** 已认证用户提交合法 name、baseUrl（http/https 且无内嵌 userinfo）、timeoutSeconds（1-300）、maxSeries（1-100）
- **THEN** 系统 MUST 创建数据源并返回 201，payload MUST 包含 id/name/baseUrl/username/enabled/timeoutSeconds/maxSeries/lastCheck/createdAt/updatedAt，MUST NOT 包含 password

#### Scenario: Duplicate name within the same owner

- **WHEN** 用户创建或更新数据源的 name 与同 owner 已有数据源重复
- **THEN** 系统 MUST 返回 409 BUSINESS_CONFLICT

#### Scenario: Password semantics

- **WHEN** 更新数据源的 password 为空
- **THEN** 系统 MUST 保留旧密码；password MUST NOT 出现在任何 API 响应、日志或错误信息中

#### Scenario: Cross-owner access

- **WHEN** 用户尝试读取、更新、删除或探测其他 owner 的数据源
- **THEN** 系统 MUST 返回 403，MUST NOT 暴露数据源是否存在

#### Scenario: Connectivity check

- **WHEN** 用户请求 `:check`
- **THEN** 系统 MUST 对数据源执行真实 instant `up` 查询并持久化探测结果；失败时 lastCheck 的 error MUST 为固定文案，MUST NOT 泄漏上游 URL、凭据或响应体

#### Scenario: First-list seeding

- **WHEN** 用户首次列出数据源且文件配置 `prometheus.baseUrl` 有效
- **THEN** 系统 MUST 自动创建「本机 Prometheus」；播种失败 MUST NOT 阻断列表返回

### Requirement: Prometheus query proxy

系统 SHALL 提供查询代理接口：`GET /prometheus/labels/{label}/values?sourceId=`、`POST /prometheus/query`、`POST /prometheus/query-range`，全部要求 Bearer 认证并按数据源 owner 作用域过滤；查询结果时间戳 MUST 以毫秒返回。

#### Scenario: Range query

- **WHEN** 用户提交 sourceId/query/startMs/endMs/stepSeconds（5-300）且跨度 ≤ 3 天
- **THEN** 系统 MUST 调用真实 Prometheus `/api/v1/query_range` 并返回 `{ query, startMs, endMs, stepSeconds, series }`，series 中每个点 MUST 为 `{ timestamp(ms), value }`

#### Scenario: Instant query

- **WHEN** 用户提交 sourceId/query/可选 timeMs
- **THEN** 系统 MUST 调用 `/api/v1/query` 并返回 `{ query, series }`

#### Scenario: Label values for metric picker

- **WHEN** 用户请求 `__name__` 或其他合法 label 的 values
- **THEN** 系统 MUST 调用 `/api/v1/label/{label}/values` 并返回有界列表；label 不符合 Prometheus 标识符规则时 MUST 返回 400

#### Scenario: Upstream failure

- **WHEN** 上游 Prometheus 不可达或返回非法响应
- **THEN** 系统 MUST 返回 503 SYSTEM_UNAVAILABLE，MUST NOT 泄漏上游 URL、凭据或响应体

#### Scenario: Disabled source cannot be queried

- **WHEN** 用户对已停用数据源执行查询或 label values
- **THEN** 系统 MUST 返回 409 BUSINESS_CONFLICT

### Requirement: Metrics explorer and data source views

前端 SHALL 提供「监控中心」：数据源管理页（`/monitor/sources`）支持列表、新建、编辑（密码留空保留旧值）、删除与连通性检查；指标浏览器页（`/monitor/metrics`）支持选择数据源、通过 `__name__` 真实指标名选择器或手动输入 PromQL、选择时间范围（≤ 3 天）与步长、展示 ECharts 时序图与序列明细表。桌面与移动端布局 MUST 同时保留，移动端 MUST 提供监控子 tabs，且 MUST 尊重 `prefers-reduced-motion`。

#### Scenario: User adds their own Prometheus and explores metrics

- **WHEN** 用户在数据源管理页创建并检查通过数据源，随后在指标浏览器选中该数据源
- **THEN** 指标选择器 MUST 展示该数据源真实返回的 `__name__` 列表；执行查询后 MUST 展示真实时序图与序列明细，MUST NOT 使用伪数据

#### Scenario: No sources available

- **WHEN** 用户没有任何数据源
- **THEN** 指标浏览器 MUST 显示引导用户先到数据源管理页的空状态

#### Scenario: Mobile navigation

- **WHEN** 视口宽度 ≤ 760px
- **THEN** 底部导航 MUST 平铺对话/知识库/监控/诊断/MCP 五项，监控页面 MUST 提供「指标浏览器/数据源管理」子 tabs
