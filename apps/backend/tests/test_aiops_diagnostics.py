from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

import httpx
import pytest
from alembic import command
from alembic.config import Config

from super_ai.aiops import AiopsDiagnosticService, DiagnosisCasePersistor
from super_ai.api.app import AiopsDiagnosticRunner, create_app
from super_ai.llm import LlmProvider, RerankResult
from super_ai.mcp_client import LocalMcpClient, McpClientError, McpToolDefinition
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import (
    DiagnosticTaskRecord,
    JsonDict,
    TenantScopeError,
)
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.retrieval import KnowledgeRetrievalTool
from super_ai.vector_store import StoredVectorChunk, VectorSearchResult


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.inputs: list[list[str]] = []

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.inputs.append(texts)
        return [[0.1, 0.2] for _ in texts]


class FakeVectorStore:
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
        return [
            StoredVectorChunk(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                knowledge_base_id=hit.knowledge_base_id,
                owner_user_id=hit.owner_user_id,
                tenant_id=hit.tenant_id,
                content=hit.content,
                source=hit.source,
                created_at=hit.created_at,
                metadata=hit.metadata,
            )
            for hit in self.hits
        ]


class FakeRerankModel:
    async def arerank(
        self, *, query: str, documents: Sequence[str], top_n: int
    ) -> list[RerankResult]:
        return [
            RerankResult(index=index, relevance_score=0.95 - index / 100)
            for index in range(min(top_n, len(documents)))
        ]


REPORT_MARKDOWN = """# 告警分析报告

---

## 📋 活跃告警清单

| 告警名称 | 级别 | 目标服务 | 首次触发时间 | 最新触发时间 | 状态 |
|---|---|---|---|---|---|
| WorkerCpuHigh | critical | worker | 未获取 | 未获取 | 活跃 |

---

## 🔍 告警根因分析1 - WorkerCpuHigh

### 告警详情
- **告警级别**: critical

### 日志证据
- SearchLog 返回 cpu_pressure

### 根因结论
证据支持 CPU 压力症状，但不足以确认最终根因。

---

## 🛠️ 处理方案执行1 - WorkerCpuHigh

### 已执行的排查步骤
1. 查询 CLS 日志

### 处理建议
依据 SOP 继续检查 CPU 饱和度。

### 预期效果
确认 CPU 压力来源。

---

## 📊 结论

### 整体评估
存在需要继续核实的 CPU 压力告警。

### 关键发现
- CLS 返回 cpu_pressure 证据。

### 后续建议
1. 补充 CPU 指标。

### 风险评估
当前风险较高，但影响范围尚未获取。"""


def _fake_model_text(response: object) -> str:
    if isinstance(response, str):
        return response
    content = getattr(response, "content", response)
    return str(content)


class _StructuredDelegate(Protocol):
    structured_error: Exception | None

    async def ainvoke(self, input: object) -> object: ...


class FakeStructuredOutput:
    def __init__(
        self,
        delegate: _StructuredDelegate,
        schema: type[Any],
        *,
        include_raw: bool = False,
    ) -> None:
        self._delegate = delegate
        self._schema = schema
        self._include_raw = include_raw

    async def ainvoke(self, input: object) -> object:
        if self._delegate.structured_error is not None:
            raise self._delegate.structured_error
        raw = await self._delegate.ainvoke(input)
        parsed = self._schema.model_validate_json(_fake_model_text(raw))
        if self._include_raw:
            return {"raw": raw, "parsed": parsed, "parsing_error": None}
        return parsed


