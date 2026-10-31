from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.aiops import AiopsDiagnosticService
from super_ai.aiops.investigation import scoped_metric_step, validate_diagnosis
from super_ai.llm import LlmProvider, RerankResult
from super_ai.mcp_client import LocalMcpClient, McpToolDefinition
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import DiagnosticEvidenceRecord, JsonDict
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.metrics import (
    HttpPromqlProvider,
    MetricQueryError,
    MetricSeries,
    build_promql_provider,
    render_metric_text,
)
from super_ai.retrieval import KnowledgeRetrievalTool
from super_ai.vector_store import StoredVectorChunk, VectorSearchResult
from test_aiops_diagnostics import FakeStructuredOutput


@pytest.mark.asyncio
async def test_promql_provider_parses_matrix_range() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "matrix",
                    "result": [
                        {
                            "metric": {"__name__": "up", "job": "worker"},
                            "values": [[1000, "0"], [1015, "1"]],
                        }
                    ],
                },
            },
        )
    )
    provider = HttpPromqlProvider(
        base_url="http://prometheus.test",
        timeout_seconds=3,
        transport=transport,
    )

    series = await provider.query_range(
        query="up", start_seconds=1000.0, end_seconds=1015.0, step_seconds=15
    )

    assert len(series) == 1
    assert series[0].metric == {"__name__": "up", "job": "worker"}
    assert series[0].values == ((1000.0, 0.0), (1015.0, 1.0))


@pytest.mark.asyncio
async def test_promql_provider_parses_instant_vector_and_rejects_error_status() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if "error" in str(request.url):
            return httpx.Response(200, json={"status": "error", "error": "bad query"})
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {"__name__": "up"}, "value": [1000, "1"]}],
                },
            },
        )

    provider = HttpPromqlProvider(
        base_url="http://prometheus.test",
        timeout_seconds=3,
        transport=httpx.MockTransport(respond),
    )

    series = await provider.query(query="up")

    assert series[0].values == ((1000.0, 1.0),)
    with pytest.raises(MetricQueryError):
        await provider.query(query="error")


@pytest.mark.asyncio
async def test_promql_provider_label_values_uses_label_endpoint() -> None:
    seen_paths: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": ["up", "node_cpu_seconds_total", 42, "go_goroutines"],
            },
        )

    provider = HttpPromqlProvider(
        base_url="http://prometheus.test",
        timeout_seconds=3,
        transport=httpx.MockTransport(respond),
    )

    values = await provider.label_values("__name__")

    assert seen_paths == ["/api/v1/label/__name__/values"]
    assert values == ["up", "node_cpu_seconds_total", "go_goroutines"]


def test_build_promql_provider_requires_base_url(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps({"prometheus": {"baseUrl": "", "timeoutSeconds": 5}}),
        encoding="utf-8",
    )

    with pytest.raises(MetricQueryError):
        build_promql_provider(config_path=config_path)


