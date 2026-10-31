## MODIFIED Requirements

### Requirement: Markdown and PDF indexable text extraction

系统 SHALL 对允许上传的 Markdown、UTF-8 纯文本和 PDF 文档生成可索引文本。Markdown 与 TXT SHALL 以 UTF-8 文本读取；PDF SHALL 使用现成 PDF 文本提取库获取文本，不执行 OCR。

#### Scenario: Markdown text is extracted

- **WHEN** user 上传 UTF-8 Markdown 文件
- **THEN** 后端 MUST 将该 Markdown 正文保存为可索引文本。

#### Scenario: Plain text is extracted

- **WHEN** user 上传 UTF-8 TXT 文件
- **THEN** 后端 MUST 将该文本正文保存为可索引文本。

#### Scenario: PDF text is extracted

- **WHEN** user 上传包含可选择文本的 PDF 文件
- **THEN** 后端 MUST 使用 PDF 文本提取库保存可索引文本，而不是把 PDF 字节当 UTF-8 文本解码。

#### Scenario: PDF is encrypted

- **WHEN** user 上传已加密的 PDF 文件
- **THEN** 后端 MUST 使用统一参数错误拒绝上传，并提示先解除密码保护。

#### Scenario: PDF is corrupt or pages cannot be parsed

- **WHEN** user 上传损坏或页面文本无法解析的 PDF 文件
- **THEN** 后端 MUST 使用统一参数错误拒绝上传，并提示文件可能损坏、需要重新导出。

#### Scenario: PDF has no extractable text

- **WHEN** user 上传可解析但没有文本层的 PDF 文件
- **THEN** 后端 MUST 使用统一参数错误拒绝上传，并说明该 PDF 可能是扫描件、建议转换为 Markdown/TXT。

## ADDED Requirements

### Requirement: Configurable default chunk sizing

系统 SHALL 允许通过 `documentChunking.chunkSize` 与 `documentChunking.chunkOverlap` 配置未单独指定策略的文档默认分块参数，并 SHALL 继续优先使用文档上传时保存的 chunking 配置。

#### Scenario: Deployment overrides default chunk size

- **WHEN** 项目配置提供合法的 `documentChunking` 值且文档没有自己的 chunking 配置
- **THEN** 索引任务 MUST 使用配置的分块大小与重叠。

#### Scenario: Document configuration takes precedence

- **WHEN** 文档 metadata 保存了上传时选择的策略或字符参数
- **THEN** 索引任务 MUST 使用文档自身配置，而不是覆盖为全局默认值。

#### Scenario: Invalid chunking configuration

- **WHEN** `chunkSize` 不是正数、`chunkOverlap` 为负数或不小于 `chunkSize`
- **THEN** 后端 MUST 在读取配置时报告明确的配置错误。
