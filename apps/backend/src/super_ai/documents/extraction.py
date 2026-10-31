"""Indexable text extraction for supported knowledge documents."""

from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_indexable_text(filename: str, content: bytes) -> str:
    """Extract text from the supported upload formats before indexing."""
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf_text(content)
    return _extract_text_document(content, suffix)


def _extract_text_document(content: bytes, suffix: str) -> str:
    label = "TXT" if suffix == ".txt" else "Markdown"
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} 文件必须使用 UTF-8 编码。") from exc
    normalized = text.strip()
    if not normalized:
        raise ValueError(f"{label} 文件没有可索引文本，请上传包含正文的 {suffix} 文件。")
    return normalized


def _extract_pdf_text(content: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(content))
    except (PdfReadError, ValueError, OSError) as exc:
        raise ValueError("PDF 文件无法读取，请上传有效的 .pdf 文件。") from exc
    if reader.is_encrypted:
        raise ValueError("该 PDF 已加密，请先解除密码保护后再上传。")
    pages: list[str] = []
    failed_pages = 0
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except (PdfReadError, ValueError, KeyError):
            page_text = ""
            failed_pages += 1
        if page_text.strip():
            pages.append(page_text.strip())
    text = "\n\n".join(pages).strip()
    if not text:
        if failed_pages > 0:
            raise ValueError(
                "该 PDF 的页面文本无法解析，文件可能已损坏；请重新导出后再上传。"
            )
        raise ValueError(
            "该 PDF 没有可索引文本，可能是扫描件；请上传包含可选择文本的 PDF，"
            "或转换为 Markdown/TXT。"
        )
    return text