class FakeChatModel:
    def __init__(
        self,
        *,
        report_response: str | None = None,
        report_error: Exception | None = None,
        plan_response: str | None = None,
    ) -> None:
        self.report_response = report_response
        self.report_error = report_error
        self.plan_response = plan_response
        self.structured_error: Exception | None = None
        self.structured_schemas: list[type[Any]] = []
        self.inputs: list[object] = []

    def with_structured_output(
        self, schema: type[Any], *, method: str | None = None, include_raw: bool = False
    ) -> FakeStructuredOutput:
        self.structured_schemas.append(schema)
        return FakeStructuredOutput(self, schema, include_raw=include_raw)

    async def ainvoke(self, input: object) -> object:
        self.inputs.append(input)
        if "AIOps 诊断报告生成器" in str(input):
            if self.report_error is not None:
                raise self.report_error
            if self.report_response is not None:
                return self.report_response
            ids = re.findall(r'"evidenceId": "(evidence_[^" ]+)"', str(input))
            return json.dumps(
                {
                    "version": 1,
                    "assessment": "insufficient_evidence",
                    "summary": "CPU 压力存在，但尚不能确认根因。",
                    "hypotheses": [
                        {
                            "id": "h1",
                            "title": "CPU 饱和",
                            "supportingEvidence": (
                                [{"evidenceId": ids[-1], "excerpt": "cpu_pressure"}] if ids else []
                            ),
                            "opposingEvidence": [],
                        }
                    ],
                    "missingInformation": ["缺少 CPU 指标"],
                    "recommendations": ["检查 CPU 指标"],
                    "verificationSteps": ["对齐告警窗口"],
                }
            )
        if "重新规划器" in str(input):
            return '{"action":"stop","reason":"需补充 CPU 指标","steps":[]}'
        if self.plan_response is not None:
            return self.plan_response
        return '{"steps": []}'


class FakeLlmProvider:
    def __init__(
        self,
        *,
        report_response: str | None = None,
        report_error: Exception | None = None,
        plan_response: str | None = None,
    ) -> None:
        self.chat_model = FakeChatModel(
            report_response=report_response,
            report_error=report_error,
            plan_response=plan_response,
        )

    def create_chat_model(self) -> FakeChatModel:
        return self.chat_model

    def create_structured_chat_model(self) -> FakeChatModel:
        return self.chat_model

    def create_embedding_model(self) -> FakeEmbeddingModel:
        return FakeEmbeddingModel()

    async def check_readiness(self) -> object:
        return object()


class FakeMcpClient:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def discover_tools(self) -> list[McpToolDefinition]:
        return [McpToolDefinition("SearchLog", "Search real logs", {})]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> object:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        return [
            {
                "type": "text",
                "text": json.dumps(
                    [
                        {
                            "LogJson": json.dumps(
                                {
                                    "timestamp": "2026-07-11T06:00:00Z",
                                    "level": "ERROR",
                                    "service": "worker",
                                    "event": "cpu_pressure",
                                    "message": "Worker CPU exceeded threshold",
                                    "latency_ms": "2450",
                                    "secret": "must-not-enter-report-context",
                                }
                            )
                        }
                    ]
                ),
            }
        ]


class TrackingMcpClient(FakeMcpClient):
    def __init__(self, *, sleep: float = 0.01) -> None:
        super().__init__()
        self.sleep = sleep
        self.active = 0
        self.max_active = 0

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> object:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.sleep)
            return await super().call_tool(name, arguments)
        finally:
            self.active -= 1


class FakeCaseIndexScheduler:
    def __init__(self) -> None:
        self.scheduled: list[tuple[str, str]] = []

    def schedule(self, *, owner_user_id: str, task_id: str) -> None:
        self.scheduled.append((owner_user_id, task_id))


