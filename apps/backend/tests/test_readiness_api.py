from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

import super_ai.api.app as api_app
from super_ai.api.app import create_app
from super_ai.llm import LlmProvider, LlmReadinessResult
from super_ai.vector_store import MilvusHealthCheckResult


class FakeVectorStore:
    def __init__(self, *, ok: bool = True, error: Exception | None = None) -> None:
        self.ok = ok
        self.error = error
        self.calls = 0

    def health_check(self) -> MilvusHealthCheckResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return MilvusHealthCheckResult(
            ok=self.ok,
            uri="http://milvus.test:19530",
            collection_name="knowledge_chunks",
            latency_ms=2.0,
            error=None if self.ok else "Milvus unavailable",
        )


class FakeLlmProvider:
    async def check_readiness(self) -> LlmReadinessResult:
        return LlmReadinessResult(
            ok=True,
            provider="qwen-openai",
            model="qwen-test",
            base_url="https://provider.test/v1",
            latency_ms=12.0,
        )


class FakeMcpClient:
    async def readiness(self) -> dict[str, object]:
        return {"ok": True, "endpoint": "http://mcp.test/sse", "toolCount": 3, "error": None}


def fake_mcp_client(_request: object) -> FakeMcpClient:
    return FakeMcpClient()


@pytest.mark.asyncio
async def test_readiness_aggregates_safe_component_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # 指向临时数据库：测试不依赖操作者本地 config 指向的真实数据库文件。
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'ready1.sqlite3').as_posix()}",
        vector_store=FakeVectorStore(),
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", fake_mcp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "ready"
    assert payload["dependencies"]["sqlite"]["ok"] is True
    assert payload["dependencies"]["llm"]["model"] == "qwen-test"
    assert "apiKey" not in str(payload)


@pytest.mark.asyncio
async def test_readiness_reports_degraded_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'ready2.sqlite3').as_posix()}",
        vector_store=FakeVectorStore(ok=False),
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", fake_mcp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")

    assert response.status_code == 503
    payload = response.json()["data"]
    assert payload["status"] == "degraded"
    assert payload["dependencies"]["sqlite"]["ok"] is True
    assert payload["dependencies"]["mcp"]["ok"] is True


@pytest.mark.asyncio
async def test_health_is_liveness_without_dependency_probes() -> None:
    vector_store = FakeVectorStore(error=RuntimeError("must not be called"))
    app = create_app(vector_store=vector_store)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"
    assert "dependencies" not in response.json()["data"]
    assert vector_store.calls == 0


@pytest.mark.asyncio
async def test_config_check_reports_safe_configuration_and_dependency_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    secret = "readiness-test-api-key"
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "backend": {"memoryDatabaseUrl": "sqlite+aiosqlite:///:memory:"},
                "llm": {
                    "provider": "qwen-openai",
                    "apiKey": secret,
                    "baseUrl": "https://provider.test/v1",
                    "chatModel": "qwen-test",
                    "embeddingModel": "embedding-test",
                        "embeddingDimensions": 2,
                        "rerankModel": "rerank-test",
                        "rerankUrl": "https://provider.test/rerank",
                        "modelCapabilities": {
                            "qwen-test": {"contextWindowTokens": 131072}
                        },
                    "temperature": 0.1,
                    "timeoutSeconds": 3,
                    "maxRetries": 1,
                },
                "vectorStore": {
                    "uri": "http://milvus.test:19530",
                    "collectionName": "knowledge_chunks",
                    "vectorDimension": 2,
                    "indexType": "HNSW",
                    "metricType": "COSINE",
                    "timeoutSeconds": 3,
                    "indexParams": {"M": 16},
                    "searchParams": {"ef": 64},
                },
                "mcp": {
                    "clsSseUrl": "http://mcp.test/sse",
                    "timeoutSeconds": 3,
                    "retries": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:",
        project_config_path=config_path,
        vector_store=FakeVectorStore(),
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", fake_mcp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/config/check")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["configuration"]["llm"]["model"] == "qwen-test"
    assert payload["dependencies"]["sqlite"]["ok"] is True
    # langfuse 段缺失时按“禁用”处理：valid=true，整体保持 200。
    assert payload["configuration"]["langfuse"] == {
        "valid": True,
        "enabled": False,
        "error": None,
    }
    assert secret not in response.text


