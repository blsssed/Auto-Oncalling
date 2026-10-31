"""Reusable diagnosis quality evaluation scenarios and scoring (fake-model mode).

The suite measures properties of the diagnosis engine rather than model quality:
citation validity, evidence coverage, root-cause keyword hit, budget compliance
and terminal task state. Scenario definitions are plain data so a future
real-model runner can reuse them unchanged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from super_ai.aiops import AiopsDiagnosticService, DiagnosisCasePersistor
from super_ai.llm import LlmProvider
from super_ai.mcp_client import LocalMcpClient
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import (
    DiagnosticEvidenceRecord,
    DiagnosticReportRecord,
    JsonDict,
)
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.metrics import MetricSeries
from super_ai.retrieval import KnowledgeRetrievalTool
from super_ai.vector_store import VectorSearchResult
from test_aiops_diagnostics import (
    FakeCaseIndexScheduler,
    FakeChatModel,
    FakeEmbeddingModel,
    FakeLlmProvider,
    FakeMcpClient,
    FakeRerankModel,
    FakeVectorStore,
    sop_hit,
)

OWNER = "eval-owner"
NOW = datetime(2026, 7, 11, 6, tzinfo=timezone.utc)
STOP_DECISION = '{"action":"stop","reason":"证据已充分，停止调查。","steps":[]}'


def _report(
    *,
    assessment: str,
    summary: str,
    hypothesis: dict[str, object] | None,
    missing: list[str],
) -> str:
    return json.dumps(
        {
            "version": 1,
            "assessment": assessment,
            "summary": summary,
            "hypotheses": [hypothesis] if hypothesis is not None else [],
            "missingInformation": missing,
            "recommendations": ["由操作者复核后执行处理建议。"],
            "verificationSteps": ["对齐事故窗口复查证据。"],
        },
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class DiagnosisScenario:
    """One deterministic incident fixture and the quality bar it must meet."""

    id: str
    description: str
    alert: dict[str, object]
    query: str
    plan: tuple[dict[str, object], ...]
    report_template: str
    logs: tuple[dict[str, str], ...] = ()
    metric_series: tuple[MetricSeries, ...] | None = None
    sop_hits: tuple[VectorSearchResult, ...] = ()
    replan_response: str = STOP_DECISION
    mcp_error: Exception | None = None
    expected_assessment: str = "insufficient_evidence"
    expected_evidence_kinds: frozenset[str] = frozenset()
    expected_keywords: tuple[str, ...] = ()
    expected_report_generation: str | None = "llm"
    expected_citation_validation: str | None = "passed"
    expect_task_succeeded: bool = True
    expected_failed_tools: int = 0
    max_call_count: int = 6


CPU_SERIES = (
    MetricSeries(
        metric={"__name__": "up", "job": "worker"},
        values=((1000.0, 0.0), (1015.0, 1.0)),
    ),
)

WORKER_CPU_SPIKE = DiagnosisScenario(
    id="worker-cpu-spike",
    description="worker CPU 饱和:指标与日志双证据互相印证",
    alert={"severity": "critical", "service": "worker", "startsAt": NOW.isoformat()},
    query="检查 worker CPU 饱和告警",
    plan=(
        {
            "id": "metric-cpu",
            "tool": "promql_query",
            "arguments": {"query": 'up{job="worker"}'},
            "purpose": "确认 CPU 指标",
        },
        {
            "id": "logs-cpu",
            "tool": "SearchLog",
            "arguments": {"Query": "event:cpu_pressure"},
            "purpose": "获取 CPU 压力日志",
        },
    ),
    report_template=_report(
        assessment="supported",
        summary="worker CPU 饱和触发告警",
        hypothesis={
            "id": "h1",
            "title": "CPU 饱和",
            "supportingEvidence": [
                {"evidenceId": "__LOG__", "excerpt": "cpu_pressure"},
                {"evidenceId": "__METRIC__", "excerpt": "avg=0.5"},
            ],
            "opposingEvidence": [],
        },
        missing=[],
    ),
    logs=(
        {
            "timestamp": "2026-07-11T05:58:00Z",
            "level": "ERROR",
            "service": "worker",
            "event": "cpu_pressure",
            "message": "cpu_pressure exceeded threshold",
        },
    ),
    metric_series=CPU_SERIES,
    sop_hits=(sop_hit(OWNER),),
    expected_assessment="supported",
    expected_evidence_kinds=frozenset({"log", "metric"}),
    expected_keywords=("CPU",),
)

CHECKOUT_TIMEOUT = DiagnosisScenario(
    id="checkout-timeout",
    description="checkout 上游超时:仅日志证据",
    alert={"severity": "critical", "service": "checkout", "startsAt": NOW.isoformat()},
    query="检查 checkout 超时告警",
    plan=(
        {
            "id": "logs-timeout",
            "tool": "SearchLog",
            "arguments": {"Query": "event:timeout"},
            "purpose": "获取超时日志",
        },
    ),
    report_template=_report(
        assessment="supported",
        summary="checkout 上游依赖超时",
        hypothesis={
            "id": "h1",
            "title": "上游超时",
            "supportingEvidence": [{"evidenceId": "__LOG__", "excerpt": "upstream timeout"}],
            "opposingEvidence": [],
        },
        missing=[],
    ),
    logs=(
        {
            "timestamp": "2026-07-11T06:00:30Z",
            "level": "ERROR",
            "service": "checkout",
            "event": "timeout",
            "message": "upstream timeout after 3000ms",
        },
    ),
    expected_assessment="supported",
    expected_evidence_kinds=frozenset({"log"}),
    expected_keywords=("timeout",),
)

INSUFFICIENT_EVIDENCE = DiagnosisScenario(
    id="insufficient-evidence",
    description="窗口内没有任何日志或指标:必须明确给出证据不足",
    alert={"severity": "warning", "service": "search", "startsAt": NOW.isoformat()},
    query="检查 search 服务异常",
    plan=(),
    report_template=_report(
        assessment="insufficient_evidence",
        summary="当前范围内没有可验证的日志或指标",
        hypothesis=None,
        missing=["缺少服务事件日志"],
    ),
    expected_assessment="insufficient_evidence",
    expected_evidence_kinds=frozenset(),
    expected_keywords=("证据不足", "未取得"),
)

TOOL_FAILURE = DiagnosisScenario(
    id="tool-failure",
    description="日志工具失败:不得产出伪造结论",
    alert={"severity": "critical", "service": "worker", "startsAt": NOW.isoformat()},
    query="检查 worker 告警(日志源不可用)",
    plan=(
        {
            "id": "logs-fail",
            "tool": "SearchLog",
            "arguments": {"Query": "event:cpu_pressure"},
            "purpose": "获取日志",
        },
    ),
    report_template=_report(
        assessment="insufficient_evidence",
        summary="日志工具不可用",
        hypothesis=None,
        missing=["工具失败"],
    ),
    mcp_error=RuntimeError("MCP 连接失败"),
    expected_assessment="insufficient_evidence",
    expected_evidence_kinds=frozenset(),
    expected_keywords=("诊断工具执行失败",),
    expect_task_succeeded=False,
    expected_failed_tools=1,
)

EVAL_SCENARIOS: tuple[DiagnosisScenario, ...] = (
    WORKER_CPU_SPIKE,
    CHECKOUT_TIMEOUT,
    INSUFFICIENT_EVIDENCE,
    TOOL_FAILURE,
)


class ScenarioChatModel(FakeChatModel):
    """Fake model that answers planner/replanner/report from scenario data."""

    def __init__(
        self, *, plan: tuple[dict[str, object], ...], report_template: str, replan_response: str
    ) -> None:
        super().__init__(plan_response=json.dumps({"steps": list(plan)}, ensure_ascii=False))
        self.report_template = report_template
        self.replan_response = replan_response

    async def ainvoke(self, input: object) -> object:
        text = str(input)
        if "AIOps 诊断报告生成器" in text:
            self.inputs.append(input)
            matches = re.findall(r'"evidenceId": "([^"]+)", "kind": "(log|metric)"', text)
            log_id = next((item_id for item_id, kind in matches if kind == "log"), "")
            metric_id = next((item_id for item_id, kind in matches if kind == "metric"), "")
            return self.report_template.replace("__LOG__", log_id).replace("__METRIC__", metric_id)
        if "重新规划器" in text:
            self.inputs.append(input)
            return self.replan_response
        return await super().ainvoke(input)


class ScenarioMcpClient(FakeMcpClient):
    """MCP client returning scenario logs (or raising the scenario error)."""

    def __init__(
        self, *, logs: tuple[dict[str, str], ...], error: Exception | None = None
    ) -> None:
        super().__init__(error=error)
        self.logs = logs

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> object:
        self.calls.append((name, arguments))
        if self.error is not None:
            raise self.error
        payload = [{"LogJson": json.dumps(log, ensure_ascii=False)} for log in self.logs]
        return [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]


class ScenarioPromqlProvider:
    """PromQL provider returning the scenario's metric series."""

    def __init__(self, series: tuple[MetricSeries, ...]) -> None:
        self.series = series
        self.calls: list[dict[str, object]] = []

    async def query_range(
        self, *, query: str, start_seconds: float, end_seconds: float, step_seconds: int
    ) -> list[MetricSeries]:
        self.calls.append(
            {"query": query, "start": start_seconds, "end": end_seconds, "step": step_seconds}
        )
        return list(self.series)

    async def query(self, *, query: str, at_seconds: float | None = None) -> list[MetricSeries]:
        del query, at_seconds
        return list(self.series)