@pytest.mark.asyncio
async def test_diagnostic_runs_sop_first_persists_evidence_and_audits(
    migrated_database_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logging.getLogger("super_ai.aiops.diagnostics").disabled = False
    caplog.set_level(logging.INFO, logger="super_ai.aiops.diagnostics")
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-a",
            status="accepted",
            query="Investigate worker CPU alarm",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        embedding = FakeEmbeddingModel()
        retrieval = KnowledgeRetrievalTool(
            embedding_model=embedding,
            vector_store=FakeVectorStore([sop_hit("user-a")]),
            rerank_model=FakeRerankModel(),
        )
        mcp = FakeMcpClient()
        scheduler = FakeCaseIndexScheduler()
        provider = FakeLlmProvider()
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=retrieval,
            mcp_client=cast(LocalMcpClient, mcp),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=scheduler,
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
        persisted = await repositories.diagnostics.get_task(
            owner_user_id="user-a",
            task_id=task.id,
        )
        reports = await repositories.diagnostics.list_reports(
            owner_user_id="user-a",
            task_id=task.id,
        )
        checkpoints = await repositories.diagnostics.list_checkpoints(
            owner_user_id="user-a",
            task_id=task.id,
        )
        steps = await repositories.diagnostics.list_steps(
            owner_user_id="user-a",
            task_id=task.id,
        )
        evidence = await repositories.diagnostics.list_evidence(
            owner_user_id="user-a",
            task_id=task.id,
        )
        report_links = await repositories.diagnostics.list_report_evidence_links(
            owner_user_id="user-a",
            task_id=task.id,
        )
        audits = await cast(Any, repositories.tool_call_audits).list_for_diagnostic_task(
            owner_user_id="user-a",
            diagnostic_task_id=task.id,
        )
        cases = await repositories.diagnostics.list_cases(owner_user_id="user-a")
    finally:
        await engine.dispose()

    assert embedding.inputs == [["Investigate worker CPU alarm"]]
    assert mcp.calls[0][0] == "SearchLog"
    assert persisted is not None
    assert persisted.status == "succeeded"
    assert persisted.result_payload["noSopMatched"] is False
    assert reports[0].payload["reportGeneration"] == "llm"
    assert reports[0].title == "告警分析报告"
    assert cast(JsonDict, reports[0].payload["diagnosis"])["assessment"] == "insufficient_evidence"
    assert "cpu_pressure" in reports[0].content
    assert "```" not in reports[0].content
    report_prompt = next(
        str(item) for item in provider.chat_model.inputs if "AIOps 诊断报告生成器" in str(item)
    )
    assert "supportingEvidence" in report_prompt
    assert "opposingEvidence" in report_prompt
    assert "evidenceId" in report_prompt
    report_evidence = cast(list[dict[str, object]], reports[0].payload["evidence"])
    assert report_evidence[0]["tool"] == "SearchLog"
    assert "cpu_pressure" in str(report_evidence[0]["summary"])
    assert "must-not-enter-report-context" not in str(report_evidence[0]["summary"])
    assert [checkpoint.checkpoint_ns for checkpoint in checkpoints] == [
        "planner",
        "executor",
        "replanner",
        "report",
    ]
    assert [audit.tool_name for audit in audits] == ["knowledge_retrieval", "SearchLog"]
    assert [step.phase for step in steps] == ["planner", "executor", "replanner", "report"]
    assert {item.kind for item in evidence} == {"alert", "knowledge_reference", "log"}
    assert all(link.report_id == reports[0].id for link in report_links)
    assert {link.evidence_id for link in report_links} == {item.id for item in evidence}
    assert set(cast(list[str], reports[0].payload["evidenceIds"])) == {
        item.id for item in evidence
    }
    assert [event["type"] for event in events][-2:] == ["task.status", "complete"]
    assert any(event["type"] == "reference.source" for event in events)
    assert cases == []
    assert scheduler.scheduled == []
    events = [
        json.loads(record.message) for record in caplog.records if record.message.startswith("{")
    ]
    assert {event["event"] for event in events} == {
        "agent.aiops.started",
        "agent.aiops.completed",
    }
    assert all(event["diagnosticTaskId"] == task.id for event in events)
    assert "Investigate worker CPU alarm" not in "\n".join(
        record.message for record in caplog.records
    )


@pytest.mark.asyncio
async def test_diagnostic_no_sop_and_mcp_failure_are_explicit(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-b",
            status="accepted",
            query="Investigate missing logs",
            input_payload={"scope": {"service": "worker"}},
        )
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(
                LlmProvider,
                FakeLlmProvider(report_error=RuntimeError("report model unavailable")),
            ),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([]),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, FakeMcpClient(error=McpClientError("CLS unavailable"))),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
        persisted = await repositories.diagnostics.get_task(
            owner_user_id="user-a",
            task_id=task.id,
        )
        reports = await repositories.diagnostics.list_reports(
            owner_user_id="user-a",
            task_id=task.id,
        )
        cases = await repositories.diagnostics.list_cases(owner_user_id="user-a")
    finally:
        await engine.dispose()

    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.result_payload["noSopMatched"] is True
    assert reports[0].payload["reportGeneration"] == "fallback"
    assert reports[0].content.startswith("# 告警分析报告")
    assert "未检索到匹配的 SOP" in reports[0].content
    assert "诊断工具执行失败" in reports[0].content
    assert "证据不足，无法确认根因" in reports[0].content
    assert any(event["type"] == "error" for event in events)
    assert any(_is_failed_tool_event(event) for event in events)
    assert cases == []


@dataclass
class FakeAiopsRunner:
    calls: list[str] = field(default_factory=lambda: [])

    async def stream(
        self,
        *,
        task: DiagnosticTaskRecord,
        accessible_knowledge_base_ids: Sequence[str],
    ) -> AsyncIterator[dict[str, object]]:
        self.calls.append(task.id)
        yield {
            "id": "evt_1",
            "type": "task.status",
            "channel": "aiops",
            "timestamp": "2026-07-10T00:00:00+00:00",
            "task": {"id": task.id, "status": "running", "message": "Planner", "progress": 10},
        }