@pytest.mark.asyncio
async def test_config_check_reports_langfuse_enabled_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    public_key = "pk-lf-readiness"
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "backend": {"memoryDatabaseUrl": "sqlite+aiosqlite:///:memory:"},
                "llm": {
                    "provider": "qwen-openai",
                    "apiKey": "readiness-test-api-key",
                    "baseUrl": "https://provider.test/v1",
                    "chatModel": "qwen-test",
                    "embeddingModel": "embedding-test",
                    "embeddingDimensions": 2,
                    "rerankModel": "rerank-test",
                    "rerankUrl": "https://provider.test/rerank",
                    "modelCapabilities": {"qwen-test": {"contextWindowTokens": 131072}},
                    "temperature": 0.1,
                    "timeoutSeconds": 3,
                    "maxRetries": 1,
                },
                "vectorStore": {
                    "uri": "http://milvus.test:19530",
                    "collectionName": "knowledge_chunks",
                    "vectorDimension": 2,
                    "indexType": "HNSW",
                    "metricType": "COSINE",
                    "timeoutSeconds": 3,
                    "indexParams": {"M": 16},
                    "searchParams": {"ef": 64},
                },
                "mcp": {
                    "clsSseUrl": "http://mcp.test/sse",
                    "timeoutSeconds": 3,
                    "retries": 1,
                },
                "langfuse": {
                    "enabled": True,
                    "publicKey": public_key,
                    "secretKey": "sk-lf-readiness",
                    "host": "https://langfuse.example.test",
                },
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:",
        project_config_path=config_path,
        vector_store=FakeVectorStore(),
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", fake_mcp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/config/check")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["configuration"]["langfuse"] == {
        "valid": True,
        "enabled": True,
        "host": "https://langfuse.example.test",
        "error": None,
    }
    assert public_key not in response.text
    assert "sk-lf-readiness" not in response.text


@pytest.mark.asyncio
async def test_config_check_reports_langfuse_invalid_without_leaking_keys(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "backend": {"memoryDatabaseUrl": "sqlite+aiosqlite:///:memory:"},
                "llm": {
                    "provider": "qwen-openai",
                    "apiKey": "readiness-test-api-key",
                    "baseUrl": "https://provider.test/v1",
                    "chatModel": "qwen-test",
                    "embeddingModel": "embedding-test",
                    "embeddingDimensions": 2,
                    "rerankModel": "rerank-test",
                    "rerankUrl": "https://provider.test/rerank",
                    "modelCapabilities": {"qwen-test": {"contextWindowTokens": 131072}},
                    "temperature": 0.1,
                    "timeoutSeconds": 3,
                    "maxRetries": 1,
                },
                "langfuse": {"enabled": True, "publicKey": "", "secretKey": ""},
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:",
        project_config_path=config_path,
        vector_store=FakeVectorStore(),
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", fake_mcp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/config/check")

    assert response.status_code == 503
    payload = response.json()["data"]
    assert payload["configuration"]["langfuse"]["valid"] is False
    assert "langfuse" in payload["status"] or payload["status"] == "degraded"


@pytest.mark.asyncio
async def test_config_check_surfaces_invalid_configuration_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "invalid-project.json"
    config_path.write_text("{}", encoding="utf-8")
    app = create_app(
        database_url="sqlite+aiosqlite:///:memory:",
        project_config_path=config_path,
        vector_store=FakeVectorStore(),
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", fake_mcp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/config/check")

    assert response.status_code == 503
    payload = response.json()["data"]
    assert payload["status"] == "degraded"
    assert payload["configuration"]["sqlite"]["valid"] is False
    assert payload["configuration"]["llm"]["valid"] is False
    assert payload["configuration"]["milvus"]["valid"] is False
    assert payload["configuration"]["mcp"]["valid"] is False
