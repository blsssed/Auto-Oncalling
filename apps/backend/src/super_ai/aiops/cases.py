"""Manual confirmation and idempotent persistence of reviewed diagnostic cases."""

from __future__ import annotations

import inspect
import re
from collections.abc import Awaitable
from dataclasses import dataclass, replace
from typing import Protocol, cast

from super_ai.memory.repositories import (
    DiagnosticCaseRecord,
    DiagnosticEvidenceRecord,
    DiagnosticReportRecord,
    DiagnosticTaskRecord,
    MemoryRepositories,
)


class DiagnosisCaseIndexScheduler(Protocol):
    """Schedule a generated case's ordinary document index task."""

    def schedule(self, *, owner_user_id: str, task_id: str) -> Awaitable[None] | None:
        """Schedule an owner-scoped index task without blocking diagnosis streaming."""


class DiagnosisCasePersistor:
    """Create one indexable case after an operator reviews a finished report."""

    def __init__(
        self,
        *,
        repositories: MemoryRepositories,
        index_task_scheduler: DiagnosisCaseIndexScheduler,
    ) -> None:
        self._repositories = repositories
        self._index_task_scheduler = index_task_scheduler

    async def persist(
        self,
        *,
        task: DiagnosticTaskRecord,
        report: DiagnosticReportRecord,
        root_cause: str,
        remediation: str,
    ) -> DiagnosticCaseRecord:
        evidence = await self._repositories.diagnostics.list_evidence(
            owner_user_id=task.owner_user_id, task_id=task.id
        )
        fields = replace(
            _case_fields(task, report, evidence),
            root_cause=root_cause.strip(),
            remediation=remediation.strip(),
        )
        content = _case_content(task, report, evidence, fields)
        case = await self._repositories.diagnostics.confirm_case(
            owner_user_id=task.owner_user_id,
            task_id=task.id,
            report_id=report.id,
            alert_name=fields.alert_name,
            service=fields.service,
            keywords=fields.keywords,
            root_cause=fields.root_cause,
            remediation=fields.remediation,
            summary=fields.summary,
            evidence_ids=[item.id for item in evidence],
            content=content,
            metadata={
                "knowledgeType": "diagnostic-case",
                "diagnosticTaskId": task.id,
                "diagnosticReportId": report.id,
                "rootCause": fields.root_cause,
                "remediation": fields.remediation,
                "evidenceIds": [e.id for e in evidence],
            },
        )
        index_task = await self._repositories.document_index_tasks.get_task(
            owner_user_id=task.owner_user_id, task_id=case.index_task_id
        )
        if index_task is not None and index_task.status == "pending":
            scheduled = self._index_task_scheduler.schedule(
                owner_user_id=task.owner_user_id, task_id=case.index_task_id
            )
            if inspect.isawaitable(scheduled):
                await scheduled
        return case


@dataclass(frozen=True, slots=True)
class DiagnosisCaseFields:
    alert_name: str
    service: str
    keywords: list[str]
    root_cause: str
    remediation: str
    summary: str
    evidence_count: int


def _case_fields(
    task: DiagnosticTaskRecord,
    report: DiagnosticReportRecord,
    evidence: list[DiagnosticEvidenceRecord],
) -> DiagnosisCaseFields:
    alert = task.input_payload.get("alert")
    alert_data = cast(dict[str, object], alert) if isinstance(alert, dict) else {}
    report_payload = report.payload
    return DiagnosisCaseFields(
        alert_name=_first_text(alert_data, "alertName", "alertname", "name"),
        service=_first_text(alert_data, "service", "job", "application"),
        keywords=_keywords(task.query),
        root_cause=_first_text(report_payload, "rootCause", "root_cause", "conclusion"),
        remediation=_first_text(report_payload, "remediation", "action", "recommendation"),
        summary=_plain_report_summary(report.content),
        evidence_count=len(evidence),
    )


def _case_content(
    task: DiagnosticTaskRecord,
    report: DiagnosticReportRecord,
    evidence: list[DiagnosticEvidenceRecord],
    fields: DiagnosisCaseFields,
) -> str:
    lines = [
        "# AIOps Diagnostic Case",
        "",
        f"Diagnostic task: {task.id}",
        f"Report: {report.id}",
        f"Alert: {fields.alert_name}",
        f"Service: {fields.service}",
        f"Keywords: {', '.join(fields.keywords)}",
        "",
        "## Incident query",
        task.query,
        "",
        "## Root cause",
        fields.root_cause,
        "",
        "## Remediation",
        fields.remediation,
        "",
        "## Evidence-backed report",
        report.content,
        "",
        "## Evidence summaries",
    ]
    lines.extend(f"- [{item.kind}] {item.source}: {item.summary[:500]}" for item in evidence)
    return "\n".join(lines)


def _first_text(payload: dict[str, object], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str):
            return value[:500]
    return ""


def _keywords(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", query.lower())
    return list(dict.fromkeys(terms))[:12]


def _plain_report_summary(content: str) -> str:
    plain_text = re.sub(r"^#{1,6}\s+", "", content, flags=re.MULTILINE)
    plain_text = re.sub(r"[`*_>|-]", " ", plain_text)
    plain_text = re.sub(r"\s+", " ", plain_text).strip()
    return plain_text[:240]
