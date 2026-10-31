# 设计：文档摄取增强

## 决策

### 1. `.txt` 复用文本 MIME 白名单

`.txt` 与 `.md` 都按 UTF-8 文本处理，浏览器通常上报 `text/plain`、空 MIME 或 `application/octet-stream`。后端沿用 `MARKDOWN_DOCUMENT_MIME_TYPES` 校验，单独暴露 `TEXT_DOCUMENT_EXTENSIONS` 以便错误信息区分 Markdown / TXT。

### 2. PDF 错误按可操作原因分类

- 解析器无法打开文件 → “无法读取，请上传有效的 .pdf”。
- `reader.is_encrypted` → “已加密，请先解除密码保护”。
- 页面全部提取失败 → “页面文本无法解析，文件可能已损坏”。
- 页面可解析但没有文本 → “可能是扫描件”，并给出 Markdown/TXT 备选。

分类只改变错误提示，不引入 OCR；不伪造文本。

### 3. 全局分块默认值与文档级配置共存

`documentChunking` 只作为 `DocumentIndexingService` 的默认 `chunk_size` / `chunk_overlap`。上传时用户选择并持久化在文档 metadata 中的策略与参数继续优先（`_chunking_kwargs`），不会因为部署配置变化而改写既有文档的索引语义。

配置在首次使用时读取并按 app 实例缓存；修改后需重启后端生效，与检索缓存等本地配置行为一致。

## 风险

- 既有知识库文档不会自动重新分块；如需生效需重新索引。
- `.txt` 不做编码探测，非 UTF-8 文本会得到明确错误而不是猜测编码。
