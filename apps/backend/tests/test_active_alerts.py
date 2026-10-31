from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.alerts import (
    ActiveAlert,
    AggregatedAlertProvider,
    AlertmanagerAlertProvider,
    AlertProviderError,
    PrometheusAlertProvider,
    build_alertmanager_alert_provider,
)
from super_ai.api.app import alert_snapshot_event, alert_snapshot_stream, create_app
from super_ai.chat.streaming import encode_sse
from super_ai.jobs import BackgroundJobRuntime
from super_ai.memory.repositories import (
    ActiveAlertRecord,
    ActiveAlertRepository,
    BackgroundJobRepository,
    MemoryRepositories,
)


class FakeAlertProvider:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error

    async def list_active_alerts(self) -> list[ActiveAlert]:
        if self.error is not None:
            raise self.error
        return [
            ActiveAlert(
                id="fingerprint-checkout-latency",
                source="test-provider",
                alert_name="CheckoutLatencyHigh",
                service="checkout",
                severity="critical",
                status="active",
                starts_at="2026-07-10T08:00:00Z",
                summary="Checkout latency is above the SLO.",
                labels={"alertname": "CheckoutLatencyHigh", "service": "checkout"},
                annotations={"summary": "Checkout latency is above the SLO."},
                context={"fingerprint": "fingerprint-checkout-latency"},
            )
        ]


@pytest.mark.asyncio
async def test_alertmanager_provider_normalizes_active_v2_alerts() -> None:
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json=[
                {
                    "fingerprint": "fingerprint-checkout-latency",
                    "labels": {
                        "alertname": "CheckoutLatencyHigh",
                        "service": "checkout",
                        "severity": "critical",
                    },
                    "annotations": {"summary": "Checkout latency is above the SLO."},
                    "startsAt": "2026-07-10T08:00:00Z",
                    "status": {"state": "active"},
                },
                {
                    "fingerprint": "silenced-alert",
                    "labels": {"alertname": "SilencedAlert"},
                    "annotations": {},
                    "startsAt": "2026-07-10T08:00:00Z",
                    "status": {"state": "suppressed"},
                },
            ],
        )
    )
    provider = AlertmanagerAlertProvider(
        alerts_api="http://alertmanager.test/api/v2/alerts",
        timeout_seconds=3,
        transport=transport,
    )

    alerts = await provider.list_active_alerts()

    assert len(alerts) == 1
    assert alerts[0].alert_name == "CheckoutLatencyHigh"
    assert alerts[0].service == "checkout"
    assert alerts[0].context["fingerprint"] == "fingerprint-checkout-latency"


