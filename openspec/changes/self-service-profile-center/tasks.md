# 任务

## 实现

- [x] 契约：`model-configuration.ts` 新建；`auth.ts`/`errors.ts`/`openapi.ts`/`index.ts` 扩展；契约测试补路径、受保护操作、schema 与类型 fixture。
- [x] 后端 `project_config.py` 增公开 `user_config_path_for` 助手。
- [x] 后端 `llm/config_writer.py`：`LlmConfigUpdate`、三种异常、`load_llm_config_view`（掩码）、`apply_llm_config_update`（生效源写入、modelCapabilities 同步、原子写、写后校验回滚）。
- [x] 后端 `error_catalog.py` 增 `AUTH_PASSWORD_MISMATCH`、`MODEL_CONFIGURATION_INVALID`。
- [x] 后端 `auth/repositories.py` Protocol 增 `update_user_profile`/`update_user_password_hash`/`revoke_sessions_for_user`；`auth/sqlite.py` 实现；`auth/service.py` 增 `update_profile` 与 `change_password`。
- [x] 后端 `api/app.py`：`injected_providers` 记录、三个请求模型、`GET/PUT /config/llm`、`PUT /auth/profile`、`PUT /auth/password`、`_invalidate_llm_runtime_cache`（含 retrieval_cache sentinel 复位）。
- [x] 前端：路由三子页、`WorkspaceLayout` 头像链接与 `repeat(6,1fr)`、`WorkspaceNavigation` 个人中心入口（compactOnly）。
- [x] 前端：`ProfileView.vue`/`ModelConfigView.vue`/`PersonalInfoView.vue`/`ProfileAboutView.vue` 新建。
- [x] 前端：`settings/modelConfigClient.ts`、`stores/modelConfig.ts` 新建；`authClient.ts`、`stores/auth.ts`、`ui/userFacingError.ts` 扩展。
- [x] 文档：`docs/operations-and-monitoring.md` 自助配置小节；`README.md` 能力清单与入口表。
- [x] Langfuse 追踪自助配置：契约 `model-configuration.ts`/`openapi.ts` 增 langfuse 字段；`config_writer.py` 读写 `langfuse` 段（写掩码、启用校验、关闭保留密钥、写后 `load_tracing_settings` 校验回滚）；`app.py` 失效 `tracing_provider`；`ModelConfigView.vue` 增 Langfuse 表单段。

## 测试

- [x] `tests/test_model_config_api.py`：GET 掩码无密钥泄漏；PUT 写盘保留其他段、modelCapabilities 同步、空 apiKey 保持、未配置空 key 报错、嵌套生效源写入、热生效后 app.state 复位（含 retrieval_cache sentinel）、注入 fake 不覆盖、写后校验失败回滚字节不变、非法 user 文件不毁。
- [x] Langfuse：PUT 写入 langfuse 段且响应/GET 无密钥本体、tracing_provider 复位 sentinel；空密钥保持、关闭只改 enabled 且保留密钥、启用缺密钥报 `VALIDATION_MISSING_FIELD` 且文件不变。
- [x] `tests/test_profile_api.py`：改昵称同步 /auth/me、空昵称报错、未认证 401、错当前密码 `AUTH_PASSWORD_MISMATCH`、短新密码报错、改密码后旧 token 失效新密码可登录。
- [x] 前端 `tests/modelConfigStore.test.ts`、`tests/settingsComponents.test.ts` 新建；`appShellRouter.test.ts`、`workspaceLayout.test.ts`、`appShellComponents.test.ts` 扩展。

## 验证

- [x] `apps/backend`：`uv run ruff check .`、`uv run pyright`、`uv run pytest`。
- [x] 仓库根：`npm run frontend:typecheck`、`npm run frontend:test`、`npm run contracts:typecheck`、`npm --workspace packages/api-contracts run test`、`openspec validate --all`、`npm run docs:build`。
- [x] 手工 E2E：点头像进个人中心→改模型保存→状态面板 valid→测试连接 ok→聊天走新模型→改昵称→改密码重登录→窄屏布局可用→响应无 apiKey 泄漏（附桌面 + 窄屏截图）。
