# 配置与运维

应用只读取本地 `config/project.json` 和可选的 `config/user.project.json`，不读取本机环境变量。两个文件都被 Git 忽略；仓库只保留不含真实凭据的模板。不要为本项目创建 `.env` 文件，也不要提交本地配置。

首次使用时，在仓库根目录执行：

```bash
cp config/project.template.json config/project.json
cp config/user.project.template.json config/user.project.json
```

## 项目交付后的个人配置

在本地 `config/user.project.json` 中填写使用者自己的模型密钥、CLS 凭据和 CLS 日志目标。其他运行参数可在本地 `config/project.json` 中调整：

| 配置字段 | 替换为 |
| --- | --- |
| `llm.apiKey` | 使用者自己的模型服务密钥 |
| `clsMcpServer.secretId` | 使用者自己的 CLS 凭据 ID |
| `clsMcpServer.secretKey` | 使用者自己的 CLS 凭据密钥 |
| `clsLogUpload.region` | 使用者自己的 CLS 地域 |
| `clsLogUpload.logsetId` | 使用者自己的 CLS 日志集 ID |
| `clsLogUpload.topicId` | 使用者自己的 CLS 主题 ID |
| `langfuse.publicKey` / `langfuse.secretKey` | 使用者自己的 Langfuse 云项目密钥（可选） |

模板中的凭据字段必须保持为空。即使仓库是私有仓库，也不要提交真实密钥；已暴露的密钥应在对应云平台立即轮换。

## 个人中心自助模型配置

除手改本地 JSON 配置外，使用者还可以在前端「个人中心 → 模型配置」（左下角头像进入）自助修改 LLM 配置：`apiKey`、`baseUrl`、`chatModel` 与上下文窗口、`embeddingModel` 与维度、`rerankModel`/`rerankUrl`、温度、超时和重试次数；以及可选的 Langfuse 追踪段：`enabled` 开关、`host`、`publicKey` 与 `secretKey`。该页面调用 `GET / PUT /config/llm`，写入本地 `config/user.project.json` 并**立即热生效，无需重启后端**（下一个请求即用新配置重建 LLM/Embedding/Rerank provider、检索缓存与 Langfuse tracing provider）。

安全与语义约定：

- `GET /config/llm` 永不回传密钥本体：LLM `apiKey` 与 Langfuse `publicKey`/`secretKey` 都只返回 `*Configured` 与 `*Last4`；`/config/check` 同样不序列化任何密钥。
- 保存时 `apiKey` 与 Langfuse 密钥留空表示保持现有值；当前未配置任何密钥时留空会返回 `VALIDATION_MISSING_FIELD`。启用 Langfuse 追踪时必须提供（或已配置）`publicKey` 与 `secretKey`；关闭追踪只改 `enabled`，已保存的密钥保留以便随时重新启用。
- 保存成功后 `modelCapabilities` 中的上下文窗口会随对话模型自动同步；写入采用原子替换，写后校验（LLM 配置 + Langfuse 配置）失败会自动回滚为原配置并返回 `MODEL_CONFIGURATION_INVALID`。
- 修改中的表单未保存时，「测试连接」不会执行；保存后它复用 `GET /config/check` 展示配置校验与 LLM 依赖探测结果。

「个人中心 → 个人信息」支持修改昵称（`PUT /auth/profile`）与修改密码（`PUT /auth/password`）。修改密码需验证当前密码，成功后**该用户全部登录会话被吊销**，需要用新密码重新登录。

## Langfuse 追踪（可选）

Langfuse 追踪默认关闭。启用方式：在本地 `config/project.json`（或 `user.project.json`）中将 `langfuse.enabled` 设为 `true`，并填入 [app.langfuse.com](https://app.langfuse.com) 项目的 `publicKey` / `secretKey`；`host` 默认 `https://cloud.langfuse.com`，一般无需修改。

启用后，聊天链、AIOps 诊断链和聊天记忆压缩的 LLM 调用会上报到 Langfuse 控制台，trace 名称分别为 `chat-agent`、`aiops-diagnosis`、`chat-memory-compaction`；每个 trace 的 metadata 带 `requestId`，可与本地 JSON 日志互查。配置缺失、`enabled=false` 或 Langfuse SDK/网络故障时自动静默降级，不影响聊天与诊断的正常运行。`GET /api/config/check` 会报告 `langfuse` 段的有效性（不序列化密钥）。

## 真实日志与本地告警样例

真实 CLS 日志上传和本地 active-alert 演示属于显式运维流程，不是常规应用启动的一部分。请遵循[真实 CLS 日志与告警教程](tutorials/real-log-and-alert.md)，分别执行其中的日志上传脚本和本地告警命令。
