# 任务

## 实现

- [x] 上传策略新增 `.txt`，同步共享契约、后端校验与前端提示。
- [x] PDF 提取区分加密、损坏与扫描件错误。
- [x] 新增 `documentChunking` 配置与 `load_chunking_settings` 校验。
- [x] `DocumentIndexingService` 默认分块参数接入配置，文档级配置继续优先。
- [x] README 同步文档格式与分块配置说明。

## 验证

- [x] `uv run pytest tests/test_document_ingestion.py tests/test_knowledge_documents_api.py tests/test_document_indexing.py`
- [x] `uv run pytest`
- [x] `uv run ruff check .`
- [x] `uv run pyright`
- [x] `npm run contracts:typecheck` 与 api-contracts 测试
- [x] `npm run frontend:typecheck`、前端测试与 `npm run frontend:build`
- [ ] `openspec validate --all`（当前环境未安装 OpenSpec CLI，待可执行时补跑）
