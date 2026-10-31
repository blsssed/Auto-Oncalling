# 个人中心：自助模型配置与个人信息管理

## Why

当前 LLM 配置（apiKey、baseUrl、chatModel、embedding/rerank 模型、temperature 等）只能手改被 Git 忽略的 `config/user.project.json` 后重启后端；前端左下角头像不可点击，昵称不可修改，也没有改密码入口。使用者需要在前端自助完成这些操作：点击左下角头像进入「个人中心」，左侧菜单含「模型配置」「个人信息」「关于」，模型配置保存后无需重启即可生效，并提供「测试连接」与运行状态反馈。

## What Changes

- 新增受保护接口 `GET /config/llm` 与 `PUT /config/llm`：读取/更新 LLM 模型配置。apiKey 采用写掩码语义——GET 只返回 `apiKeyConfigured` 与 `apiKeyLast4`，PUT 中 apiKey 为空表示保持现有值；配置写入 `config/user.project.json`（原子写 + 写后校验，非法时回滚）。
- 保存成功后后端重置运行时 provider 缓存（llm/embedding/rerank/聊天/诊断 runner、上下文窗口、检索缓存），下一次请求即使用新配置，无需重启。
- 「测试连接」与运行状态面板复用现有 `GET /config/check`，不新增 check 端点。
- 新增 `PUT /auth/profile`（修改昵称）与 `PUT /auth/password`（校验当前密码后改密码，成功后吊销该用户全部会话）。
- 前端新增个人中心：左下角头像可点击进入；桌面左侧菜单 + 内容双栏布局，窄屏底栏新增「我的」入口、菜单变顶部横条；中文界面沿用现有设计体系。
- 新增错误码 `AUTH_PASSWORD_MISMATCH`、`MODEL_CONFIGURATION_INVALID`（TS 契约、Python 错误目录、前端文案映射三处同步）。

## Impact

- 后端：`super_ai/llm/config_writer.py`（新）、`super_ai/project_config.py`、`super_ai/auth/repositories.py`、`super_ai/auth/sqlite.py`、`super_ai/auth/service.py`、`super_ai/api/app.py`、`super_ai/error_catalog.py`、新增 `tests/test_model_config_api.py` 与 `tests/test_profile_api.py`。
- 契约：`packages/api-contracts/src/model-configuration.ts`（新）、`auth.ts`、`errors.ts`、`openapi.ts`、`index.ts`、`tests/api-contracts.test.ts`。
- 前端：`src/router/index.ts`、`src/layouts/WorkspaceLayout.vue`、`src/components/WorkspaceNavigation.vue`、新建 `views/ProfileView.vue`/`ModelConfigView.vue`/`PersonalInfoView.vue`/`ProfileAboutView.vue`、新建 `src/settings/modelConfigClient.ts` 与 `src/stores/modelConfig.ts`、`src/authClient.ts`、`src/stores/auth.ts`、`src/ui/userFacingError.ts`、新增/扩展若干测试。
- 文档：`docs/operations-and-monitoring.md`、`README.md`。
- 非目标：不改配置文件模板（llm 段已含全部字段、模板密钥保持为空）；不从环境变量读配置；不支持 apiKey 以外的多 provider 切换；不做未保存表单的连接测试（测试的是已保存配置）；不新增数据库迁移（users 表已有 display_name/password_hash/updated_at）。
