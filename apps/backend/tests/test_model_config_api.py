from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

import super_ai.api.app as api_app
from super_ai.api.app import create_app
from super_ai.llm import LlmProvider, LlmReadinessResult
from super_ai.vector_store import MilvusHealthCheckResult

_SECRET = "sk-test-1234567890abcd"


class FakeVectorStore:
    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(
            ok=True,
            uri="http://milvus.test:19530",
            collection_name="knowledge_chunks",
            latency_ms=2.0,
            error=None,
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


def _fake_mcp_client(_request: object) -> FakeMcpClient:
    return FakeMcpClient()


def _base_config(*, provider: str = "qwen-openai") -> dict[str, object]:
    return {
        "backend": {"memoryDatabaseUrl": "sqlite+aiosqlite:///:memory:"},
        "llm": {
            "provider": provider,
            "apiKey": "",
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
    }


def _write_configs(
    tmp_path: Path,
    *,
    base: dict[str, object] | None = None,
    user: dict[str, object] | None = None,
) -> Path:
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(base if base is not None else _base_config()),
        encoding="utf-8",
    )
    if user is not None:
        (tmp_path / "user.project.json").write_text(json.dumps(user), encoding="utf-8")
    return config_path


def _put_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "baseUrl": "https://provider.test/v2",
        "chatModel": "qwen-new",
        "contextWindowTokens": 65536,
        "embeddingModel": "embedding-new",
        "embeddingDimensions": 4,
        "rerankModel": "rerank-new",
        "rerankUrl": "https://provider.test/rerank2",
        "temperature": 0.5,
        "timeoutSeconds": 30,
        "maxRetries": 3,
    }
    body.update(overrides)
    return body


