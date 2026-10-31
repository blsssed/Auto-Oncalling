from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from super_ai.aiops import AiopsDiagnosticService
from super_ai.aiops.investigation import (
    fingerprint,
    resolve_scope,
    scoped_records,
    scoped_step,
    validate_diagnosis,
)
from super_ai.api.app import create_app
from super_ai.llm import LlmProvider
from super_ai.mcp_client import LocalMcpClient
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import DiagnosticEvidenceRecord, JsonDict
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.retrieval import KnowledgeRetrievalTool, KnowledgeRetrievalToolInput
from test_aiops_diagnostics import (
    FakeCaseIndexScheduler,
    FakeChatModel,
    FakeEmbeddingModel,
    FakeLlmProvider,
    FakeMcpClient,
    FakeRerankModel,
    FakeVectorStore,
    auth_headers,
    register_user,
    sop_hit,
)
from test_aiops_diagnostics import migrated_database_url as migrated_database_url
from test_memory_migrations import alembic_config

NOW = datetime(2026, 7, 11, 6, tzinfo=timezone.utc)


def test_explicit_scope_precedence_and_default_windows() -> None:
    alert: JsonDict = {
        "startsAt": NOW.isoformat(),
        "labels": {"service": "wrong", "incident_id": "incident-a"},
        "annotations": {"trace_id": "trace-a"},
    }
    scope = resolve_scope({"service": "worker", "traceId": "explicit"}, alert, NOW)
    assert scope == {
        "service": "worker", "incidentId": "incident-a", "traceId": "explicit",
        "from": int((NOW - timedelta(minutes=15)).timestamp() * 1000),
        "to": int((NOW + timedelta(minutes=15)).timestamp() * 1000),
    }
    recent = resolve_scope({}, {}, NOW)
    assert cast(int, recent["to"]) - cast(int, recent["from"]) == 30 * 60 * 1000
    with pytest.raises(ValueError):
        resolve_scope({"from": NOW.isoformat(), "to": NOW.isoformat()}, {}, NOW)
    with pytest.raises(ValueError):
        resolve_scope({"from": "2026-07-11T06:00:00"}, {}, NOW)


def test_scoped_query_preserves_valid_filter_and_intersects_time() -> None:
    scope = resolve_scope({"service": "worker", "incidentId": "one"}, {}, NOW)
    step = scoped_step({"arguments": {
        "Query": 'level:ERROR OR (event:"cpu_pressure" AND message:"a(b)")',
        "From": cast(int, scope["from"]) + 1000, "To": cast(int, scope["to"]) + 1000,
        "TopicId": "untrusted", "Region": "untrusted", "Limit": 200,
    }}, scope, "region", "topic")
    args = cast(JsonDict, step["arguments"])
    query = cast(str, args["Query"])
    assert query.startswith('service:"worker" AND incident_id:"one" AND (')
    assert "level:ERROR OR" in query
    assert (args["From"], args["To"]) == (cast(int, scope["from"]) + 1000, scope["to"])
    assert (args["Region"], args["TopicId"], args["Limit"]) == ("region", "topic", 100)
    assert fingerprint(step) == fingerprint({"arguments": {**args, "Limit": 1}})


@pytest.mark.parametrize("query", ['*) OR service:other OR (*', 'message:"unfinished',
                                         "* | select *", "*\nOR *", "word\\"])
def test_query_cannot_escape_scope_group(query: str) -> None:
    scope = resolve_scope({"service": "worker"}, {}, NOW)
    with pytest.raises(ValueError):
        scoped_step({"arguments": {"Query": query}}, scope, "region", "topic")


def test_mixed_incidents_wrong_trace_and_missing_time_are_excluded() -> None:
    scope = resolve_scope({"service": "worker", "incidentId": "one", "traceId": "right"},
                          {"startsAt": NOW.isoformat()}, NOW)
    valid = {"timestamp": NOW.isoformat(), "service": "worker", "incident_id": "one",
             "trace_id": "right", "message": "cpu_pressure password=private-value"}
    records = [valid, {**valid, "incident_id": "other"}, {**valid, "trace_id": "wrong"},
               {**valid, "timestamp": (NOW + timedelta(hours=1)).isoformat()},
               {**valid, "timestamp": None}]
    output = [{"text": json.dumps([{"LogJson": json.dumps(item)} for item in records])}]
    logs, rejected = scoped_records(output, scope)
    assert len(logs) == 1 and rejected == 4
    assert "private-value" not in json.dumps(logs)
    assert scoped_records([], scope) == ([], 0)


