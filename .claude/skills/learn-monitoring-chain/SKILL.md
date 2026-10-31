---
name: learn-monitoring-chain
description: 按请求生命周期学习本仓库监控链路：从 FastAPI 路由入口，经 AIOps 编排、日志/指标/MCP 数据源、SQLite 持久化，到 SSE 返回前端。当用户问“监控链路怎么学 / 从哪开始读 / 一次诊断请求怎么走 / 改监控代码该看哪里”时使用。
allowed-tools: Read, Grep, Glob, Bash
---

# 学习监控链路

目标：让完全没看过本仓库的人，在 90 分钟内建立一条能自己走的调用路径，而不是通读 10 万行代码。

使用方法：按下面的“四站路线”顺序读；每一站先读“先读什么”，读完用“必须能回答”自检，答不上再回头读，不要提前跳站。

## 30 秒心智模型

用户点“开始诊断”后，只发生五件事：

1. **入口**：前端 `POST /aiops/diagnostics`，后端校验参数、写一条 `queued` 任务，立刻返回 `taskId`。
2. **任务**：`BackgroundJobRuntime` 的 worker 用 SQLite 租约领走任务，在后台执行，失败会退避重试。
3. **编排**：`AiopsDiagnosticService` 用 LangGraph 跑 `planner → executor → replanner → report`，执行日志/指标/知识检索。
4. **数据**：日志经 `LogQuery` 钳制后交给 CLS MCP 或本地 adapter；指标经 PromQL provider；每个结果都脱敏后落库成“证据”。
5. **返回**：前端打开 `GET /aiops/diagnostics/{id}:stream`，按持久化事件的 `sequence` 顺序收到 SSE；断线重连可回放。

记住一句话：**请求只负责入队和回放，真正的诊断在后台任务里。**

## 90 分钟四站路线

| 站 | 时间 | 先读什么 | 读完必须能回答 | 明确跳过 |
|---|---|---|---|---|
| 0 请求进入 | 15 min | `api/app.py`: `create_app`、`/health`、`_current_user`、`success_response` | 请求怎样变成已认证用户和统一信封？成功/失败两种信封长什么样？ | 认证、聊天、知识库、MCP CRUD 全部路由 |
| 1 任务启动 | 25 min | `POST /aiops/diagnostics`、`jobs/runtime.py` 全文、`aiops_job_handler` | 为什么请求只入队？谁真正执行？失败、超时、取消分别去哪？ | worker 池扩缩容、租约 SQL 细节 |
| 2 诊断编排 | 30 min | `aiops/diagnostics.py`: `stream`、`_build_graph`、`_planner`、`_executor`、`_replanner`、`_report` | 四个节点各读 state 的哪些字段、返回哪些 delta？失败时降级成什么？ | `_create_plan` 之后的预算/事件/payload helper |
| 3 返回前端 | 20 min | `api/app.py`: `stream_aiops_diagnostic` 内的 `event_stream`、`chat/streaming.py:encode_sse`、告警快照轮询 | 事件怎样持久化？断线为什么能从 `sequence` 续上？告警清了为什么还有一条 revision？ | 前端组件细节、各告警厂商解析 |

### 每一站的具体读法

**站 0：只建立“入口长什么样”的直觉。**
先看 `create_app` 里注册的中间件和异常处理器，再看任意一个健康检查路由（如 `/health`），最后看 `_current_user` 怎样从 token 得到 `UserRecord`。不要在这里读业务。

**站 1：这是全链路最值得精读的 200 行。**
先读 `BackgroundJobRuntime._worker_loop`，再读 `_execute` 的四个分支（成功 / 取消 / 失败重试 / 超时），最后读 `raise_if_cancelled`。读完后回到 `api/app.py`，看 `create_aiops_diagnostic` 怎样 `enqueue`、`aiops_job_handler` 怎样被注册和调用。

**站 2：只读“图”和“节点”，不读工具实现。**
先读 `stream` 确认它怎样创建任务状态并驱动图，再读 `_build_graph` 确认节点和边，然后逐个读四个节点。每个节点只回答三件事：读哪些 state 字段、返回哪些 delta、异常时回退成什么。`_executor` 里真正要理解的是“先并发取数、再串行落库”这个顺序，而不是每个 `_safe_value`。

**站 3：把“产生事件”和“发送事件”分开看。**
产生事件在站 2 的节点里（`_task_status_event`、`_tool_event` 等），持久化在任务事件表，发送在 `event_stream`。先看 `encode_sse` 的帧格式，再看 `event_stream` 怎样按 `sequence` 读库并 yield，最后看告警轮询为什么要维护 revision。