@pytest.mark.asyncio
async def test_aggregated_provider_keeps_prometheus_source_and_tolerates_one_failed_source(
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "prometheus.test":
            return httpx.Response(
                200,
                json={
                    "status": "success",
                    "data": {
                        "alerts": [
                            {
                                "activeAt": "2026-07-10T08:00:00Z",
                                "annotations": {"summary": "Quote latency is too high."},
                                "labels": {
                                    "alertname": "QuantRiskPricingLatencyHigh",
                                    "service": "quant-risk-service",
                                    "severity": "critical",
                                },
                                "state": "firing",
                                "value": "1",
                            }
                        ]
                    },
                },
            )
        return httpx.Response(503)

    transport = httpx.MockTransport(respond)
    provider = AggregatedAlertProvider(
        providers=(
            PrometheusAlertProvider(
                source_id="external-prometheus",
                alerts_api="https://prometheus.test/api/v1/alerts",
                timeout_seconds=3,
                transport=transport,
            ),
            AlertmanagerAlertProvider(
                source_id="local-alertmanager",
                alerts_api="http://alertmanager.test/api/v2/alerts",
                timeout_seconds=3,
                transport=transport,
            ),
        )
    )

    alerts = await provider.list_active_alerts()

    assert len(alerts) == 1
    assert alerts[0].source == "external-prometheus"
    assert alerts[0].status == "active"
    assert alerts[0].context["alertSource"] == "external-prometheus"
    assert alerts[0].context["alertSourceType"] == "prometheus-v1"


def test_build_provider_skips_blank_placeholder_and_keeps_valid_source(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    _write_prom_config(
        config_path,
        [
            {"id": "external-test-prometheus", "type": "prometheus-v1", "alertsApi": ""},
            {
                "id": "local-alertmanager",
                "type": "alertmanager-v2",
                "alertsApi": "http://127.0.0.1:9093/api/v2/alerts",
            },
        ],
    )

    provider = build_alertmanager_alert_provider(config_path=config_path)

    assert isinstance(provider, AggregatedAlertProvider)
    assert len(provider.providers) == 1
    assert isinstance(provider.providers[0], AlertmanagerAlertProvider)


def test_build_provider_raises_when_every_source_is_invalid(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    _write_prom_config(
        config_path,
        [{"id": "external-test-prometheus", "type": "prometheus-v1", "alertsApi": ""}],
    )

    with pytest.raises(AlertProviderError):
        build_alertmanager_alert_provider(config_path=config_path)


def _write_prom_config(path: Path, sources: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps({"prometheusAlerts": {"timeoutSeconds": 5, "sources": sources}}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_active_alert_endpoint_requires_auth_and_surfaces_provider_failure(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(
            database_url=migrated_database_url,
            alert_provider=FakeAlertProvider(error=AlertProviderError("unavailable")),
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthenticated = await client.get("/aiops/alerts/active")
        user = await _register(client, "alerts-owner@example.com")
        unavailable = await client.get(
            "/aiops/alerts/active",
            headers={"Authorization": f"Bearer {user['accessToken']}"},
        )

    assert unauthenticated.status_code == 401
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "SYSTEM_UNAVAILABLE"
    assert "unavailable" not in unavailable.text


@pytest.mark.asyncio
async def test_active_alert_endpoint_returns_normalized_alerts_for_authenticated_user(
    migrated_database_url: str,
) -> None:
    transport = httpx.ASGITransport(
        app=create_app(database_url=migrated_database_url, alert_provider=FakeAlertProvider())
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        user = await _register(client, "alerts-list@example.com")
        response = await client.get(
            "/aiops/alerts/active",
            headers={"Authorization": f"Bearer {user['accessToken']}"},
        )

    assert response.status_code == 200
    payload = cast(dict[str, Any], response.json()["data"])
    assert payload["items"][0]["alertName"] == "CheckoutLatencyHigh"
    assert payload["items"][0]["source"] == "test-provider"
    assert payload["items"][0]["context"]["fingerprint"] == "fingerprint-checkout-latency"


async def _register(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": email.split("@")[0],
            "password": "correct horse battery staple",
        },
    )
    return cast(dict[str, Any], response.json()["data"])


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "active-alerts.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"


def _snapshot_record(alert_id: str = "fingerprint-checkout-latency") -> ActiveAlertRecord:
    return ActiveAlertRecord(
        id=alert_id,
        source="test-provider",
        alert_name="CheckoutLatencyHigh",
        service="checkout",
        severity="critical",
        status="active",
        starts_at="2026-07-10T08:00:00Z",
        summary="Checkout latency is above the SLO.",
        labels={"alertname": "CheckoutLatencyHigh", "service": "checkout"},
        annotations={"summary": "Checkout latency is above the SLO."},
        context={"fingerprint": alert_id},
    )


def _write_poll_config(path: Path, *, poll_interval: int = 3600) -> None:
    path.write_text(
        json.dumps(
            {
                "vectorStore": {
                    "uri": "http://localhost:19530",
                    "collectionName": "knowledge_chunks",
                    "vectorDimension": 1024,
                    "indexType": "HNSW",
                    "metricType": "COSINE",
                    "timeoutSeconds": 10,
                    "indexParams": {"M": 16, "efConstruction": 200},
                    "searchParams": {"ef": 64},
                },
                "prometheusAlerts": {
                    "timeoutSeconds": 5,
                    "pollIntervalSeconds": poll_interval,
                    "sources": [
                        {
                            "id": "local-alertmanager",
                            "type": "alertmanager-v2",
                            "alertsApi": "http://127.0.0.1:9093/api/v2/alerts",
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_active_alert_repository_round_trip_and_revision(
    migrated_database_url: str,
) -> None:
    app = create_app(database_url=migrated_database_url)
    repository = cast(ActiveAlertRepository, app.state.memory_repositories.active_alerts)

    assert await repository.latest_revision() == 0
    assert await repository.replace_snapshot(alerts=[_snapshot_record()]) == 1
    assert (
        await repository.replace_snapshot(
            alerts=[_snapshot_record(), _snapshot_record("second-alert")]
        )
        == 2
    )
    snapshot = await repository.list_active_alerts()
    assert [alert.id for alert in snapshot] == [
        "fingerprint-checkout-latency",
        "second-alert",
    ]
    assert await repository.latest_revision() == 2

    assert await repository.replace_snapshot(alerts=[]) == 3
    assert await repository.list_active_alerts() == []


@pytest.mark.asyncio
async def test_alert_poll_recurring_job_writes_snapshot_and_reschedules(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "project.json"
    _write_poll_config(config_path)
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        alert_provider=FakeAlertProvider(),
    )
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    background = cast(BackgroundJobRepository, repositories.background_jobs)
    active_alerts = cast(ActiveAlertRepository, repositories.active_alerts)
    runtime = cast(BackgroundJobRuntime, app.state.background_job_runtime)
    try:
        seed = await background.enqueue(
            owner_user_id="system",
            job_id=f"job_{uuid4().hex}",
            kind="alert_poll",
            resource_type="aiops_alert_poll",
            resource_id="global",
            payload={},
            max_attempts=3,
            timeout_seconds=120,
            available_at=datetime.now(timezone.utc),
        )
        await runtime.start()
        for _ in range(100):
            if await active_alerts.latest_revision() > 0:
                break
            await asyncio.sleep(0.05)

        snapshot = await active_alerts.list_active_alerts()
        assert len(snapshot) == 1
        assert snapshot[0].alert_name == "CheckoutLatencyHigh"

        next_job = await background.find_for_resource(
            owner_user_id="system",
            resource_type="aiops_alert_poll",
            resource_id="global",
        )
        assert next_job is not None
        assert next_job.id != seed.id
        assert next_job.status == "queued"
        assert next_job.available_at > datetime.now(timezone.utc)
    finally:
        await runtime.stop()


def test_alert_snapshot_sse_event_has_expected_shape() -> None:
    event = alert_snapshot_event([_snapshot_record()])

    assert event["type"] == "alerts.snapshot"
    assert event["channel"] == "aiops"
    items = cast(list[dict[str, object]], event["items"])
    assert items[0]["alertName"] == "CheckoutLatencyHigh"
    assert items[0]["source"] == "test-provider"
    frame = encode_sse(event)
    assert frame.startswith("event: alerts.snapshot\ndata: ")
    assert '"type":"alerts.snapshot"' in frame


@pytest.mark.asyncio
async def test_alert_stream_requires_auth(migrated_database_url: str) -> None:
    transport = httpx.ASGITransport(app=create_app(database_url=migrated_database_url))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        unauthenticated = await client.get("/aiops/alerts/stream")

    assert unauthenticated.status_code == 401


@pytest.mark.asyncio
async def testalert_snapshot_stream_yields_on_revision_change(
    migrated_database_url: str,
) -> None:
    app = create_app(database_url=migrated_database_url)
    repository = cast(ActiveAlertRepository, app.state.memory_repositories.active_alerts)
    await repository.replace_snapshot(alerts=[_snapshot_record()])

    # A stable revision must yield exactly one snapshot frame across several polls.
    frames = alert_snapshot_stream(repository, poll_seconds=0.05)
    received: list[str] = []

    async def collect() -> None:
        async for frame in frames:
            received.append(frame)

    task = asyncio.create_task(collect())
    try:
        await asyncio.sleep(0.3)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert len(received) == 1
    assert received[0].startswith("event: alerts.snapshot\ndata: ")
    assert '"alertName":"CheckoutLatencyHigh"' in received[0]

    # A new poll revision yields the next snapshot frame.
    await repository.replace_snapshot(alerts=[])
    refreshed = alert_snapshot_stream(repository)
    second = await asyncio.wait_for(anext(refreshed), timeout=2)
    assert '"items":[]' in second
