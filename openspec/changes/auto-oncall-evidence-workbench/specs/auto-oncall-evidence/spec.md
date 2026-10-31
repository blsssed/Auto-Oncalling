## ADDED Requirements
### Requirement: Scoped evidence investigation
系统 SHALL 限制查询在事故范围，最多修订 3 次计划和调用 6 次日志工具。
#### Scenario: Mixed incidents
- **WHEN** 主题包含多个事故
- **THEN** 查询 MUST 包含定位条件与时间边界
#### Scenario: Missing scope
- **WHEN** 没有定位条件
- **THEN** 系统 MUST 提示补充信息，不执行全量查询
### Requirement: Traceable structured conclusion
系统 SHALL 保存候选根因、正反证据、缺口与验证建议。
#### Scenario: Invalid reference
- **WHEN** 模型引用其他任务证据或不存在的摘录
- **THEN** 系统 MUST 拒绝结论并退化为证据不足
### Requirement: Human reviewed knowledge
系统 SHALL 仅检索人工确认的诊断案例。
#### Scenario: Idempotent confirmation
- **WHEN** owner 重复确认报告
- **THEN** 系统 MUST 返回同一案例而不重复创建索引任务
### Requirement: Credential free recording replay
系统 SHALL 提供不调用后台或 CLS 的公开回放。
#### Scenario: No recordings
- **WHEN** 没有脱敏录制
- **THEN** 页面 MUST 显示空状态，不制造诊断
### Requirement: Private configuration boundary
系统 SHALL 只向前端提供白名单 API 地址。
#### Scenario: Browser requests private config
- **WHEN** 浏览器访问私有 JSON
- **THEN** 开发服务器 MUST 拒绝且产物 MUST 不包含密钥
