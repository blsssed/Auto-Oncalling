"""Prometheus 数据源管理 + 指标查询 API 的行为测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.api.app import create_app
from super_ai.metrics import HttpPromqlProvider, MetricQueryError, MetricSeries
from super_ai.vector_store import MilvusHealthCheckResult


class FakeVectorStore:
    def health_check(self) -> MilvusHealthCheckResult:
        return MilvusHealthCheckResult(True, "http://milvus.test", "chunks", 1.0)


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "prometheus-sources.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"


def _write_config(tmp_path: Path, *, with_prometheus: bool) -> Path:
    config: dict[str, Any] = {
        "backend": {"memoryDatabaseUrl": "sqlite+aiosqlite:///:memory:"},
        "mcp": {"clsSseUrl": "http://mcp.test/sse", "timeoutSeconds": 3, "retries": 1},
    }
    if with_prometheus:
        config["prometheus"] = {
            "baseUrl": "http://127.0.0.1:9090",
            "timeoutSeconds": 5,
        }
    path = tmp_path / "project.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


async def _register(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": email.split("@", 1)[0],
            "password": "correct horse battery staple",
        },
    )
    return response.json()["data"]


def _headers(auth: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {auth['accessToken']}"}


@pytest.mark.asyncio
async def test_prometheus_source_crud_scope_and_password_semantics(
    migrated_database_url: str, tmp_path: Path
) -> None:
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=_write_config(tmp_path, with_prometheus=False),
        vector_store=FakeVectorStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        owner = await _register(client, "prom-owner@example.com")
        other = await _register(client, "prom-other@example.com")

        unauthenticated = await client.get("/prometheus/sources")
        empty = await client.get("/prometheus/sources", headers=_headers(owner))
        created = await client.post(
            "/prometheus/sources",
            headers=_headers(owner),
            json={
                "name": "生产 Prometheus",
                "baseUrl": "https://prometheus.example.com",
                "username": "alice",
                "password": "s3cret-value",
                "enabled": True,
                "timeoutSeconds": 8,
                "maxSeries": 30,
            },
        )
        source_id = created.json()["data"]["id"]
        duplicate = await client.post(
            "/prometheus/sources",
            headers=_headers(owner),
            json={"name": "生产 Prometheus", "baseUrl": "http://127.0.0.1:9090"},
        )
        forbidden = await client.get("/prometheus/sources", headers=_headers(other))
        forbidden_update = await client.put(
            f"/prometheus/sources/{source_id}",
            headers=_headers(other),
            json={"name": "劫持", "baseUrl": "http://127.0.0.1:9090"},
        )
        forbidden_delete = await client.delete(
            f"/prometheus/sources/{source_id}",
            headers=_headers(other),
        )
        updated = await client.put(
            f"/prometheus/sources/{source_id}",
            headers=_headers(owner),
            json={"name": "生产 Prometheus", "baseUrl": "https://prometheus.example.com"},
        )
        repositories = app.state.memory_repositories
        kept = await repositories.prometheus_sources.get(
            owner_user_id=owner["user"]["id"], source_id=source_id
        )
        deleted = await client.delete(f"/prometheus/sources/{source_id}", headers=_headers(owner))
        after_delete = await client.get("/prometheus/sources", headers=_headers(owner))

    body = created.json()["data"]
    assert unauthenticated.status_code == 401
    assert empty.json()["data"]["items"] == []
    assert created.status_code == 201
    assert "password" not in body
    assert "s3cret-value" not in created.text
    assert body["username"] == "alice"
    assert duplicate.status_code == 409
    assert forbidden.status_code == 200
    assert forbidden.json()["data"]["items"] == []
    assert forbidden_update.status_code == 403
    assert forbidden_delete.status_code == 403
    assert updated.status_code == 200
    assert kept is not None and kept.password == "s3cret-value"
    assert deleted.json()["data"]["deleted"] is True
    assert after_delete.json()["data"]["items"] == []


@pytest.mark.asyncio
async def test_prometheus_source_check_reports_up_and_down(
    migrated_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states: list[bool] = [True, False]

    async def fake_query(
        self: HttpPromqlProvider, *, query: str, at_seconds: float | None = None
    ) -> list[MetricSeries]:
        if states.pop(0):
            return []
        raise MetricQueryError("down")

    monkeypatch.setattr(HttpPromqlProvider, "query", fake_query)
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=_write_config(tmp_path, with_prometheus=False),
        vector_store=FakeVectorStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        owner = await _register(client, "prom-check@example.com")
        created = await client.post(
            "/prometheus/sources",
            headers=_headers(owner),
            json={"name": "检查目标", "baseUrl": "http://127.0.0.1:9090"},
        )
        source_id = created.json()["data"]["id"]
        first = await client.post(f"/prometheus/sources/{source_id}:check", headers=_headers(owner))
        second = await client.post(
            f"/prometheus/sources/{source_id}:check", headers=_headers(owner)
        )

    first_body = first.json()["data"]
    second_body = second.json()["data"]
    assert first.status_code == 200
    assert first_body["check"]["ok"] is True
    assert first_body["check"]["error"] is None
    assert second_body["check"]["ok"] is False
    assert second_body["check"]["error"] == "Prometheus 数据源不可用。"
    assert second_body["source"]["lastCheck"]["ok"] is False


@pytest.mark.asyncio
async def test_prometheus_source_list_seeds_local_from_file_config(
    migrated_database_url: str, tmp_path: Path
) -> None:
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=_write_config(tmp_path, with_prometheus=True),
        vector_store=FakeVectorStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        owner = await _register(client, "prom-seed@example.com")
        seeded = await client.get("/prometheus/sources", headers=_headers(owner))
        other = await _register(client, "prom-seed-b@example.com")
        other_list = await client.get("/prometheus/sources", headers=_headers(other))

    items = seeded.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["name"] == "本机 Prometheus"
    assert items[0]["baseUrl"] == "http://127.0.0.1:9090"
    # 播种按用户生效：B 首次列表也会得到自己的"本机 Prometheus"。
    other_items = other_list.json()["data"]["items"]
    assert len(other_items) == 1
    assert other_items[0]["id"] != items[0]["id"]


@pytest.mark.asyncio
async def test_prometheus_query_endpoints_validate_and_shape_series(
    migrated_database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_query_range(
        self: HttpPromqlProvider,
        *,
        query: str,
        start_seconds: float,
        end_seconds: float,
        step_seconds: int,
    ):
        return [
            MetricSeries(
                metric={"__name__": "up", "job": "demo"},
                values=((start_seconds + 60.0, 1.0), (start_seconds + 120.0, 2.5)),
            )
        ]

    async def fake_label_values(self: HttpPromqlProvider, label: str):
        return ["up", "process_cpu_seconds_total"]

    monkeypatch.setattr(HttpPromqlProvider, "query_range", fake_query_range)
    monkeypatch.setattr(HttpPromqlProvider, "label_values", fake_label_values)
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=_write_config(tmp_path, with_prometheus=False),
        vector_store=FakeVectorStore(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        owner = await _register(client, "prom-query@example.com")
        other = await _register(client, "prom-query-b@example.com")
        created = await client.post(
            "/prometheus/sources",
            headers=_headers(owner),
            json={"name": "查询源", "baseUrl": "http://127.0.0.1:9090"},
        )
        source_id = created.json()["data"]["id"]
        start_ms = 1_700_000_000_000
        ranged = await client.post(
            "/prometheus/query-range",
            headers=_headers(owner),
            json={
                "sourceId": source_id,
                "query": "up",
                "startMs": start_ms,
                "endMs": start_ms + 3_600_000,
                "stepSeconds": 30,
            },
        )
        instant = await client.post(
            "/prometheus/query",
            headers=_headers(owner),
            json={"sourceId": source_id, "query": "up"},
        )
        labels = await client.get(
            "/prometheus/labels/__name__/values",
            headers=_headers(owner),
            params={"sourceId": source_id},
        )
        cross_owner = await client.post(
            "/prometheus/query-range",
            headers=_headers(other),
            json={
                "sourceId": source_id,
                "query": "up",
                "startMs": start_ms,
                "endMs": start_ms + 3_600_000,
                "stepSeconds": 30,
            },
        )
        bad_step = await client.post(
            "/prometheus/query-range",
            headers=_headers(owner),
            json={
                "sourceId": source_id,
                "query": "up",
                "startMs": start_ms,
                "endMs": start_ms + 3_600_000,
                "stepSeconds": 1,
            },
        )
        bad_span = await client.post(
            "/prometheus/query-range",
            headers=_headers(owner),
            json={
                "sourceId": source_id,
                "query": "up",
                "startMs": start_ms,
                "endMs": start_ms + 4 * 24 * 3_600_000,
                "stepSeconds": 30,
            },
        )
        bad_label = await client.get(
            "/prometheus/labels/bad%20label/values",
            headers=_headers(owner),
            params={"sourceId": source_id},
        )

    range_body = ranged.json()["data"]
    assert ranged.status_code == 200
    assert range_body["query"] == "up"
    assert range_body["startMs"] == start_ms
    assert range_body["stepSeconds"] == 30
    assert range_body["series"][0]["metric"] == {"__name__": "up", "job": "demo"}
    points = range_body["series"][0]["points"]
    assert points[0]["timestamp"] == start_ms + 60_000
    assert points[1]["value"] == 2.5
    assert instant.status_code == 200
    assert labels.status_code == 200
    assert labels.json()["data"]["label"] == "__name__"
    assert "process_cpu_seconds_total" in labels.json()["data"]["values"]
    assert cross_owner.status_code == 403
    assert bad_step.status_code == 400
    assert bad_span.status_code == 400
    assert bad_label.status_code == 400
