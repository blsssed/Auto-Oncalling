# 文档摄取增强

## Why

知识库目前只接受 `.md` 与 `.pdf`。运维常见纯文本日志片段、导出文本和事故记录无法直接入库；同时 PDF 的加密、损坏与扫描件都落在同一句“没有可索引文本”，用户难以判断如何修复。默认分块参数也固定在代码常量中，无法按知识库或部署环境调整。

## What Changes

- 上传策略新增 `.txt`（UTF-8 纯文本），共享契约、后端校验与前端上传入口同步。
- PDF 提取区分：加密、文件损坏/页面解析失败、扫描件或纯图片，分别返回可操作的错误提示。
- 新增 `documentChunking` 配置段（`chunkSize`、`chunkOverlap`），作为未单独选择策略的文档默认值；文档自身保存的 chunking 配置仍然优先。
- 更新 README、真实告警教程与相关测试。

## Impact

- 后端：`super_ai/documents/{policy,extraction,indexing}.py`、文档上传校验与索引服务构造。
- 共享契约：`DOCUMENT_UPLOAD_POLICY` 与 OpenAPI 上传说明。
- 前端：文件校验与格式提示。
- 配置：`config/project.template.json` 新增 `documentChunking`。
