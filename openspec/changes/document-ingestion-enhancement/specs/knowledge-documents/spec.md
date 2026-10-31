## MODIFIED Requirements

### Requirement: Upload policy

系统 SHALL 在共享 API 合同中定义文件大小、文件类型、重复上传和覆盖策略。上传文件 SHALL 仅支持 Markdown `.md`、UTF-8 纯文本 `.txt` 与 PDF `.pdf` 文档。

#### Scenario: Oversized file is rejected

- **WHEN** 上传文件超过配置的最大文件大小
- **THEN** API MUST 使用统一的验证错误响应拒绝它，并提供明确的大小限制说明。

#### Scenario: 不支持的文件类型被拒绝

- **WHEN** 上传的文件扩展名不是 `.md`、`.txt` 或 `.pdf`，或 PDF/TXT 的 MIME 类型明显不符合要求
- **THEN** API MUST 使用统一的验证错误响应拒绝它，并说明只支持 Markdown、TXT 与 PDF。

#### Scenario: Markdown browser MIME variants are accepted

- **WHEN** user 上传 `.md` 文件且浏览器提供 `text/markdown`、`text/plain`、空 MIME 或 `application/octet-stream`
- **THEN** API MUST 接受该文件并按 Markdown 文档保存。

#### Scenario: Plain text document is accepted

- **WHEN** user 上传 UTF-8 `.txt` 文件且浏览器提供 `text/plain`、空 MIME 或 `application/octet-stream`
- **THEN** API MUST 接受该文件并保存其正文作为可索引文本。

#### Scenario: Duplicate upload without overwrite is rejected

- **WHEN** 一个 user 上传了一个内容哈希已在相同知识库中存在的文档，且 `overwrite` 不为真
- **THEN** API MUST 使用统一的业务冲突错误响应拒绝它。

#### Scenario: Duplicate upload with overwrite replaces prior document

- **WHEN** 一个 user 上传了带有 `overwrite=true` 的重复文档
- **THEN** 系统 MUST 移除该哈希值的先前文档向量，将先前文档元数据标记为已删除，并为上传创建一个新的文档记录。
