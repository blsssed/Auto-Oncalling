## ADDED Requirements

### Requirement: Optional provider and local log configuration sections

项目配置 SHALL 支持可选的 `llm.embedding`、`llm.rerank` 与 `logStore` 读取限制字段，模板只提供安全默认值，不包含真实凭据。

#### Scenario: Templates keep provider overrides empty

- **WHEN** 检查 `config/project.template.json` 和 `config/user.project.template.json`
- **THEN** `llm.embedding.apiKey`、`llm.embedding.baseUrl`、`llm.embedding.model`、`llm.rerank.apiKey`、`llm.rerank.baseUrl` 和 `llm.rerank.model` MUST 为空字符串，`llm.embedding.dimensions` MUST 为 `null`

#### Scenario: Merged config preserves empty override sections

- **WHEN** 应用合并基础模板与用户模板
- **THEN** 合并结果 MUST 保留空的 `llm.embedding` 与 `llm.rerank` 节，并 MUST NOT 用环境变量补充缺失字段

#### Scenario: Local log limits have safe defaults

- **WHEN** `logStore.type` 为 `file` 且未配置读取限制
- **THEN** `format` MUST 默认为 `auto`，`maxBytes` MUST 默认为 8 MiB，`maxRecords` MUST 默认为 20,000

#### Scenario: Local log limits are invalid

- **WHEN** `logStore.format` 不是 `auto`/`jsonl`/`json-array`，或 `maxBytes`/`maxRecords` 不是正整数
- **THEN** 配置构建 MUST 失败并返回明确的安全错误