## 函数内部只看三处

第一次读任何函数，只找这三个位置，其余代码先跳过：

1. **入参从哪来**：是路由参数、state 字段，还是上一个函数的结果？
2. **返回什么形状**：统一信封、delta dict、SSE event，还是领域记录？
3. **异常/取消时走哪条分支**：抛给上层、降级为 insufficient，还是写失败事件？

函数名和类型标注已经说明“做了什么”，不要为 getter、构造器、payload 转换停留。

## 文件热点图

行号会漂移，以函数名为准。

| 文件 | 只读这些 | 跳过 |
|---|---|---|
| `apps/backend/src/super_ai/api/app.py` | `create_app`、健康检查段、`create_aiops_diagnostic`、`aiops_job_handler`、`stream_aiops_diagnostic`、`_alert_poll_job_handler`、`alert_snapshot_stream` | 认证、聊天、知识库、MCP CRUD、文件上传 |
| `apps/backend/src/super_ai/aiops/diagnostics.py` | `stream`、`_build_graph`、`_planner`、`_executor`、`_replanner`、`_report` | `_create_plan` 之后的 helper |
| `apps/backend/src/super_ai/jobs/runtime.py` | 整个文件（约 215 行） | 无 |
| `apps/backend/src/super_ai/memory/extended_sqlite.py` | `SQLiteBackgroundJobRepository`、`SQLiteActiveAlertRepository` | feedback、MCP connection 仓储 |
| `apps/backend/src/super_ai/memory/sqlite.py` | `SQLiteToolCallAuditRepository`、`SQLiteDiagnosticMemoryRepository` | chat/prompt/skill/knowledge/document/索引任务仓储 |
| `apps/backend/src/super_ai/aiops/investigation.py` | `resolve_scope`、`scoped_metric_step`、`fingerprint`、`validate_diagnosis`、`diagnosis_markdown` | Pydantic 字段声明、正则细节 |
| `apps/backend/src/super_ai/log_store/query.py` | `LogQuery.from_step`、`to_cls_arguments`、`matches` | 历史 Query 字符串解析 |
| `apps/backend/src/super_ai/alerts.py` | `AggregatedAlertProvider`、`_normalize_alert` | 各厂商解析细节 |
| `apps/backend/src/super_ai/metrics.py` | `HttpPromqlProvider.query_range` | 结果解析辅助函数 |
| `apps/backend/src/super_ai/mcp_client.py` | `LocalMcpClient.call_tool`、`discover_tools` | 传输实现、重试参数 |
| `apps/backend/tests/` | `test_readiness_api.py`、`test_aiops_diagnostics.py`、`test_active_alerts.py` | 其余 |

## 可执行验证

读完后用测试和真实请求验证理解，不要只靠阅读：

```bash
cd apps/backend

# 入口与信封
uv run pytest tests/test_readiness_api.py -q

# 诊断主链路（计划、证据、报告、SSE）
uv run pytest tests/test_aiops_diagnostics.py -q

# 告警快照 revision 语义
uv run pytest tests/test_active_alerts.py -q
```

本地启动后（见 `README.md` 或 `scripts/start-local.sh`）：

```bash
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/ready
```

再用浏览器登录、发起一次诊断，打开开发者工具的 Network → EventStream，观察事件顺序与 `sequence` 是否连续。

## 五个自测题

能答出这五题，说明链路已经通了：

1. 为什么诊断请求不直接在请求线程里执行，而是先入队？
2. `planner` 和 `replanner` 返回的 delta 有什么区别？预算在哪里被扣减？
3. `_executor` 为什么先 `gather` 再串行写库？如果边取数边写库会出什么问题？
4. 证据（evidence）和报告（report）是什么关系？引用校验失败时报告变成什么？
5. 为什么告警快照为空也要把 revision 加一？

## 常见误区

- **别从 `models.py` 或 `config.py` 读起**：它们是形状和配置，不是链路。
- **别先学 LangGraph**：先理解四个节点各自的输入输出，再看图怎样连起来。
- **别通读 `app.py`**：只读热点图里的函数，其余路由与监控无关。
- **别把注释当规格**：行为以代码和测试为准；代码里只有“为什么”注释，导览在本 skill。
- **别跳过失败路径**：监控链路的重点就是失败、超时、取消、证据不足时怎样收敛。