@dataclass(frozen=True)
class EvalScore:
    scenario_id: str
    task_status: str
    assessment: str
    report_generation: str
    citation_validation: str
    evidence_kinds: frozenset[str]
    call_count: int
    failed_tools: int
    llm_calls: int
    llm_latency_ms: int
    root_cause_hit: bool
    checks: dict[str, bool]
    score: float

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())


_CHECK_WEIGHTS = {
    "task_status": 10.0,
    "assessment": 25.0,
    "citation_validation": 20.0,
    "evidence_coverage": 20.0,
    "root_cause": 15.0,
    "budget": 5.0,
    "tool_failures": 5.0,
}


def _int_value(value: object) -> int:
    return value if isinstance(value, int) else 0


def _tool_status(event: dict[str, object]) -> str:
    if event.get("type") != "tool.call":
        return ""
    tool_call = event.get("toolCall")
    if not isinstance(tool_call, dict):
        return ""
    return str(cast(JsonDict, tool_call).get("status") or "")


def score_scenario(
    scenario: DiagnosisScenario,
    *,
    task_status: str,
    report: DiagnosticReportRecord,
    evidence: list[DiagnosticEvidenceRecord],
    events: list[dict[str, object]],
) -> EvalScore:
    payload = report.payload
    diagnosis = cast(JsonDict, payload.get("diagnosis") or {})
    assessment = str(diagnosis.get("assessment") or "")
    generation = str(payload.get("reportGeneration") or "")
    citation = str(payload.get("citationValidation") or "")
    call_count = _int_value(payload.get("callCount"))
    evidence_kinds = frozenset(item.kind for item in evidence if item.kind in {"log", "metric"})
    failed_tools = sum(1 for event in events if _tool_status(event) == "failed")
    usage = cast(JsonDict, payload.get("llmUsage") or {})
    llm_calls = _int_value(usage.get("calls"))
    llm_latency_ms = _int_value(usage.get("latencyMs"))
    content = report.content.lower()
    root_cause_hit = all(keyword.lower() in content for keyword in scenario.expected_keywords)

    checks: dict[str, bool] = {
        "task_status": (task_status == "succeeded") == scenario.expect_task_succeeded,
        "assessment": assessment == scenario.expected_assessment,
        "evidence_coverage": scenario.expected_evidence_kinds <= evidence_kinds,
        "root_cause": root_cause_hit,
        "budget": call_count <= scenario.max_call_count,
        "tool_failures": failed_tools == scenario.expected_failed_tools,
    }
    if scenario.expected_citation_validation is not None:
        checks["citation_validation"] = citation == scenario.expected_citation_validation
    if scenario.expected_report_generation is not None:
        checks["report_generation"] = generation == scenario.expected_report_generation

    total_weight = sum(_CHECK_WEIGHTS[name] for name in checks if name in _CHECK_WEIGHTS)
    earned_weight = sum(
        _CHECK_WEIGHTS[name] for name, ok in checks.items() if ok and name in _CHECK_WEIGHTS
    )
    score = (earned_weight / total_weight * 100.0) if total_weight else 0.0
    return EvalScore(
        scenario_id=scenario.id,
        task_status=task_status,
        assessment=assessment,
        report_generation=generation,
        citation_validation=citation,
        evidence_kinds=evidence_kinds,
        call_count=call_count,
        failed_tools=failed_tools,
        llm_calls=llm_calls,
        llm_latency_ms=llm_latency_ms,
        root_cause_hit=root_cause_hit,
        checks=checks,
        score=score,
    )


