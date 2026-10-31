"""LLM usage accounting: merging, provider metadata, and persisted state parsing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast

from super_ai.aiops.diagnostics import bounded_evidence_context
from super_ai.aiops.usage import LlmUsage, usage_from_response, usage_of
from super_ai.memory.repositories import DiagnosticEvidenceRecord

NOW = datetime(2026, 7, 11, tzinfo=timezone.utc)


def test_usage_merge_and_serialization() -> None:
    first = LlmUsage(calls=1, prompt_tokens=10, completion_tokens=5, total_tokens=15, latency_ms=20)
    second = LlmUsage(calls=2, prompt_tokens=7, completion_tokens=3, total_tokens=10, latency_ms=50)

    merged = first.merge(second)

    assert merged == LlmUsage(
        calls=3, prompt_tokens=17, completion_tokens=8, total_tokens=25, latency_ms=70
    )
    assert merged.to_dict() == {
        "calls": 3,
        "promptTokens": 17,
        "completionTokens": 8,
        "totalTokens": 25,
        "latencyMs": 70,
    }


def test_usage_of_reads_persisted_dict_and_ignores_junk() -> None:
    assert usage_of({"calls": 2, "promptTokens": 11, "latencyMs": 7}) == LlmUsage(
        calls=2, prompt_tokens=11, latency_ms=7
    )
    assert usage_of({"calls": "2", "latencyMs": True}) == LlmUsage()
    assert usage_of(None) == LlmUsage()


def test_usage_from_response_captures_provider_metadata() -> None:
    response = SimpleNamespace(
        usage_metadata={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150}
    )
    usage = usage_from_response(response, latency_ms=250)
    assert usage == LlmUsage(
        calls=1, prompt_tokens=120, completion_tokens=30, total_tokens=150, latency_ms=250
    )

    fallback = usage_from_response(
        SimpleNamespace(usage_metadata={"input_tokens": 5}), latency_ms=-1
    )
    assert fallback == LlmUsage(calls=1, prompt_tokens=5, total_tokens=5)


def _evidence(evidence_id: str, records: list[dict[str, object]]) -> DiagnosticEvidenceRecord:
    return DiagnosticEvidenceRecord(
        id=evidence_id,
        owner_user_id="owner",
        task_id="task",
        step_id="step",
        tool_call_id="tool",
        kind="log",
        source="SearchLog",
        summary="summary",
        payload={"output": {"recordCount": len(records), "records": records}},
        created_at=NOW,
    )


def test_report_context_trims_oversized_logs_but_keeps_counts() -> None:
    records: list[dict[str, object]] = [{"message": "x" * 500} for _ in range(60)]
    context = bounded_evidence_context([_evidence("evidence_a", records)])

    assert len(context) == 1
    output = cast(dict[str, object], context[0]["output"])
    assert output["recordCount"] == 60
    assert output["recordsTruncated"] is True
    assert len(cast(list[object], output["records"])) < 60
    assert len(json.dumps(context, ensure_ascii=False)) <= 4000


def test_report_context_keeps_small_evidence_unchanged() -> None:
    records: list[dict[str, object]] = [{"message": "cpu_pressure"}]
    evidence = _evidence("evidence_a", records)
    context = bounded_evidence_context(
        [
            evidence,
            DiagnosticEvidenceRecord(
                id="evidence_b",
                owner_user_id="owner",
                task_id="task",
                step_id="step",
                tool_call_id=None,
                kind="alert",
                source="alert",
                summary="alert",
                payload={"output": {"recordCount": 99}},
                created_at=NOW,
            ),
        ]
    )

    assert context == [
        {"evidenceId": "evidence_a", "kind": "log", "output": evidence.payload["output"]}
    ]


def test_report_context_respects_total_budget() -> None:
    items = [
        _evidence(f"evidence_{index}", [{"message": "y" * 250} for _ in range(20)])
        for index in range(30)
    ]
    context = bounded_evidence_context(items)

    assert 0 < len(context) < len(items)
    assert context[0]["evidenceId"] == "evidence_0"
    assert len(json.dumps(context, ensure_ascii=False)) <= 24000