async def _register_token(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/auth/register",
        json={
            "email": "timi@example.com",
            "displayName": "Timi",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 201
    return cast(str, response.json()["data"]["accessToken"])


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "model-config-api.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"


@pytest.mark.asyncio
async def test_get_llm_configuration_returns_masked_view_without_leaking_key(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path, user={"llm": {"apiKey": _SECRET}})
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.get("/config/llm", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["apiKeyConfigured"] is True
    assert data["apiKeyLast4"] == "abcd"
    assert data["chatModel"] == "qwen-test"
    assert data["contextWindowTokens"] == 131072
    assert "apiKey" not in data
    assert _SECRET not in response.text


@pytest.mark.asyncio
async def test_get_llm_configuration_degrades_when_key_not_configured(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path)
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.get("/config/llm", headers=_auth_headers(token))
        anonymous = await client.get("/config/llm")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["apiKeyConfigured"] is False
    assert data["apiKeyLast4"] is None
    assert data["chatModel"] == "qwen-test"
    assert data["contextWindowTokens"] == 131072
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "AUTH_UNAUTHENTICATED"


@pytest.mark.asyncio
async def test_put_llm_configuration_writes_user_file_and_preserves_other_sections(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(
        tmp_path,
        user={"llm": {"apiKey": _SECRET}, "customSection": {"keep": True}},
    )
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/config/llm",
            json=_put_body(),
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["chatModel"] == "qwen-new"
    assert data["contextWindowTokens"] == 65536
    assert data["apiKeyConfigured"] is True
    assert _SECRET not in response.text

    written = json.loads((tmp_path / "user.project.json").read_text(encoding="utf-8"))
    assert written["customSection"] == {"keep": True}
    llm = written["llm"]
    assert llm["apiKey"] == _SECRET
    assert llm["chatModel"] == "qwen-new"
    assert llm["embeddingModel"] == "embedding-new"
    assert llm["rerankModel"] == "rerank-new"
    assert llm["rerankUrl"] == "https://provider.test/rerank2"
    assert llm["modelCapabilities"]["qwen-new"] == {"contextWindowTokens": 65536}


@pytest.mark.asyncio
async def test_put_llm_configuration_with_empty_api_key_keeps_existing(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path, user={"llm": {"apiKey": _SECRET}})
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/config/llm",
            json=_put_body(apiKey=""),
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    written = json.loads((tmp_path / "user.project.json").read_text(encoding="utf-8"))
    assert written["llm"]["apiKey"] == _SECRET


@pytest.mark.asyncio
async def test_put_llm_configuration_requires_api_key_when_none_configured(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path)
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/config/llm",
            json=_put_body(apiKey=""),
            headers=_auth_headers(token),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_MISSING_FIELD"
    assert not (tmp_path / "user.project.json").exists()


@pytest.mark.asyncio
async def test_put_llm_configuration_writes_effective_nested_source_and_preserves_nested_key(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    nested_key = "nested-embedding-key"
    config_path = _write_configs(
        tmp_path,
        user={
            "llm": {
                "apiKey": _SECRET,
                "embedding": {"model": "nested-embedding", "dimensions": 8, "apiKey": nested_key},
            }
        },
    )
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        before = await client.get("/config/llm", headers=_auth_headers(token))
        response = await client.put(
            "/config/llm",
            json=_put_body(),
            headers=_auth_headers(token),
        )

    assert before.json()["data"]["embeddingModel"] == "nested-embedding"
    assert before.json()["data"]["embeddingDimensions"] == 8
    assert response.status_code == 200
    assert response.json()["data"]["embeddingModel"] == "embedding-new"
    assert response.json()["data"]["embeddingDimensions"] == 4

    written = json.loads((tmp_path / "user.project.json").read_text(encoding="utf-8"))
    llm = written["llm"]
    assert llm["embedding"]["model"] == "embedding-new"
    assert llm["embedding"]["dimensions"] == 4
    assert llm["embedding"]["apiKey"] == nested_key
    assert "embeddingModel" not in llm
    assert nested_key not in response.text


@pytest.mark.asyncio
async def test_put_llm_configuration_invalidates_runtime_cache_but_keeps_injected_fakes(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path, user={"llm": {"apiKey": _SECRET}})
    injected_provider = cast(LlmProvider, FakeLlmProvider())
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        llm_provider=injected_provider,
    )
    stale_embedding = object()
    stale_cache = object()
    app.state.embedding_model = stale_embedding
    app.state.rerank_model = object()
    app.state.chat_agent_runner = object()
    app.state.aiops_diagnostic_runner = object()
    app.state.retrieval_cache = stale_cache
    app.state.llm_context_window_tokens = 131072

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/config/llm",
            json=_put_body(),
            headers=_auth_headers(token),
        )

    assert response.status_code == 200
    # 注入的 fake 绝不被覆盖；手动放入的缓存必须全部失效。
    assert app.state.llm_provider is injected_provider
    assert app.state.embedding_model is None
    assert app.state.rerank_model is None
    assert app.state.chat_agent_runner is None
    assert app.state.aiops_diagnostic_runner is None
    assert app.state.llm_context_window_tokens is None
    assert app.state.retrieval_cache is api_app._RETRIEVAL_CACHE_UNSET  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_put_llm_configuration_rolls_back_when_resulting_config_is_invalid(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    # provider 为空会让写后校验失败，从而触发回滚。
    config_path = _write_configs(tmp_path, base=_base_config(provider=""))
    user_path = tmp_path / "user.project.json"
    user_path.write_text(json.dumps({"llm": {"apiKey": _SECRET}}), encoding="utf-8")
    original_bytes = user_path.read_bytes()

    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/config/llm",
            json=_put_body(),
            headers=_auth_headers(token),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MODEL_CONFIGURATION_INVALID"
    assert user_path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_llm_configuration_endpoints_report_conflict_for_broken_user_file(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path)
    user_path = tmp_path / "user.project.json"
    user_path.write_text("not valid json {", encoding="utf-8")

    # 注入 fake 向量库，避免 create_app 在构建默认 Milvus store 时提前读取坏配置。
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        vector_store=FakeVectorStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        get_response = await client.get("/config/llm", headers=_auth_headers(token))
        put_response = await client.put(
            "/config/llm",
            json=_put_body(),
            headers=_auth_headers(token),
        )

    assert get_response.status_code == 409
    assert get_response.json()["error"]["code"] == "BUSINESS_CONFLICT"
    assert put_response.status_code == 409
    assert put_response.json()["error"]["code"] == "BUSINESS_CONFLICT"
    assert user_path.read_text(encoding="utf-8") == "not valid json {"


@pytest.mark.asyncio
async def test_put_llm_configuration_with_langfuse_keys_writes_masked_section(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path, user={"llm": {"apiKey": _SECRET}})
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    app.state.tracing_provider = object()  # 模拟已缓存的旧 tracing provider

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/config/llm",
            json=_put_body(
                langfuseEnabled=True,
                langfuseHost="https://cloud.langfuse.com",
                langfusePublicKey="pk-lf-test-12345678public",
                langfuseSecretKey="sk-lf-test-12345678secret",
            ),
            headers=_auth_headers(token),
        )
        view_after = await client.get("/config/llm", headers=_auth_headers(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["langfuseEnabled"] is True
    assert data["langfusePublicKeyConfigured"] is True
    assert data["langfuseSecretKeyLast4"] == "cret"
    assert "pk-lf-test-12345678public" not in response.text
    assert "sk-lf-test-12345678secret" not in response.text
    assert "pk-lf-test-12345678public" not in view_after.text

    written = json.loads((tmp_path / "user.project.json").read_text(encoding="utf-8"))
    assert written["langfuse"] == {
        "enabled": True,
        "host": "https://cloud.langfuse.com",
        "publicKey": "pk-lf-test-12345678public",
        "secretKey": "sk-lf-test-12345678secret",
    }
    # 保存后 tracing provider 必须复位到 sentinel，下一个请求按新配置重建。
    assert app.state.tracing_provider is api_app._TRACING_PROVIDER_UNSET  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_put_llm_configuration_keeps_langfuse_keys_when_disabled_or_empty(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(
        tmp_path,
        user={
            "llm": {"apiKey": _SECRET},
            "langfuse": {
                "enabled": True,
                "publicKey": "pk-lf-existing-1234",
                "secretKey": "sk-lf-existing-5678",
            },
        },
    )
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        disable_response = await client.put(
            "/config/llm",
            json=_put_body(langfuseEnabled=False),
            headers=_auth_headers(token),
        )
        assert disable_response.status_code == 200
        assert disable_response.json()["data"]["langfuseEnabled"] is False
        written = json.loads((tmp_path / "user.project.json").read_text(encoding="utf-8"))
        # 关闭追踪只改 enabled，已保存的密钥保留以便随时重新启用。
        assert written["langfuse"]["enabled"] is False
        assert written["langfuse"]["publicKey"] == "pk-lf-existing-1234"
        assert written["langfuse"]["secretKey"] == "sk-lf-existing-5678"

        reenable_response = await client.put(
            "/config/llm",
            json=_put_body(langfuseEnabled=True),
            headers=_auth_headers(token),
        )

    assert reenable_response.status_code == 200
    assert reenable_response.json()["data"]["langfuseEnabled"] is True
    rewritten = json.loads((tmp_path / "user.project.json").read_text(encoding="utf-8"))
    assert rewritten["langfuse"]["enabled"] is True


@pytest.mark.asyncio
async def test_put_llm_configuration_enabling_langfuse_without_keys_reports_missing(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = _write_configs(tmp_path, user={"llm": {"apiKey": _SECRET}})
    user_path = tmp_path / "user.project.json"
    original_bytes = user_path.read_bytes()
    app = create_app(database_url=migrated_database_url, project_config_path=config_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        response = await client.put(
            "/config/llm",
            json=_put_body(langfuseEnabled=True),
            headers=_auth_headers(token),
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_MISSING_FIELD"
    assert user_path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_config_check_reflects_updated_model_without_leaking_key(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_key = "sk-updated-9876543210wxyz"
    config_path = _write_configs(tmp_path, user={"llm": {"apiKey": _SECRET}})
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        vector_store=FakeVectorStore(),
        llm_provider=cast(LlmProvider, FakeLlmProvider()),
    )
    monkeypatch.setattr(api_app, "_mcp_client", _fake_mcp_client)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await _register_token(client)
        put_response = await client.put(
            "/config/llm",
            json=_put_body(apiKey=new_key),
            headers=_auth_headers(token),
        )
        check_response = await client.get("/config/check")

    assert put_response.status_code == 200
    assert check_response.status_code == 200
    configuration = check_response.json()["data"]["configuration"]
    assert configuration["llm"]["model"] == "qwen-new"
    assert new_key not in check_response.text
    assert _SECRET not in check_response.text