def test_build_promql_provider_rejects_mismatched_credentials(tmp_path: Path) -> None:
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "prometheus": {
                    "baseUrl": "http://127.0.0.1:9090",
                    "timeoutSeconds": 5,
                    "username": "user",
                    "password": "",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(MetricQueryError):
        build_promql_provider(config_path=config_path)


def test_scoped_metric_step_clamps_window_to_scope() -> None:
    scope: JsonDict = {"from": 1_000_000, "to": 2_000_000, "service": "worker"}

    step = scoped_metric_step(
        {"id": "m1", "arguments": {"query": "up", "from": 500_000, "to": 3_000_000}},
        scope,
    )

    assert step["tool"] == "promql_query"
    arguments = cast(dict[str, object], step["arguments"])
    assert arguments["query"] == "up"
    assert arguments["from"] == 1_000_000
    assert arguments["to"] == 2_000_000
    assert arguments["stepSeconds"] == 30


def test_scoped_metric_step_rejects_blank_or_control_char_query() -> None:
    scope: JsonDict = {"from": 1_000_000, "to": 2_000_000}

    with pytest.raises(ValueError):
        scoped_metric_step({"arguments": {"query": "   "}}, scope)
    with pytest.raises(ValueError):
        scoped_metric_step({"arguments": {"query": "up\n\x00"}}, scope)


def test_render_metric_text_summarizes_series() -> None:
    text = render_metric_text(
        [
            MetricSeries(
                metric={"__name__": "up", "job": "worker"},
                values=((1000.0, 0.0), (1015.0, 1.0)),
            )
        ]
    )

    assert "up" in text
    assert "latest=1" in text
    assert "avg=0.5" in text
    assert "points=2" in text


def _metric_evidence(evidence_id: str, text: str) -> DiagnosticEvidenceRecord:
    return DiagnosticEvidenceRecord(
        id=evidence_id,
        owner_user_id="user-a",
        task_id="diagnostic-a",
        step_id=None,
        tool_call_id=None,
        kind="metric",
        source="promql_query",
        summary=text,
        payload={"output": {"text": text, "seriesCount": 1}},
        created_at=datetime.now(timezone.utc),
    )


def test_validate_diagnosis_accepts_metric_citation() -> None:
    text = "up{job=worker}: latest=1 min=0 max=1 avg=0.5 points=2"
    evidence = [_metric_evidence("evidence_metric", text)]
    raw = json.dumps(
        {
            "version": 1,
            "assessment": "supported",
            "summary": "指标确认 worker 已恢复。",
            "hypotheses": [
                {
                    "id": "h1",
                    "title": "worker 恢复",
                    "supportingEvidence": [
                        {"evidenceId": "evidence_metric", "excerpt": "avg=0.5"}
                    ],
                    "opposingEvidence": [],
                }
            ],
            "missingInformation": [],
            "recommendations": [],
            "verificationSteps": [],
        }
    )

    diagnosis = validate_diagnosis(raw, evidence, "user-a", "diagnostic-a")

    assert diagnosis.assessment == "supported"


def test_validate_diagnosis_rejects_metric_excerpt_not_in_text() -> None:
    evidence = [_metric_evidence("evidence_metric", "up{job=worker}: latest=1 points=2")]
    raw = json.dumps(
        {
            "version": 1,
            "assessment": "supported",
            "summary": "x",
            "hypotheses": [
                {
                    "id": "h1",
                    "title": "x",
                    "supportingEvidence": [
                        {"evidenceId": "evidence_metric", "excerpt": "not-present"}
                    ],
                    "opposingEvidence": [],
                }
            ],
            "missingInformation": [],
            "recommendations": [],
            "verificationSteps": [],
        }
    )

    with pytest.raises(ValueError):
        validate_diagnosis(raw, evidence, "user-a", "diagnostic-a")


class _FakePromqlProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def query_range(
        self,
        *,
        query: str,
        start_seconds: float,
        end_seconds: float,
        step_seconds: int,
    ) -> list[MetricSeries]:
        self.calls.append(
            {
                "query": query,
                "start": start_seconds,
                "end": end_seconds,
                "step": step_seconds,
            }
        )
        return [
            MetricSeries(
                metric={"__name__": "up", "job": "worker"},
                values=((1000.0, 0.0), (1015.0, 1.0)),
            )
        ]

    async def query(self, *, query: str, at_seconds: float | None = None) -> list[MetricSeries]:
        return [MetricSeries(metric={"__name__": "up"}, values=((1000.0, 1.0),))]


class _MetricPlanChatModel:
    def __init__(self) -> None:
        self.inputs: list[object] = []
        self.structured_error: Exception | None = None

    def with_structured_output(
        self, schema: type[Any], *, method: str | None = None, include_raw: bool = False
    ) -> FakeStructuredOutput:
        return FakeStructuredOutput(self, schema, include_raw=include_raw)

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        text = str(input)
        if "AIOps 诊断报告生成器" in text:
            match = re.search(r'"evidenceId": "(evidence_[^"]+)", "kind": "metric"', text)
            evidence_id = match.group(1) if match else "evidence_missing"
            return json.dumps(
                {
                    "version": 1,
                    "assessment": "supported",
                    "summary": "指标确认 worker 在窗口内恢复。",
                    "hypotheses": [
                        {
                            "id": "h1",
                            "title": "worker 恢复",
                            "supportingEvidence": [
                                {"evidenceId": evidence_id, "excerpt": "avg=0.5"}
                            ],
                            "opposingEvidence": [],
                        }
                    ],
                    "missingInformation": [],
                    "recommendations": ["继续观察 up 指标"],
                    "verificationSteps": ["复查指标"],
                }
            )
        if "重新规划器" in text:
            return '{"action":"stop","reason":"证据已足够","steps":[]}'
        # Planner prompt: return a single PromQL step.
        return json.dumps(
            {
                "steps": [
                    {
                        "id": "metric-step",
                        "tool": "promql_query",
                        "arguments": {"query": "up"},
                        "purpose": "查询 worker 可用性指标",
                    }
                ]
            }
        )


class _MetricLlmProvider:
    def __init__(self) -> None:
        self.chat_model = _MetricPlanChatModel()

    def create_chat_model(self) -> _MetricPlanChatModel:
        return self.chat_model

    def create_structured_chat_model(self) -> _MetricPlanChatModel:
        return self.chat_model


class _EmptyMcpClient:
    async def discover_tools(self) -> list[McpToolDefinition]:
        return [McpToolDefinition("SearchLog", "Search real logs", {})]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> object:
        raise AssertionError("MCP should not be called for a metric-only plan")


@pytest.mark.asyncio
async def test_executor_produces_metric_evidence_cited_in_report(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-metric",
            status="accepted",
            query="Investigate worker availability",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        promql = _FakePromqlProvider()
        provider = _MetricLlmProvider()
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=_FakeEmbeddingModel(),
                vector_store=_FakeVectorStore([]),
                rerank_model=_FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, _EmptyMcpClient()),
            promql_provider=promql,
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
        evidence = await repositories.diagnostics.list_evidence(
            owner_user_id="user-a", task_id=task.id
        )
        reports = await repositories.diagnostics.list_reports(
            owner_user_id="user-a", task_id=task.id
        )
    finally:
        await engine.dispose()

    metric_evidence = [item for item in evidence if item.kind == "metric"]
    assert len(metric_evidence) == 1
    output = cast(dict[str, object], metric_evidence[0].payload["output"])
    assert output["seriesCount"] == 1
    assert "avg=0.5" in str(output["text"])
    assert promql.calls[0]["query"] == "up"
    assert cast(float, promql.calls[0]["start"]) < cast(float, promql.calls[0]["end"])
    report_payload = reports[0].payload
    assert report_payload["reportGeneration"] == "llm"
    diagnosis = cast(dict[str, object], report_payload["diagnosis"])
    assert diagnosis["assessment"] == "supported"
    metric_reference_events = [
        event
        for event in events
        if event.get("type") == "reference.source"
        and cast(dict[str, object], event.get("reference", {})).get("sourceType") == "metric"
    ]
    assert metric_reference_events


class _FakeEmbeddingModel:
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2] for _ in texts]


class _FakeVectorStore:
    def __init__(self, hits: list[VectorSearchResult]) -> None:
        self.hits = hits

    def search_chunks(
        self,
        *,
        query_vector: Sequence[float],
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
        limit: int,
    ) -> list[VectorSearchResult]:
        return list(self.hits[:limit])

    def list_chunks(
        self,
        *,
        tenant_id: str,
        knowledge_base_ids: Sequence[str],
    ) -> list[StoredVectorChunk]:
        return []


class _FakeRerankModel:
    async def arerank(
        self, *, query: str, documents: Sequence[str], top_n: int
    ) -> list[RerankResult]:
        return []


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "metrics.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