def evidence() -> DiagnosticEvidenceRecord:
    return DiagnosticEvidenceRecord(
        id="evidence-a", owner_user_id="owner", task_id="task", step_id="step",
        tool_call_id="tool", kind="log", source="SearchLog", summary="cpu_pressure",
        payload={"output": {"records": [{"message": "cpu_pressure"},
                                         {"message": "CPU normal"}],
                            "metadata": "not-log-evidence"}}, created_at=NOW,
    )


def conclusion(assessment: str = "supported", excerpt: str = "cpu_pressure") -> str:
    return json.dumps({"version": 1, "assessment": assessment, "summary": "候选 CPU 问题",
        "hypotheses": [{"id": "h1", "title": "CPU 压力",
            "supportingEvidence": [{"evidenceId": "evidence-a", "excerpt": excerpt}],
            "opposingEvidence": [{"evidenceId": "evidence-a", "excerpt": "CPU normal"}]
                if assessment == "conflicting_evidence" else []}],
        "missingInformation": [], "recommendations": [], "verificationSteps": []})


@pytest.mark.parametrize("change", [{"owner_user_id": "other"}, {"task_id": "other"},
                                    {"kind": "alert"}])
def test_citations_reject_other_owner_task_and_non_log(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        validate_diagnosis(conclusion(), [replace(evidence(), **change)], "owner", "task")


@pytest.mark.parametrize("raw", ["not JSON", '{"version":1}', conclusion(excerpt="fabricated"),
                                 conclusion(excerpt="not-log-evidence")])
def test_citations_reject_fabricated_excerpts_and_invalid_structure(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_diagnosis(raw, [evidence()], "owner", "task")


def test_opposing_evidence_is_traceable_without_claiming_quality() -> None:
    diagnosis = validate_diagnosis(
        conclusion("conflicting_evidence"), [evidence()], "owner", "task")
    assert diagnosis.assessment == "conflicting_evidence"
    assert diagnosis.hypotheses[0].opposingEvidence[0].excerpt == "CPU normal"


class ReplanningModel(FakeChatModel):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode, self.revisions = mode, 0

    async def ainvoke(self, input: object) -> object:
        if "重新规划器" in str(input):
            self.revisions += 1
            if self.mode == "calls":
                return '{"action":"continue","reason":"继续验证剩余假设"}'
            if self.mode == "invalid":
                return "not-json"
            query = "*" if self.mode == "duplicate" else f"event:revision-{self.revisions}"
            return json.dumps({"action": "revise", "reason": "新证据改变了假设",
                               "steps": [{"tool": "SearchLog", "arguments": {"Query": query}}]})
        if "诊断报告生成器" not in str(input):
            count = 6 if self.mode == "calls" else 1
            return json.dumps({"steps": [
                {"tool": "SearchLog", "arguments": {"Query": f"event:initial-{i}"}}
                for i in range(count)
            ]})
        return await super().ainvoke(input)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,calls,revisions,gap", [
    ("calls", 6, 0, "日志工具预算"), ("revise", 4, 3, "计划修订预算"),
    ("duplicate", 2, 1, "重复查询"), ("invalid", 1, 0, "有效决策"),
])
async def test_replanning_changes_queries_and_stops_at_bounds(
    migrated_database_url: str, mode: str, calls: int, revisions: int, gap: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repos = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repos.diagnostics.create_task(owner_user_id="owner", task_id="bounded",
            status="accepted", query="检查 CPU", input_payload={"alert": {
                "service": "worker", "startsAt": NOW.isoformat()}})
        provider = FakeLlmProvider()
        provider.chat_model = ReplanningModel(mode)
        mcp = FakeMcpClient()
        service = AiopsDiagnosticService(repositories=repos,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([]), rerank_model=FakeRerankModel()),
            mcp_client=cast(LocalMcpClient, mcp), cls_region="region", cls_topic_id="topic")
        events = [event async for event in service.stream(
            task=task, accessible_knowledge_base_ids=())]
        report = (await repos.diagnostics.list_reports(owner_user_id="owner", task_id=task.id))[0]
        steps = await repos.diagnostics.list_steps(owner_user_id="owner", task_id=task.id)
        assert len(mcp.calls) == calls
        assert report.payload["callCount"] == calls
        assert report.payload["revisionCount"] == revisions
        assert gap in str(report.payload["stopReason"])
        assert gap in report.content
        assert [event["type"] for event in events][-1] == "complete"
        if mode == "revise":
            changes = [s for s in steps
                       if s.phase == "replanner" and s.payload["decision"] == "revise"]
            assert len(changes) == 3
            assert all(s.payload["before"] != s.payload["after"] for s in changes)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_confirmation_is_atomic_concurrent_and_owner_scoped(
    migrated_database_url: str,
) -> None:
    scheduler = FakeCaseIndexScheduler()
    app = create_app(database_url=migrated_database_url, index_task_scheduler=scheduler)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        owner = await register_user(client, "confirm@example.com")
        other = await register_user(client, "other@example.com")
        repos = app.state.memory_repositories
        task = await repos.diagnostics.create_task(owner_user_id=owner["user"]["id"],
                                                   task_id="confirm",
                                                   status="succeeded", query="检查 CPU")
        await repos.diagnostics.add_report(owner_user_id=owner["user"]["id"],
                                           report_id="report", task_id=task.id,
                                           title="旧 Markdown", content="旧报告可读")
        url = f"/aiops/diagnostics/{task.id}:save-to-knowledge"
        body = {"confirmed": True, "rootCause": "人工复核根因", "remediation": "人工执行建议"}
        denied = await client.post(url, json=body, headers=auth_headers(other["accessToken"]))
        invalid = await client.post(url, json={**body, "confirmed": False},
                                    headers=auth_headers(owner["accessToken"]))
        requests = await asyncio.gather(
            *[client.post(url, json=body, headers=auth_headers(owner["accessToken"]))
              for _ in range(4)])
        assert denied.status_code == 403 and invalid.status_code == 400
        assert all(r.status_code == 202 for r in requests)
        assert len({r.json()["data"]["document"]["id"] for r in requests}) == 1
        assert len({r.json()["data"]["task"]["id"] for r in requests}) == 1
        cases = await repos.diagnostics.list_cases(owner_user_id=owner["user"]["id"])
        assert len(cases) == 1 and cases[0].review_status == "confirmed"
        assert cases[0].confirmed_by == owner["user"]["id"] and cases[0].confirmed_at
        changed = await client.post(url, json={**body, "rootCause": "重复请求不覆盖"},
                                    headers=auth_headers(owner["accessToken"]))
        assert changed.status_code == 202
        stored = (await repos.diagnostics.list_cases(owner_user_id=owner["user"]["id"]))[0]
        assert stored.root_cause == body["rootCause"]
    await app.state.memory_engine.dispose()


