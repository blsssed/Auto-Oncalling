# 任务

## 1. 拆分 Embedding / Rerank 配置

- [x] `LlmProviderConfig` 新增独立 embedding/rerank key 与 base URL，key 字段 `repr=False`。
- [x] 解析可选 `llm.embedding` / `llm.rerank`，逐字段回退到顶层配置。
- [x] 非对象节、非正整数 `dimensions` 返回不含密钥的配置错误。
- [x] provider 工厂使用有效 embedding/rerank 凭据与端点。
- [x] 两个配置模板新增空节，凭据保持为空。
- [x] 测试覆盖完整覆盖、逐字段回退、非法配置与密钥不进入 `repr`。
- [x] 修正默认配置测试对操作者本地 `config/user.project.json` 的隐式依赖。

## 2. 诊断任务失败终态

- [x] runner 构建放入独立 `try`。
- [x] 构建异常时把非终态任务写为 `failed`，记录 `completed_at` 与脱敏错误。
- [x] 不覆盖 `stream` 已写入的 `failed`/`succeeded`/`cancelled`。
- [x] 异常继续向上抛出，保留后台 job 失败/重试语义。
- [x] 回归测试断言任务不再残留 `accepted` 且错误不含测试密钥。

## 3. 本地日志真实读取

- [x] `logStore` 新增 `format`/`maxBytes`/`maxRecords` 与工厂校验。
- [x] 支持 JSONL、JSON 数组、单文件、目录与 glob。
- [x] 目录按 mtime 倒序；JSONL 尾部有界读取；`maxRecords` 截断。
- [x] `time` 归一化为 `timestamp`；坏行跳过并计数；结果继续脱敏与作用域过滤。
- [x] legacy `Query` 子集过滤（`service`/`incident`/`trace`/`level`/`text`/`event`/`message`/`host`/`request_id`）。
- [x] 测试覆盖 JSONL、目录/glob、`maxBytes`、`maxRecords`、epoch 时间、坏行、非法语法与工厂校验。

## 4. 统一日志查询模型

- [x] 新增冻结 `LogQuery` 与 `from_step`、`to_arguments`、`to_cls_arguments`、`matches`。
- [x] 结构化参数优先，旧 `Query` 回退；scope 冲突与时间无交集失败；`limit` 1–100。
- [x] CLS adapter 翻译为 `SearchLog` 参数；`FileLogStore.build_args` 输出结构化参数。
- [x] `scoped_step` 保留兼容包装与旧输出形状；CLS 宽松模式保留 legacy passthrough。
- [x] planner/replanner prompt 描述结构化字段并禁止 CLS CQL、管道、括号、`OR`/`NOT`。
- [x] 新增 `test_log_query.py`，并补充 CLS/本地 adapter 与端到端诊断测试。

## 5. 文档与验证

- [x] 后端 README 说明独立 embedding/rerank 配置与本地日志/统一查询字段。
- [x] 创建本 OpenSpec change 与 delta spec。
- [x] 同步 `docs/changes/` WIKI 并运行 `npm run docs:build`。
- [x] `uv run pytest tests/test_llm_provider.py tests/test_environment_examples.py`
- [x] `uv run pytest tests/test_log_query.py tests/test_log_store.py tests/test_aiops_diagnostics.py tests/test_auto_diagnosis.py tests/test_auto_oncall.py`
- [x] `uv run ruff check .`
- [x] `uv run pyright`
- [x] `uv run pytest`（全量，连续 8 轮通过）
- [ ] `openspec validate --all`（当前环境未安装 CLI，待可执行时补跑）
- [ ] 真实 RAG 索引/检索验证（等待可用的 Embedding 供应商凭据）
