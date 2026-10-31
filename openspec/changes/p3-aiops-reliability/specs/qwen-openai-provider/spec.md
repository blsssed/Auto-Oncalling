## ADDED Requirements

### Requirement: Independent embedding and rerank provider configuration

后端 SHALL 允许 `llm.embedding` 与 `llm.rerank` 覆盖聊天供应商的 API key、base URL、模型和维度，并在字段缺失或为空时逐字段回退到顶层 `llm` 配置。

#### Scenario: Chat and embedding use different providers

- **WHEN** `llm` 配置 DeepSeek 聊天，`llm.embedding` 配置百炼 API key、base URL 与模型
- **THEN** 聊天模型 MUST 使用顶层配置，Embedding 客户端 MUST 使用 `llm.embedding` 的凭据、base URL、模型和维度

#### Scenario: Rerank overrides only the endpoint

- **WHEN** `llm.rerank` 只配置 `apiKey` 和 `baseUrl`
- **THEN** rerank 模型名 MUST 回退到顶层 `llm.rerankModel`，聊天配置 MUST 保持不变

#### Scenario: Nested configuration is empty

- **WHEN** `llm.embedding` 或 `llm.rerank` 的字段为空或不存在
- **THEN** 有效值 MUST 回退到顶层 `llm.apiKey`、`llm.baseUrl`、`llm.embeddingModel`、`llm.embeddingDimensions`、`llm.rerankModel` 和 `llm.rerankUrl`

#### Scenario: Nested configuration is invalid

- **WHEN** `llm.embedding` 不是对象，或 `dimensions` 不是正整数
- **THEN** 配置加载 MUST 失败并返回不包含任何 API key 的安全错误信息