@pytest.mark.asyncio
async def test_pending_legacy_cases_excluded_from_vector_and_keyword() -> None:
    original = sop_hit("owner")
    legacy = replace(original, chunk_id="legacy", source="aiops-diagnostic",
                     metadata={"diagnosticTaskId": "old"})
    pending = replace(original, chunk_id="pending",
                      metadata={"knowledgeType": "diagnostic-case", "reviewStatus": "pending"})
    confirmed = replace(original, chunk_id="confirmed",
                        metadata={"knowledgeType": "diagnostic-case", "reviewStatus": "confirmed"})
    tool = KnowledgeRetrievalTool(embedding_model=FakeEmbeddingModel(),
        vector_store=FakeVectorStore([legacy, pending, confirmed]), rerank_model=FakeRerankModel())
    result = await tool.run(
        KnowledgeRetrievalToolInput(query="CPU saturation"), owner_user_id="owner",
        accessible_knowledge_base_ids=("kb_owner",))
    assert [hit.chunk_id for hit in result.results] == ["confirmed"]
    assert result.results[0].vector_rank == 1 and result.results[0].bm25_rank == 1


def test_confirmation_migration_round_trip_and_old_row_pending(tmp_path: Path) -> None:
    path = tmp_path / "migration.db"
    config = alembic_config(path)
    command.upgrade(config, "202607110007")
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO aiops_diagnostic_cases (id, owner_user_id, task_id, report_id, "
            "document_id, index_task_id, alert_name, service, keywords, root_cause, "
            "remediation, summary, evidence_ids, created_at) VALUES "
            "('old', 'owner', 'task', 'report', 'doc', 'index', '', '', '[]', "
            "'', '', '', '[]', '2026-07-11')"))
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT review_status, confirmed_by, confirmed_at FROM aiops_diagnostic_cases")
        ).one() == ("pending", None, None)
    command.downgrade(config, "202607110007")
    columns = {c["name"] for c in inspect(engine).get_columns("aiops_diagnostic_cases")}
    assert "review_status" not in columns
    command.upgrade(config, "head")
    engine.dispose()