async def run_scenario(scenario: DiagnosisScenario, database_url: str) -> EvalScore:
    """Run one scenario end to end and return its quality score."""
    engine = create_memory_engine(database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id=OWNER,
            task_id=f"eval-{scenario.id}",
            status="accepted",
            query=scenario.query,
            input_payload={"alert": dict(scenario.alert)},
        )
        provider = FakeLlmProvider()
        provider.chat_model = ScenarioChatModel(
            plan=scenario.plan,
            report_template=scenario.report_template,
            replan_response=scenario.replan_response,
        )
        mcp = ScenarioMcpClient(logs=scenario.logs, error=scenario.mcp_error)
        promql = (
            ScenarioPromqlProvider(scenario.metric_series)
            if scenario.metric_series is not None
            else None
        )
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore(list(scenario.sop_hits)),
                rerank_model=FakeRerankModel(),
            ),
            mcp_client=cast(LocalMcpClient, mcp),
            promql_provider=promql,
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
                task=task, accessible_knowledge_base_ids=(f"kb_{OWNER}",)
            )
        ]
        persisted = await repositories.diagnostics.get_task(
            owner_user_id=OWNER, task_id=task.id
        )
        reports = await repositories.diagnostics.list_reports(
            owner_user_id=OWNER, task_id=task.id
        )
        evidence = await repositories.diagnostics.list_evidence(
            owner_user_id=OWNER, task_id=task.id
        )
    finally:
        await engine.dispose()
    if persisted is None or not reports:
        raise AssertionError(f"Scenario {scenario.id} did not persist a task and report.")
    return score_scenario(
        scenario,
        task_status=persisted.status,
        report=reports[0],
        evidence=evidence,
        events=events,
    )


def format_scorecard(scores: list[EvalScore]) -> str:
    lines = [
        "场景 | 结论 | 生成 | 引用校验 | 工具证据 | 调用数 | 失败工具 | LLM调用 | "
        "LLM耗时ms | 得分 | 结果",
        "--- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---",
    ]
    for item in scores:
        kinds = ",".join(sorted(item.evidence_kinds)) or "-"
        outcome = "PASS" if item.passed else "FAIL"
        lines.append(
            f"{item.scenario_id} | {item.assessment} | {item.report_generation} | "
            f"{item.citation_validation} | {kinds} | {item.call_count} | "
            f"{item.failed_tools} | {item.llm_calls} | {item.llm_latency_ms} | "
            f"{item.score:.0f} | {outcome}"
        )
    average = (sum(item.score for item in scores) / len(scores)) if scores else 0.0
    lines.append(f"平均分: {average:.1f}")
    return "\n".join(lines)
