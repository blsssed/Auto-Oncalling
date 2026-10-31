## ADDED Requirements

### Requirement: SQLite concurrency resilience

记忆库 SQLite 引擎 SHALL 启用 WAL 日志模式与 busy timeout，使后台任务写入与 HTTP 请求读写并发时不再出现 `database is locked` 导致的无关功能 500。

#### Scenario: Concurrent writers do not fail with database is locked

- **WHEN** 后台任务与 HTTP 请求同时对记忆库执行写操作
- **THEN** 引擎 MUST 通过 WAL 与 busy timeout 等待或串行化写入，MUST NOT 把 `database is locked` 作为 500 暴露给普通请求

#### Scenario: Engine applies pragmas per connection

- **WHEN** 引擎新建任意连接
- **THEN** MUST 应用 `journal_mode=WAL`、`busy_timeout` 与 `synchronous=NORMAL`，且配置 MUST NOT 依赖手工执行迁移之外的步骤
