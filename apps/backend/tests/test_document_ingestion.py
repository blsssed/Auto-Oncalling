"""Document extraction formats and configurable chunk sizing."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from super_ai.documents import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    ChunkingSettings,
    chunk_document_text,
    extract_indexable_text,
    load_chunking_settings,
)
from super_ai.project_config import ProjectConfigurationError


def test_plain_text_document_is_extracted() -> None:
    assert extract_indexable_text("runbook.txt", b"  restart the worker\n") == (
        "restart the worker"
    )


def test_plain_text_document_requires_utf8_and_content() -> None:
    with pytest.raises(ValueError, match="TXT 文件必须使用 UTF-8"):
        extract_indexable_text("runbook.txt", b"\xff\xfe")
    with pytest.raises(ValueError, match="TXT 文件没有可索引文本"):
        extract_indexable_text("runbook.txt", b"   \n")


def test_markdown_document_keeps_existing_behavior() -> None:
    assert extract_indexable_text("runbook.md", b"# Restart\n\nCheck readiness.") == (
        "# Restart\n\nCheck readiness."
    )


def test_encrypted_pdf_reports_actionable_error() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("secret")
    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(ValueError, match="已加密"):
        extract_indexable_text("secret.pdf", buffer.getvalue())


def test_blank_pdf_mentions_scanned_documents() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(ValueError, match="可能是扫描件"):
        extract_indexable_text("scan.pdf", buffer.getvalue())


def test_corrupt_pdf_reports_invalid_file() -> None:
    with pytest.raises(ValueError, match="无法读取"):
        extract_indexable_text("broken.pdf", b"not a pdf")


def test_chunking_settings_default_when_section_is_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps({"vectorStore": {}}), encoding="utf-8")

    assert load_chunking_settings(config_path=config_path) == ChunkingSettings(
        chunk_size=DEFAULT_CHUNK_SIZE,
        chunk_overlap=DEFAULT_CHUNK_OVERLAP,
    )


def test_chunking_settings_read_configured_values(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps({"documentChunking": {"chunkSize": 600, "chunkOverlap": 80}}),
        encoding="utf-8",
    )

    settings = load_chunking_settings(config_path=config_path)

    assert settings == ChunkingSettings(chunk_size=600, chunk_overlap=80)
    chunks = chunk_document_text(
        "one two three four five six seven eight",
        strategy="legacy-word",
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    assert chunks[0].start == 0


@pytest.mark.parametrize(
    "section",
    [
        {"chunkSize": 0, "chunkOverlap": 0},
        {"chunkSize": 200, "chunkOverlap": -1},
        {"chunkSize": 200, "chunkOverlap": 200},
        {"chunkSize": True, "chunkOverlap": 0},
    ],
)
def test_chunking_settings_reject_invalid_values(
    section: dict[str, object], tmp_path: Path
) -> None:
    config_path = tmp_path / "project.json"
    config_path.write_text(json.dumps({"documentChunking": section}), encoding="utf-8")

    with pytest.raises(ProjectConfigurationError):
        load_chunking_settings(config_path=config_path)
