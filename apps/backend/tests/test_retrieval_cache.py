"""Short-TTL retrieval cache: expiry, bounds, scoping and config."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from super_ai.project_config import ProjectConfigurationError
from super_ai.retrieval import (
    KnowledgeRetrievalTool,
    KnowledgeRetrievalToolInput,
    KnowledgeRetrievalToolResult,
    RetrievalCache,
    RetrievalCacheStats,
    build_retrieval_cache,
)
from test_aiops_diagnostics import FakeEmbeddingModel, FakeRerankModel, FakeVectorStore, sop_hit


def _result(label: str) -> KnowledgeRetrievalToolResult:
    return KnowledgeRetrievalToolResult(query=label, top_k=1, results=[], citations=[])


def test_entries_expire_and_are_bounded() -> None:
    now = [0.0]
    cache = RetrievalCache(ttl_seconds=10.0, max_entries=2, clock=lambda: now[0])
    first = _result("first")
    cache.put("a", first)
    now[0] = 9.0
    assert cache.get("a") is first
    now[0] = 10.0
    assert cache.get("a") is None

    second = _result("second")
    third = _result("third")
    cache.put("a", first)
    cache.put("b", second)
    cache.put("c", third)
    assert cache.get("b") is second
    assert cache.get("c") is third
    assert cache.get("a") is None
    assert cache.stats() == RetrievalCacheStats(hits=3, misses=2, size=2)

    cache.invalidate()
    assert cache.stats().size == 0


def test_cache_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError):
        RetrievalCache(ttl_seconds=0)
    with pytest.raises(ValueError):
        RetrievalCache(max_entries=0)


def test_build_retrieval_cache_reads_config(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"

    config_path.write_text("{}", encoding="utf-8")
    assert isinstance(build_retrieval_cache(config_path=config_path), RetrievalCache)

    config_path.write_text(
        json.dumps({"retrievalCache": {"enabled": False}}), encoding="utf-8"
    )
    assert build_retrieval_cache(config_path=config_path) is None

    config_path.write_text(
        json.dumps({"retrievalCache": {"enabled": True, "ttlSeconds": 5, "maxEntries": 4}}),
        encoding="utf-8",
    )
    cache = build_retrieval_cache(config_path=config_path)
    assert isinstance(cache, RetrievalCache)

    for invalid in (
        {"enabled": "yes"},
        {"ttlSeconds": 0},
        {"ttlSeconds": "30"},
        {"maxEntries": 0},
    ):
        config_path.write_text(json.dumps({"retrievalCache": invalid}), encoding="utf-8")
        with pytest.raises(ProjectConfigurationError):
            build_retrieval_cache(config_path=config_path)


@pytest.mark.asyncio
async def test_tool_serves_repeat_queries_from_cache_per_owner() -> None:
    cache = RetrievalCache(ttl_seconds=30.0)
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeVectorStore([sop_hit("owner")]),
        rerank_model=FakeRerankModel(),
        cache=cache,
    )
    request = KnowledgeRetrievalToolInput(query="CPU saturation", top_k=3)

    first = await tool.run(
        request, owner_user_id="owner", accessible_knowledge_base_ids=("kb_owner",)
    )
    second = await tool.run(
        request, owner_user_id="owner", accessible_knowledge_base_ids=("kb_owner",)
    )
    other = await tool.run(
        request, owner_user_id="other", accessible_knowledge_base_ids=("kb_owner",)
    )

    assert second is first
    assert other is not first
    assert cache.stats() == RetrievalCacheStats(hits=1, misses=2, size=2)


@pytest.mark.asyncio
async def test_tool_bypasses_cache_when_disabled() -> None:
    tool = KnowledgeRetrievalTool(
        embedding_model=FakeEmbeddingModel(),
        vector_store=FakeVectorStore([sop_hit("owner")]),
        rerank_model=FakeRerankModel(),
    )
    request = KnowledgeRetrievalToolInput(query="CPU saturation")
    first = await tool.run(request, owner_user_id="owner", accessible_knowledge_base_ids=())
    second = await tool.run(request, owner_user_id="owner", accessible_knowledge_base_ids=())
    assert first is not second
