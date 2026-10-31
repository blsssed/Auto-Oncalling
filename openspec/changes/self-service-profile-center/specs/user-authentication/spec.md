## ADDED Requirements

### Requirement: 更新个人资料

系统 SHALL 提供受认证保护的 `PUT /auth/profile` 接口用于更新当前用户的昵称。昵称 MUST 非空且不超过 160 字符；更新后 `GET /auth/me` MUST 返回新昵称。

#### Scenario: 更新昵称

- **WHEN** 已认证客户端提交合法 `PUT /auth/profile`
- **THEN** 后端 MUST 更新并返回当前用户信息（含新昵称），随后的 `GET /auth/me` MUST 一致反映

#### Scenario: 非法昵称

- **WHEN** 提交的昵称为空白字符串
- **THEN** 后端 MUST 返回校验错误且 MUST NOT 修改用户记录

### Requirement: 修改密码

系统 SHALL 提供受认证保护的 `PUT /auth/password` 接口。修改时 MUST 校验当前密码（不匹配返回 `AUTH_PASSWORD_MISMATCH`），新密码 MUST 至少 8 字符；成功后密码 MUST 以 Argon2 重哈希，且该用户的全部认证会话 MUST 被吊销。

#### Scenario: 成功修改密码

- **WHEN** 已认证客户端提交正确的当前密码与合法新密码
- **THEN** 后端 MUST 更新密码哈希并吊销该用户全部会话；旧 access token 随后的请求 MUST 返回 `AUTH_SESSION_REVOKED`，新密码 MUST 可登录，旧密码 MUST 不可登录

#### Scenario: 当前密码错误

- **WHEN** 提交的当前密码与存储哈希不匹配
- **THEN** 后端 MUST 返回 `AUTH_PASSWORD_MISMATCH` 且 MUST NOT 修改密码或会话
