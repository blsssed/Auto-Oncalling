# 设计：自助模型配置与个人信息

## 决策

### 1. apiKey 写掩码语义

GET `/config/llm` 绝不返回完整 apiKey，只返回 `apiKeyConfigured: boolean` 与 `apiKeyLast4: string | null`。PUT 中 `apiKey` 为空字符串或缺省表示「保持现有值」；当合并配置中当前没有任何有效 apiKey 且提交为空时，返回 `VALIDATION_MISSING_FIELD`。这满足「不泄露密钥」约束，同时让首次配置与替换密钥都可用。

### 2. 生效源写入（effective-source write）

`LlmProviderConfig` 的 embedding/rerank 字段支持顶层标量与嵌套对象（`embedding.model`、`rerank.model` 等）两种来源，嵌套优先。写入时检查 `user.project.json` 中该字段的嵌套键是否非空：非空则写嵌套键，否则写顶层标量。嵌套的 `embedding.apiKey`/`rerank.apiKey` 覆盖与其他无关配置段全部保留，不做归一化重写。

### 3. 原子写 + 写后校验回滚

写入 `config/user.project.json` 采用同目录临时文件 + `os.replace`；写后立即用 `load_llm_provider_config` 对合并配置做完整校验，失败则还原原始字节（或删除新建文件）并抛 `LlmConfigApplyError`。已有 user 文件不可解析时报 `UserConfigInvalidError` 且文件字节不变。

### 4. 热生效缓存失效

`load_project_config` 每次读盘，但运行时 provider 是 `app.state` 进程级缓存。PUT 成功后调用 `_invalidate_llm_runtime_cache(app)`：将未注入的 `llm_provider`/`embedding_model`/`rerank_model`/`chat_agent_runner`/`aiops_diagnostic_runner` 置 `None`，`llm_context_window_tokens` 置 `None`，`retrieval_cache` 置回 `_RETRIEVAL_CACHE_UNSET`（否则新 runner 复用旧 embedding 模型的缓存向量）。`create_app` 记录 `injected_providers` 清单，注入的测试 fake 永不被覆盖。in-flight 后台任务沿用旧 provider，属可接受边界。

### 5. 测试连接复用 /config/check

「测试连接」按钮与运行状态面板都调用现有 `GET /config/check`（`configuration.llm` + `dependencies.llm`），不新增端点。由于保存即热生效，测试的就是当前生效配置；表单未保存时按钮提示「请先保存」。

### 6. 改密码吊销全部会话

`change_password` 校验当前密码（错误报 `AUTH_PASSWORD_MISMATCH`）、Argon2 重哈希后调用 `revoke_sessions_for_user` 吊销该用户所有会话（含当前会话），前端跳到登录页重新登录。与现有「注销撤销」语义一致，无新迁移。

### 7. provider 固定只读

后端只实现 `qwen-openai` 一个 provider，PUT 请求模型不含 `provider` 字段，前端展示为只读文本。

## 风险

- **缓存重置边界**：遗漏 `retrieval_cache` 会导致 embedding 变更不生效——有专门测试断言 sentinel 复位。
- **文件安全**：写路径是唯一的项目配置文件写入口；写后校验 + 回滚 + 不毁坏的非法文件保护是关键路径，测试覆盖文件字节不变。
- **严格类型**：Pydantic v2 别名字段、TS `Record<ApiErrorCode, string>` 三处同步是新构建最易出错的点。