@pytest.mark.asyncio
async def test_aiops_stream_requires_task_owner(migrated_database_url: str) -> None:
    runner = FakeAiopsRunner()
    transport = httpx.ASGITransport(
        app=create_app(
            database_url=migrated_database_url,
            aiops_diagnostic_runner=cast(AiopsDiagnosticRunner, runner),
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = await register_user(client, "owner@example.com")
        other = await register_user(client, "other@example.com")
        create_response = await client.post(
            "/aiops/diagnostics",
            headers=auth_headers(owner["accessToken"]),
            json={"query": "Inspect CPU", "alert": {"severity": "high"}},
        )
        diagnostic_id = create_response.json()["data"]["id"]
        denied = await client.post(
            f"/aiops/diagnostics/{diagnostic_id}:stream",
            headers=auth_headers(other["accessToken"]),
        )
        stream = await client.post(
            f"/aiops/diagnostics/{diagnostic_id}:stream",
            headers=auth_headers(owner["accessToken"]),
        )
        history = await client.get(
            "/aiops/diagnostics",
            headers=auth_headers(owner["accessToken"]),
        )
        owner_chain = await client.get(
            f"/aiops/diagnostics/{diagnostic_id}/evidence-chain",
            headers=auth_headers(owner["accessToken"]),
        )
        denied_chain = await client.get(
            f"/aiops/diagnostics/{diagnostic_id}/evidence-chain",
            headers=auth_headers(other["accessToken"]),
        )

    assert create_response.status_code == 202
    assert denied.status_code == 403
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: task.status" in stream.text
    assert runner.calls == [diagnostic_id]
    assert history.status_code == 200
    assert [item["id"] for item in history.json()["data"]["items"]] == [diagnostic_id]
    assert owner_chain.status_code == 200
    assert owner_chain.json()["data"]["task"]["id"] == diagnostic_id
    assert denied_chain.status_code == 403


@pytest.mark.asyncio
async def test_diagnosis_case_api_lists_only_owner_cases_and_denies_direct_access(
    migrated_database_url: str,
) -> None:
    app = create_app(database_url=migrated_database_url)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        owner = await register_user(client, "case-owner@example.com")
        other = await register_user(client, "case-other@example.com")
        repositories = app.state.memory_repositories
        task = await repositories.diagnostics.create_task(
            owner_user_id=owner["user"]["id"],
            task_id="diagnostic-case-owner",
            status="succeeded",
            query="Investigate checkout timeout",
        )
        report = await repositories.diagnostics.add_report(
            owner_user_id=owner["user"]["id"],
            report_id="report-case-owner",
            task_id=task.id,
            title="Checkout timeout report",
            content="Evidence-backed report.",
        )
        document = await repositories.documents.create_document(
            owner_user_id=owner["user"]["id"],
            document_id="document-case-owner",
            knowledge_base_id=f"kb_{owner['user']['id']}",
            filename="checkout-case.md",
            size_bytes=22,
            mime_type="text/markdown",
            content_hash="sha256:case-owner",
            metadata={"knowledgeType": "diagnostic-case"},
        )
        index_task = await repositories.document_index_tasks.create_task(
            owner_user_id=owner["user"]["id"],
            task_id="index-case-owner",
            knowledge_base_id=document.knowledge_base_id,
            document_id=document.id,
        )
        case = await repositories.diagnostics.create_case(
            owner_user_id=owner["user"]["id"],
            case_id="case-owner",
            task_id=task.id,
            report_id=report.id,
            document_id=document.id,
            index_task_id=index_task.id,
            alert_name="CheckoutTimeout",
            service="checkout",
            keywords=["checkout", "timeout"],
            root_cause="",
            remediation="",
            summary="Evidence-backed report.",
            evidence_ids=[],
        )
        owner_list = await client.get(
            "/aiops/diagnostic-cases",
            headers=auth_headers(owner["accessToken"]),
        )
        owner_detail = await client.get(
            f"/aiops/diagnostic-cases/{case.id}",
            headers=auth_headers(owner["accessToken"]),
        )
        denied_detail = await client.get(
            f"/aiops/diagnostic-cases/{case.id}",
            headers=auth_headers(other["accessToken"]),
        )

    assert owner_list.status_code == 200
    assert [item["id"] for item in owner_list.json()["data"]["items"]] == [case.id]
    assert owner_detail.status_code == 200
    assert owner_detail.json()["data"]["id"] == case.id
    assert denied_detail.status_code == 403
    assert case.id not in denied_detail.text


@pytest.mark.asyncio
async def test_diagnostic_evidence_repository_rejects_cross_tenant_step(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task_a = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-owner-a",
            status="accepted",
            query="Owner A",
        )
        task_b = await repositories.diagnostics.create_task(
            owner_user_id="user-b",
            task_id="diagnostic-owner-b",
            status="accepted",
            query="Owner B",
        )
        step_a = await repositories.diagnostics.create_step(
            owner_user_id="user-a",
            step_id="step-owner-a",
            task_id=task_a.id,
            sequence=1,
            phase="planner",
            status="completed",
        )

        with pytest.raises(TenantScopeError):
            await repositories.diagnostics.create_evidence(
                owner_user_id="user-b",
                evidence_id="evidence-cross-tenant",
                task_id=task_b.id,
                step_id=step_a.id,
                kind="ticket",
                source="ticket-system",
                summary="Must not be written.",
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_structured_output_produces_planned_steps_and_llm_report(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-structured",
            status="accepted",
            query="Investigate worker CPU alarm",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        mcp = FakeMcpClient()
        provider = FakeLlmProvider(
            plan_response=(
                '{"steps": [{"id": "s1", "tool": "SearchLog", '
                '"arguments": {"Query": "cpu_pressure"}, "purpose": "gather logs"}]}'
            )
        )
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([sop_hit("user-a")]),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, mcp),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
        reports = await repositories.diagnostics.list_reports(
            owner_user_id="user-a",
            task_id=task.id,
        )
    finally:
        await engine.dispose()

    assert reports[0].payload["reportGeneration"] == "llm"
    assert len(provider.chat_model.structured_schemas) == 3
    assert mcp.calls[0][0] == "SearchLog"
    assert "cpu_pressure" in mcp.calls[0][1]["Query"]
    assert [event["type"] for event in events][-2:] == ["task.status", "complete"]


@pytest.mark.asyncio
async def test_structured_log_query_arguments_reach_cls_scope_filter(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-structured-log-query",
            status="accepted",
            query="Investigate worker CPU alarm",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        mcp = FakeMcpClient()
        provider = FakeLlmProvider(
            plan_response=(
                '{"steps": [{"id": "s1", "tool": "SearchLog", "arguments": '
                '{"level": "ERROR", "text": "cpu_pressure", "limit": 5}, '
                '"purpose": "gather logs"}]}'
            )
        )
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([sop_hit("user-a")]),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, mcp),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
    finally:
        await engine.dispose()

    assert mcp.calls[0][0] == "SearchLog"
    arguments = mcp.calls[0][1]
    assert arguments["Query"] == (
        'service:"worker" AND level:"ERROR" AND message:"cpu_pressure"'
    )
    assert arguments["Limit"] == 5
    assert [event["type"] for event in events][-2:] == ["task.status", "complete"]


@pytest.mark.asyncio
async def test_structured_failure_falls_back_to_regex_json_path(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-structured-fallback",
            status="accepted",
            query="Investigate worker CPU alarm",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        mcp = FakeMcpClient()
        provider = FakeLlmProvider()
        provider.chat_model.structured_error = RuntimeError("structured output unavailable")
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([sop_hit("user-a")]),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, mcp),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
        reports = await repositories.diagnostics.list_reports(
            owner_user_id="user-a",
            task_id=task.id,
        )
    finally:
        await engine.dispose()

    assert reports[0].payload["reportGeneration"] == "llm"
    assert len(provider.chat_model.structured_schemas) == 3
    assert mcp.calls[0][0] == "SearchLog"
    assert cast(JsonDict, reports[0].payload["diagnosis"])["assessment"] == "insufficient_evidence"
    assert [event["type"] for event in events][-2:] == ["task.status", "complete"]


@pytest.mark.asyncio
async def test_structured_and_plain_failure_use_defaults(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-structured-fallback-default",
            status="accepted",
            query="Investigate worker CPU alarm",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        mcp = FakeMcpClient()
        provider = FakeLlmProvider(report_error=RuntimeError("report model unavailable"))
        provider.chat_model.structured_error = RuntimeError("structured output unavailable")
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([sop_hit("user-a")]),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, mcp),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
        reports = await repositories.diagnostics.list_reports(
            owner_user_id="user-a",
            task_id=task.id,
        )
    finally:
        await engine.dispose()

    assert reports[0].payload["reportGeneration"] == "fallback"
    assert mcp.calls[0][0] == "SearchLog"
    assert "证据不足，无法确认根因" in reports[0].content
    assert cast(JsonDict, reports[0].payload["diagnosis"])["assessment"] == "insufficient_evidence"
    assert [event["type"] for event in events][-1] == "complete"


@pytest.mark.asyncio
async def test_executor_bounded_concurrency(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-parallel",
            status="accepted",
            query="Investigate worker CPU alarm",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        mcp = TrackingMcpClient()
        provider = FakeLlmProvider(
            plan_response=json.dumps(
                {
                    "steps": [
                        {
                            "id": f"s{i}",
                            "tool": "SearchLog",
                            "arguments": {"Query": f"event:{i}"},
                            "purpose": "gather",
                        }
                        for i in range(5)
                    ]
                }
            )
        )
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([sop_hit("user-a")]),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, mcp),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
        reports = await repositories.diagnostics.list_reports(
            owner_user_id="user-a",
            task_id=task.id,
        )
    finally:
        await engine.dispose()

    assert mcp.max_active <= 3
    assert mcp.max_active >= 2
    assert len(mcp.calls) == 5
    assert reports[0].payload["callCount"] == 5
    assert len({str(arguments.get("Query")) for _, arguments in mcp.calls}) == 5
    evidence = cast(list[dict[str, object]], reports[0].payload["evidence"])
    log_steps = [item["stepId"] for item in evidence if item.get("tool") == "SearchLog"]
    assert log_steps == ["s0", "s1", "s2", "s3", "s4"]
    assert [event["type"] for event in events][-1] == "complete"


@pytest.mark.asyncio
async def test_parallel_events_grouped_and_complete(migrated_database_url: str) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-parallel-events",
            status="accepted",
            query="Investigate worker CPU alarm",
            input_payload={
                "alert": {
                    "severity": "critical",
                    "service": "worker",
                    "startsAt": "2026-07-11T06:00:00Z",
                }
            },
        )
        mcp = TrackingMcpClient()
        provider = FakeLlmProvider(
            plan_response=json.dumps(
                {
                    "steps": [
                        {
                            "id": f"s{i}",
                            "tool": "SearchLog",
                            "arguments": {"Query": f"event:{i}"},
                            "purpose": "gather",
                        }
                        for i in range(5)
                    ]
                }
            )
        )
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([sop_hit("user-a")]),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, mcp),
            cls_region="ap-guangzhou",
            cls_topic_id="topic-a",
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=("kb_user-a",),
            )
        ]
    finally:
        await engine.dispose()

    tool_calls = [
        event
        for event in events
        if event["type"] == "tool.call"
        and str(cast(JsonDict, event["toolCall"]).get("name")) == "SearchLog"
    ]
    assert [
        (
            str(cast(JsonDict, event["toolCall"])["name"]),
            str(cast(JsonDict, event["toolCall"])["status"]),
        )
        for event in tool_calls
    ] == [("SearchLog", "started"), ("SearchLog", "completed")] * 5
    assert sum(1 for event in events if event["type"] == "reference.source") >= 5
    assert [event["type"] for event in events][-2:] == ["task.status", "complete"]


def sop_hit(owner_user_id: str) -> VectorSearchResult:
    return VectorSearchResult(
        chunk_id="chunk_sop",
        document_id="document_sop",
        knowledge_base_id=f"kb_{owner_user_id}",
        owner_user_id=owner_user_id,
        tenant_id=owner_user_id,
        content="Check CPU saturation and query worker logs before mitigation.",
        source="worker-cpu-sop.md",
        created_at=1,
        metadata={"kind": "sop"},
        score=0.92,
    )


async def register_user(client: httpx.AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post(
        "/auth/register",
        json={
            "email": email,
            "displayName": email.split("@")[0],
            "password": "correct horse battery staple",
        },
    )
    return cast(dict[str, Any], response.json()["data"])


def auth_headers(token: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _is_failed_tool_event(event: dict[str, object]) -> bool:
    tool_call = event.get("toolCall")
    if not isinstance(tool_call, Mapping):
        return False
    tool_call_payload = cast(Mapping[str, object], tool_call)
    return bool(
        event.get("type") == "tool.call" and tool_call_payload.get("status") == "failed"
    )


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "aiops-diagnostics.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"
