## ADDED Requirements

### Requirement: 自助读取模型配置

系统 SHALL 提供受认证保护的 `GET /config/llm` 接口，返回当前生效的 LLM 模型配置视图。响应 MUST 以写掩码方式呈现密钥：只包含 `apiKeyConfigured`（布尔）与 `apiKeyLast4`（后 4 位或 null），MUST NOT 包含完整 apiKey 或其他敏感值。

#### Scenario: 已配置密钥的读取

- **WHEN** 已认证客户端请求 `GET /config/llm` 且配置中 apiKey 非空
- **THEN** 响应 MUST 返回 `apiKeyConfigured=true`、`apiKeyLast4` 为密钥后 4 位，以及 provider、baseUrl、chatModel、contextWindowTokens、embedding、rerank 等非敏感字段；响应文本 MUST NOT 出现完整 apiKey

#### Scenario: 未认证读取

- **WHEN** 未认证客户端请求 `GET /config/llm`
- **THEN** 响应 MUST 返回 `AUTH_UNAUTHENTICATED`

### Requirement: 自助写入模型配置并热生效

系统 SHALL 提供受认证保护的 `PUT /config/llm` 接口，将模型配置写入 `config/user.project.json` 并在保存成功后无需重启即生效。写入 MUST 原子化（临时文件 + 原子替换）、MUST 保留文件中其他配置段与未编辑字段、MUST 同步 `modelCapabilities[chatModel].contextWindowTokens`。写后 MUST 用完整配置校验器校验，失败时 MUST 回滚文件并返回 `MODEL_CONFIGURATION_INVALID`。

#### Scenario: 保存并立即生效

- **WHEN** 已认证客户端提交合法 `PUT /config/llm`
- **THEN** 后端 MUST 原子写入 `config/user.project.json`、MUST 重置运行时 provider 与检索缓存，且随后的聊天/诊断请求 MUST 使用新配置，全程 MUST NOT 需要重启后端

#### Scenario: 空 apiKey 保持现有值

- **WHEN** 提交 `PUT /config/llm` 且 apiKey 为空，但当前配置中已存在有效 apiKey
- **THEN** 后端 MUST 保持现有 apiKey 不变并完成保存

#### Scenario: 未配置密钥时空 apiKey

- **WHEN** 提交 `PUT /config/llm` 且 apiKey 为空，且当前配置中不存在有效 apiKey
- **THEN** 后端 MUST 返回 `VALIDATION_MISSING_FIELD`，且 MUST NOT 修改配置文件

#### Scenario: 非法配置回滚

- **WHEN** 提交的字段组合写后无法通过完整配置校验
- **THEN** 后端 MUST 还原 `config/user.project.json` 原始内容并返回 `MODEL_CONFIGURATION_INVALID`

#### Scenario: 现有用户配置文件不可解析

- **WHEN** `config/user.project.json` 已存在但不是合法 JSON 对象
- **THEN** 后端 MUST 返回业务冲突错误且 MUST NOT 修改或覆盖该文件

### Requirement: 测试连接复用就绪检查

「测试连接」能力 SHALL 复用现有 `GET /config/check`（`configuration.llm` 与 `dependencies.llm`），MUST NOT 新增专用 check 端点。由于保存即热生效，测试连接反映的是当前已保存并生效的配置。

#### Scenario: 保存后测试连接

- **WHEN** 用户保存模型配置后触发测试连接
- **THEN** 前端 MUST 调用 `GET /config/check` 并展示 `configuration.llm` 与 `dependencies.llm` 的状态；响应文本 MUST NOT 包含 apiKey

### Requirement: 自助配置 Langfuse 追踪凭据

`GET / PUT /config/llm` SHALL 同时支持读取与写入可选的 `langfuse` 配置段（`enabled`、`host`、`publicKey`、`secretKey`），写入 `config/user.project.json` 并随保存热生效（保存后 MUST 重置缓存的 tracing provider）。`publicKey` 与 `secretKey` 属于凭据，MUST 与 LLM apiKey 相同方式写掩码：只返回 `*Configured` 与 `*Last4`，MUST NOT 回传密钥本体。启用追踪时必须存在（已有或本次提交）`publicKey` 与 `secretKey`，否则 MUST 返回 `VALIDATION_MISSING_FIELD` 且不修改文件；关闭追踪 MUST 只改 `enabled` 并保留已保存的密钥；写后校验 MUST 包含 Langfuse 配置校验，失败时回滚。

#### Scenario: 写入 Langfuse 密钥并热生效

- **WHEN** 已认证客户端提交 `PUT /config/llm` 且 `langfuseEnabled=true` 并附带 `langfusePublicKey`/`langfuseSecretKey`
- **THEN** 后端 MUST 将 `langfuse` 段写入 `config/user.project.json`（保留该段其他键与文件其他段）、MUST 重置缓存的 tracing provider；响应与随后的 `GET /config/llm` MUST 只含掩码字段而不出现密钥本体

#### Scenario: 空 Langfuse 密钥保持现有值

- **WHEN** 提交的 `langfusePublicKey`/`langfuseSecretKey` 为空但配置中已存在
- **THEN** 后端 MUST 保持现有密钥不变并完成保存

#### Scenario: 启用追踪但缺少密钥

- **WHEN** 提交 `langfuseEnabled=true` 且 `publicKey`/`secretKey` 均不存在（配置中无、提交中亦为空）
- **THEN** 后端 MUST 返回 `VALIDATION_MISSING_FIELD` 且 MUST NOT 修改配置文件

#### Scenario: 关闭追踪保留密钥

- **WHEN** 配置中已存在 Langfuse 密钥且提交 `langfuseEnabled=false`
- **THEN** 后端 MUST 写入 `enabled=false` 并保留 `publicKey`/`secretKey`，以便随后重新启用
