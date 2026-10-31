"""Automatic alert diagnosis: policy, dedupe, durable jobs, and alert status."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.aiops.auto_diagnosis import (
    AutoDiagnosisSettings,
    auto_diagnosis_input_payload,
    auto_diagnosis_query,
    load_auto_diagnosis_settings,
)
from super_ai.alerts import ActiveAlert
from super_ai.api.app import (
    AiopsDiagnosticRunner,
    AlertDiagnosisEntry,
    aiops_job_handler,
    alert_snapshot_event,
    create_app,
)
from super_ai.jobs import BackgroundJobContext, BackgroundJobRuntime
from super_ai.memory.repositories import (
    ActiveAlertRecord,
    ActiveAlertRepository,
    BackgroundJobRecord,
    BackgroundJobRepository,
    DiagnosticTaskRecord,
    MemoryRepositories,
)
from super_ai.project_config import ProjectConfigurationError

OWNER_EMAIL = "alerts-auto@example.com"
ALERT_ID = "fingerprint-checkout-latency"


def _alert(*, severity: str = "critical") -> ActiveAlert:
    return ActiveAlert(
        id=ALERT_ID,
        source="test-provider",
        alert_name="CheckoutLatencyHigh",
        service="checkout",
        severity=severity,
        status="active",
        starts_at="2026-07-10T08:00:00Z",
        summary="Checkout latency is above the SLO.",
        labels={"alertname": "CheckoutLatencyHigh", "service": "checkout"},
        annotations={"summary": "Checkout latency is above the SLO."},
        context={"fingerprint": ALERT_ID},
    )


class FakeAlertProvider:
    def __init__(self, alerts: Sequence[ActiveAlert]) -> None:
        self._alerts = list(alerts)

    async def list_active_alerts(self) -> list[ActiveAlert]:
        return list(self._alerts)


@dataclass
class FakeAiopsRunner:
    calls: list[str] = field(default_factory=lambda: [])

    async def stream(
        self,
        *,
        task: DiagnosticTaskRecord,
        accessible_knowledge_base_ids: Sequence[str],
    ) -> AsyncIterator[dict[str, object]]:
        del accessible_knowledge_base_ids
        self.calls.append(task.id)
        yield {
            "id": "evt_1",
            "type": "task.status",
            "channel": "aiops",
            "timestamp": "2026-07-10T00:00:00+00:00",
            "task": {"id": task.id, "status": "running", "message": "Planner", "progress": 10},
        }


def _write_config(
    path: Path,
    *,
    auto_diagnosis: dict[str, object] | None,
    poll_interval: int = 3600,
) -> None:
    config: dict[str, object] = {
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
    if auto_diagnosis is not None:
        config["aiopsAutoDiagnosis"] = auto_diagnosis
    path.write_text(json.dumps(config), encoding="utf-8")


def _auto_config(**overrides: object) -> dict[str, object]:
    section: dict[str, object] = {
        "enabled": True,
        "ownerEmail": OWNER_EMAIL,
        "severities": ["critical"],
        "dedupeWindowSeconds": 900,
        "maxPerPoll": 3,
    }
    section.update(overrides)
    return section


def test_auto_diagnosis_settings_default_to_disabled(tmp_path: Path) -> None:
    assert load_auto_diagnosis_settings(config_path=_config(tmp_path, auto=None)) is None
    assert (
        load_auto_diagnosis_settings(
            config_path=_config(tmp_path, auto={"enabled": False})
        )
        is None
    )


def test_auto_diagnosis_settings_normalize_values(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    _write_config(
        config_path,
        auto_diagnosis={
            "enabled": True,
            "ownerEmail": "  Ops@Example.com ",
            "severities": ["Critical", "warning"],
            "dedupeWindowSeconds": 60,
            "maxPerPoll": 2,
        },
    )

    settings = load_auto_diagnosis_settings(config_path=config_path)

    assert settings == AutoDiagnosisSettings(
        owner_email="ops@example.com",
        severities=frozenset({"critical", "warning"}),
        dedupe_window_seconds=60,
        max_per_poll=2,
    )
    assert settings is not None
    assert settings.matches(_alert(severity="CRITICAL")) is True
    assert settings.matches(_alert(severity="info")) is False


def test_auto_diagnosis_settings_default_severity_and_limits(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis={"enabled": True, "ownerEmail": OWNER_EMAIL})

    settings = load_auto_diagnosis_settings(config_path=config_path)

    assert settings == AutoDiagnosisSettings(
        owner_email=OWNER_EMAIL,
        severities=frozenset({"critical"}),
        dedupe_window_seconds=900,
        max_per_poll=3,
    )


@pytest.mark.parametrize(
    "section",
    [
        {"enabled": True},
        {"enabled": True, "ownerEmail": "not-an-email"},
        {"enabled": True, "ownerEmail": OWNER_EMAIL, "severities": []},
        {"enabled": True, "ownerEmail": OWNER_EMAIL, "severities": ["critical", ""]},
        {"enabled": True, "ownerEmail": OWNER_EMAIL, "dedupeWindowSeconds": 0},
        {"enabled": True, "ownerEmail": OWNER_EMAIL, "maxPerPoll": True},
        {"enabled": "yes", "ownerEmail": OWNER_EMAIL},
    ],
)
def test_auto_diagnosis_settings_reject_invalid_values(
    section: dict[str, object], tmp_path: Path
) -> None:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis=section)

    with pytest.raises(ProjectConfigurationError):
        load_auto_diagnosis_settings(config_path=config_path)


def test_auto_diagnosis_payload_preserves_alert_provenance() -> None:
    alert = _alert()

    query = auto_diagnosis_query(alert)
    payload = auto_diagnosis_input_payload(alert)

    assert query == (
        "排查活跃告警：CheckoutLatencyHigh，服务：checkout，级别：critical，"
        "摘要：Checkout latency is above the SLO。"
    )
    assert payload["alertId"] == ALERT_ID
    assert payload["autoDiagnosis"] is True
    assert payload["scope"] == {}
    alert_payload = cast(dict[str, object], payload["alert"])
    assert alert_payload["alertSource"] == "test-provider"
    assert alert_payload["fingerprint"] == ALERT_ID


@pytest.mark.asyncio
async def test_poll_creates_durable_diagnosis_for_new_critical_alert(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis=_auto_config())
    runner = FakeAiopsRunner()
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        alert_provider=FakeAlertProvider([_alert()]),
        aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, runner),
    )
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    background = cast(BackgroundJobRepository, repositories.background_jobs)
    runtime = cast(BackgroundJobRuntime, app.state.background_job_runtime)
    owner = await _register(app, OWNER_EMAIL)
    await _seed_poll_job(background)
    try:
        await runtime.start()
        await _wait_until(lambda: _runner_has_calls(runner))
        tasks = await repositories.diagnostics.list_tasks(owner_user_id=owner.id)
    finally:
        await runtime.stop()

    assert len(tasks) == 1
    task = tasks[0]
    assert task.status in {"accepted", "running"}
    assert "CheckoutLatencyHigh" in task.query
    assert task.input_payload["alertId"] == ALERT_ID
    assert task.input_payload["autoDiagnosis"] is True
    jobs = await background.list(owner_user_id=owner.id)
    diagnosis_jobs = [job for job in jobs if job.kind == "aiops_diagnosis"]
    assert len(diagnosis_jobs) == 1
    assert diagnosis_jobs[0].resource_id == task.id
    assert diagnosis_jobs[0].payload["alertId"] == ALERT_ID


@pytest.mark.asyncio
async def test_diagnostic_task_fails_when_runner_cannot_be_constructed(
    migrated_database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis=None)
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
    )
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    background = cast(BackgroundJobRepository, repositories.background_jobs)
    owner = await _register(app, OWNER_EMAIL)
    task = await repositories.diagnostics.create_task(
        owner_user_id=owner.id,
        task_id="diagnostic_runner_config",
        status="accepted",
        query="checkout latency",
        input_payload={"query": "checkout latency"},
        result_payload={},
    )
    job = await background.enqueue(
        owner_user_id=owner.id,
        job_id="job_runner_config",
        kind="aiops_diagnosis",
        resource_type="aiops_diagnostic",
        resource_id=task.id,
        payload={"diagnosticId": task.id},
        max_attempts=1,
        timeout_seconds=60,
    )

    def failing_runner(_request: object) -> AiopsDiagnosticRunner:
        raise ProjectConfigurationError(
            "embedding apiKey=sk-should-not-leak is not configured"
        )

    monkeypatch.setattr("super_ai.api.app._aiops_diagnostic_runner", failing_runner)
    handler = aiops_job_handler(app)

    with pytest.raises(ProjectConfigurationError):
        await handler(BackgroundJobContext(job=job, repository=background))

    updated = await repositories.diagnostics.get_task(
        owner_user_id=owner.id,
        task_id=task.id,
    )
    assert updated is not None
    assert updated.status == "failed"
    assert updated.completed_at is not None
    assert updated.result_payload["failure"] == (
        "Diagnostic runner could not be initialized."
    )
    error = cast(str, updated.result_payload["error"])
    assert "embedding" in error
    assert "sk-should-not-leak" not in error


@pytest.mark.asyncio
async def test_poll_skips_alerts_below_configured_severity(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis=_auto_config())
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        alert_provider=FakeAlertProvider([_alert(severity="warning")]),
        aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, FakeAiopsRunner()),
    )
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    background = cast(BackgroundJobRepository, repositories.background_jobs)
    runtime = cast(BackgroundJobRuntime, app.state.background_job_runtime)
    owner = await _register(app, OWNER_EMAIL)
    try:
        seed = await _seed_poll_job(background)
        await runtime.start()
        await _wait_for_next_poll(background, seed.id)
        tasks = await repositories.diagnostics.list_tasks(owner_user_id=owner.id)
        jobs = await background.list(owner_user_id=owner.id)
    finally:
        await runtime.stop()

    assert tasks == []
    assert [job for job in jobs if job.kind == "aiops_diagnosis"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("age_seconds", "expected_tasks"),
    [(10, 1), (3600, 2)],
)
async def test_poll_dedupes_recent_diagnoses_within_the_window(
    migrated_database_url: str,
    tmp_path: Path,
    age_seconds: int,
    expected_tasks: int,
) -> None:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis=_auto_config())
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        alert_provider=FakeAlertProvider([_alert()]),
        aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, FakeAiopsRunner()),
    )
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    background = cast(BackgroundJobRepository, repositories.background_jobs)
    runtime = cast(BackgroundJobRuntime, app.state.background_job_runtime)
    owner = await _register(app, OWNER_EMAIL)
    await repositories.diagnostics.create_task(
        owner_user_id=owner.id,
        task_id="diagnostic_existing",
        status="succeeded",
        query="previous",
        input_payload={"alertId": ALERT_ID},
        result_payload={},
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
    )
    try:
        seed = await _seed_poll_job(background)
        await runtime.start()
        await _wait_for_next_poll(background, seed.id)
        tasks = await repositories.diagnostics.list_tasks(owner_user_id=owner.id)
    finally:
        await runtime.stop()

    assert len(tasks) == expected_tasks


@pytest.mark.asyncio
async def test_poll_reports_alerts_active_in_previous_snapshot_as_seen(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis=_auto_config())
    app = create_app(
        database_url=migrated_database_url,
        project_config_path=config_path,
        alert_provider=FakeAlertProvider([_alert()]),
        aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, FakeAiopsRunner()),
    )
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    background = cast(BackgroundJobRepository, repositories.background_jobs)
    active_alerts = cast(ActiveAlertRepository, repositories.active_alerts)
    runtime = cast(BackgroundJobRuntime, app.state.background_job_runtime)
    owner = await _register(app, OWNER_EMAIL)
    await active_alerts.replace_snapshot(alerts=[_snapshot_record()])
    try:
        seed = await _seed_poll_job(background)
        await runtime.start()
        await _wait_for_next_poll(background, seed.id)
        tasks = await repositories.diagnostics.list_tasks(owner_user_id=owner.id)
    finally:
        await runtime.stop()

    assert tasks == []


@pytest.mark.asyncio
async def test_active_alert_endpoint_annotates_user_diagnosis_status(
    migrated_database_url: str,
) -> None:
    app = create_app(
        database_url=migrated_database_url,
        alert_provider=FakeAlertProvider([_alert()]),
    )
    repositories = cast(MemoryRepositories, app.state.memory_repositories)
    owner = await _register(app, OWNER_EMAIL)
    other = await _register(app, "other-alerts@example.com")
    await repositories.diagnostics.create_task(
        owner_user_id=owner.id,
        task_id="diagnostic_auto",
        status="running",
        query="auto",
        input_payload={"alertId": ALERT_ID},
        result_payload={},
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        owner_response = await client.get(
            "/aiops/alerts/active",
            headers={"Authorization": f"Bearer {owner.access_token}"},
        )
        other_response = await client.get(
            "/aiops/alerts/active",
            headers={"Authorization": f"Bearer {other.access_token}"},
        )

    owner_items = cast(list[dict[str, Any]], owner_response.json()["data"]["items"])
    other_items = cast(list[dict[str, Any]], other_response.json()["data"]["items"])
    assert owner_items[0]["diagnosticId"] == "diagnostic_auto"
    assert owner_items[0]["diagnosisStatus"] == "running"
    assert "diagnosticId" not in other_items[0]


def test_alert_snapshot_event_includes_diagnosis_status() -> None:
    entry = AlertDiagnosisEntry(
        diagnostic_id="diagnostic_auto",
        status="succeeded",
        created_at=datetime.now(timezone.utc),
    )

    event = alert_snapshot_event([_snapshot_record()], {ALERT_ID: entry})
    plain = alert_snapshot_event([_snapshot_record()])

    items = cast(list[dict[str, object]], event["items"])
    plain_items = cast(list[dict[str, object]], plain["items"])
    assert items[0]["diagnosticId"] == "diagnostic_auto"
    assert items[0]["diagnosisStatus"] == "succeeded"
    assert "diagnosticId" not in plain_items[0]


@dataclass(frozen=True)
class RegisteredUser:
    id: str
    access_token: str


async def _register(app: Any, email: str) -> RegisteredUser:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/auth/register",
            json={
                "email": email,
                "displayName": email.split("@")[0],
                "password": "correct horse battery staple",
            },
        )
    data = cast(dict[str, Any], response.json()["data"])
    return RegisteredUser(
        id=cast(str, data["user"]["id"]),
        access_token=cast(str, data["accessToken"]),
    )


async def _seed_poll_job(background: BackgroundJobRepository) -> BackgroundJobRecord:
    from uuid import uuid4

    return await background.enqueue(
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


async def _wait_for_next_poll(
    background: BackgroundJobRepository, seed_job_id: str
) -> None:
    async def next_poll_ready() -> bool:
        job = await background.find_for_resource(
            owner_user_id="system",
            resource_type="aiops_alert_poll",
            resource_id="global",
        )
        return job is not None and job.id != seed_job_id

    await _wait_until(next_poll_ready)


async def _runner_has_calls(runner: FakeAiopsRunner) -> bool:
    return len(runner.calls) >= 1


async def _wait_until(
    predicate: Callable[[], Awaitable[bool]], *, timeout_seconds: float = 5.0
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("Timed out waiting for the background job runtime.")


def _snapshot_record() -> ActiveAlertRecord:
    return ActiveAlertRecord(
        id=ALERT_ID,
        source="test-provider",
        alert_name="CheckoutLatencyHigh",
        service="checkout",
        severity="critical",
        status="active",
        starts_at="2026-07-10T08:00:00Z",
        summary="Checkout latency is above the SLO.",
        labels={"alertname": "CheckoutLatencyHigh", "service": "checkout"},
        annotations={"summary": "Checkout latency is above the SLO."},
        context={"fingerprint": ALERT_ID},
    )


def _config(tmp_path: Path, *, auto: dict[str, object] | None) -> Path:
    config_path = tmp_path / "project.json"
    _write_config(config_path, auto_diagnosis=auto)
    return config_path


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "auto-diagnosis.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
