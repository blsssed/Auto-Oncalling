import { DOCUMENT_UPLOAD_POLICY } from "@agent-py/api-contracts";

const MARKDOWN_MIME_TYPES = new Set(["", "application/octet-stream", "text/markdown", "text/plain"]);
const PDF_MIME_TYPES = new Set(["", "application/octet-stream", "application/pdf"]);

export function validateKnowledgeDocumentFile(file: File): string | null {
  const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
  if (file.size > DOCUMENT_UPLOAD_POLICY.maxSizeBytes) {
    return `文件大小不能超过 ${formatBytes(DOCUMENT_UPLOAD_POLICY.maxSizeBytes)}。`;
  }
  if (!DOCUMENT_UPLOAD_POLICY.allowedExtensions.includes(extension as never)) {
    return supportedFormatsMessage();
  }
  if ((extension === ".md" || extension === ".txt") && !MARKDOWN_MIME_TYPES.has(file.type)) {
    const label = extension === ".txt" ? "TXT" : "Markdown";
    return `${label} 文件类型不符合要求（当前为 ${file.type}），请上传 ${extension} 文件。`;
  }
  if (extension === ".pdf" && !PDF_MIME_TYPES.has(file.type)) {
    return `PDF 文件类型不符合要求（当前为 ${file.type}），请上传有效的 .pdf 文件。`;
  }
  return null;
}

export function supportedFormatsMessage(): string {
  return `仅支持 Markdown(.md)、TXT(.txt) 与 PDF(.pdf)，单个文件不超过 ${formatBytes(DOCUMENT_UPLOAD_POLICY.maxSizeBytes)}。`;
}

export function formatBytes(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}
