"""诊断范围、证据脱敏与可追溯结论的规则层。

阅读顺序：resolve_scope → scoped_metric_step → fingerprint
→ validate_diagnosis → diagnosis_markdown。
每个函数只看三件事：输入从哪个 state 字段来、约束了什么、失败返回什么。
第一次读请跳过：Pydantic 字段声明和正则细节。

不变量：
- 显式 scope 优先，其次告警时间 ±15 分钟，最后最近 30 分钟；
- 模型只能缩小查询范围，不能突破任务的时间/service/trace；
- 引用摘要必须是当前 owner/task 证据原文的子串，否则降级为证据不足。

【学习路线 · 监控链路支撑层】链路定位：第 2 站的 scope/脱敏/结论校验
规则层，_planner/_executor/_replanner 都受它约束。重点函数：
resolve_scope、fingerprint、validate_diagnosis。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from super_ai.memory.repositories import DiagnosticEvidenceRecord, JsonDict


class DiagnosticScope(BaseModel):
    """用户显式提交的诊断范围；字段别名与前端/HTTP 契约保持一致。"""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    service: str | None = Field(default=None, min_length=1, max_length=240)
    incident_id: str | None = Field(default=None, alias="incidentId", min_length=1, max_length=240)
    trace_id: str | None = Field(default=None, alias="traceId", min_length=1, max_length=240)
    from_time: datetime | None = Field(default=None, alias="from")
    to_time: datetime | None = Field(default=None, alias="to")

    @model_validator(mode="after")
    def valid_window(self) -> DiagnosticScope:
        """时间必须带时区且 from < to，避免本地时区误解析成 UTC。"""
        for value in (self.from_time, self.to_time):
            if value is not None and value.tzinfo is None:
                raise ValueError("时间必须包含时区。")
        if self.from_time and self.to_time and self.from_time >= self.to_time:
            raise ValueError("起始时间必须早于结束时间。")
        return self


def resolve_scope(explicit: object, alert: JsonDict, now: datetime) -> JsonDict:
    """合并显式范围、告警字段和默认时间窗，输出毫秒时间戳 scope。

    字段优先级：显式 scope > 告警顶层 > labels > annotations > context。
    时间优先级：显式 from/to > 告警 startsAt ±15 分钟 > now-30 分钟到 now。
    """
    requested = DiagnosticScope.model_validate(explicit or {})
    # 告警的 service 可能藏在 labels/annotations/context，逐层向下找。
    sources = [alert]
    for key in ("labels", "annotations", "context"):
        value = alert.get(key)
        if isinstance(value, dict):
            sources.append(cast(JsonDict, value))

    def first(*keys: str) -> str | None:
        for source in sources:
            for key in keys:
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    anchor = parse_time(first("startsAt", "startTime", "timestamp"))
    # 有告警开始时间就取前后 15 分钟；否则退化为最近 30 分钟，保证范围始终有界。
    start = requested.from_time or (
        anchor - timedelta(minutes=15) if anchor else now - timedelta(minutes=30)
    )
    end = requested.to_time or (anchor + timedelta(minutes=15) if anchor else now)
    if start >= end:
        raise ValueError("诊断时间范围无效，请同时补充起止时间。")
    return {
        "service": requested.service or first("service", "application", "job"),
        "incidentId": requested.incident_id or first("incidentId", "incident_id"),
        "traceId": requested.trace_id or first("traceId", "trace_id"),
        "from": int(start.timestamp() * 1000),
        "to": int(end.timestamp() * 1000),
    }


def scoped_step(step: JsonDict, scope: JsonDict, region: str, topic: str) -> JsonDict:
    """兼容层：把 planner 步骤翻译成已作用域的 CLS SearchLog 参数。

    宽松模式允许旧 Query passthrough；本地 adapter 不使用本函数。
    """
    # 延迟导入避免 investigation 与 log_store.query 形成循环依赖。
    from super_ai.log_store.query import LogQuery

    query = LogQuery.from_step(step, scope, strict=False)
    return {
        "id": str(step.get("id") or "search-cls-logs"),
        "tool": "SearchLog",
        "purpose": str(step.get("purpose") or "获取当前事故范围内的日志证据"),
        "arguments": query.to_cls_arguments(region=region, topic_id=topic),
    }


def scoped_metric_step(step: JsonDict, scope: JsonDict) -> JsonDict:
    """把指标步骤钳制到任务时间窗内，并限制 PromQL 与 step 长度。"""
    raw = step.get("arguments")
    args = cast(JsonDict, raw) if isinstance(raw, dict) else {}
    query = str(args.get("query") or args.get("Query") or "").strip()
    # 不解析 PromQL 语义，但拒绝空串、超长和控制字符，降低注入与资源消耗风险。
    if not query or len(query) > 2000 or any(ord(c) < 32 for c in query):
        raise ValueError("仅接受受限的 PromQL 表达式。")
    start_raw = scope.get("from")
    end_raw = scope.get("to")
    if not isinstance(start_raw, int) or not isinstance(end_raw, int):
        raise ValueError("指标查询需要有效的诊断时间范围。")
    start, end = start_raw, end_raw
    # 模型只能缩小窗口：start 取较大值，end 取较小值。
    if isinstance(args.get("from"), int):
        start = max(start, cast(int, args["from"]))
    if isinstance(args.get("to"), int):
        end = min(end, cast(int, args["to"]))
    if start >= end:
        raise ValueError("指标查询时间与任务范围没有交集。")
    step_seconds = args.get("stepSeconds", 30)
    return {
        "id": str(step.get("id") or "promql-query"),
        "tool": "promql_query",
        "purpose": str(step.get("purpose") or "获取当前事故范围内的指标证据"),
        "arguments": {
            "query": query,
            "from": start,
            "to": end,
            # 5–300 秒是 Prometheus 查询成本与分辨率之间的折中。
            "stepSeconds": max(5, min(300, step_seconds)) if isinstance(step_seconds, int) else 30,
        },
    }


def fingerprint(step: JsonDict) -> str:
    """生成查询去重指纹；故意忽略 Limit。

    只改返回条数不算“新查询”，否则模型可以通过反复调大 Limit 绕过预算。
    """
    raw = step.get("arguments")
    args = cast(JsonDict, raw) if isinstance(raw, dict) else {}
    return json.dumps(
        {key: value for key, value in args.items() if key != "Limit"},
        sort_keys=True,
        ensure_ascii=False,
    )


def parse_time(value: object) -> datetime | None:
    """解析 ISO 时间；无时区的值按 UTC 处理，无法解析返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def redact(value: object) -> object:
    """递归脱敏：敏感 key 整值替换，JSON 字符串内部再解析一次。

    覆盖 sk-* / AKID* 令牌，以及 password=... 形式的赋值文本。
    """
    if isinstance(value, Mapping):
        return {
            str(key): "[redacted]"
            if re.search(r"secret|password|token|credential|api.?key|authorization", str(key), re.I)
            else redact(item)
            for key, item in cast(Mapping[str, object], value).items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return [redact(item) for item in cast(Sequence[object], value)]
    if isinstance(value, str):
        try:
            decoded: object = json.loads(value)
        except (ValueError, TypeError):
            decoded = None
        if isinstance(decoded, dict | list):
            return json.dumps(redact(cast(object, decoded)), ensure_ascii=False)
        value = re.sub(r"(?:sk-[A-Za-z0-9_-]+|AKID[A-Za-z0-9]+)", "[redacted]", value)
        return re.sub(
            r"(?i)(password|secret|token|api[_-]?key|authorization)(\s*[:=]\s*)([^\s,;]+)",
            r"\1\2[redacted]",
            value,
        )
    return value if value is None or isinstance(value, int | float | bool) else str(value)


def scoped_records(output: object, scope: JsonDict) -> tuple[list[JsonDict], int]:
    """从 MCP 返回中提取日志，执行 scope/时间过滤、字段白名单和脱敏。

    返回 (保留记录, 被排除条数)。被排除包括 scope 不匹配、时间越界、
    结构非法以及无法解析的记录。
    """
    records: list[JsonDict] = []
    rejected = 0
    if not isinstance(output, list):
        return records, rejected
    for item in cast(list[object], output):
        if not isinstance(item, dict):
            continue
        text = cast(JsonDict, item).get("text")
        if not isinstance(text, str):
            continue
        try:
            logs: object = json.loads(text)
        except ValueError:
            continue
        if not isinstance(logs, list):
            continue
        for log in cast(list[object], logs):
            if not isinstance(log, dict):
                continue
            try:
                raw: object = json.loads(str(cast(JsonDict, log).get("LogJson") or "{}"))
            except ValueError:
                raw = {}
            if not isinstance(raw, dict):
                continue
            payload = cast(JsonDict, raw)
            timestamp = parse_time(payload.get("timestamp"))
            # scope 中存在的字段必须完全相等；空字段表示不限制。
            matches = all(
                not scope.get(key) or payload.get(field) == scope[key]
                for key, field in (
                    ("service", "service"),
                    ("incidentId", "incident_id"),
                    ("traceId", "trace_id"),
                )
            )
            if (
                not matches
                or timestamp is None
                or not cast(int, scope["from"])
                <= int(timestamp.timestamp() * 1000)
                <= cast(int, scope["to"])
            ):
                rejected += 1
                continue
            # 只输出白名单字段，避免把整条原始日志（可能含密钥/用户数据）带进证据。
            records.append(
                cast(
                    JsonDict,
                    redact(
                        {
                            key: payload[key]
                            for key in (
                                "timestamp",
                                "level",
                                "service",
                                "host",
                                "event",
                                "message",
                                "latency_ms",
                                "exception",
                                "request_id",
                                "incident_id",
                                "trace_id",
                                "scenario",
                            )
                            if key in payload
                        }
                    ),
                )
            )
    return records, rejected


class Citation(BaseModel):
    """对某条证据的引用；excerpt 必须是证据原文子串。"""

    model_config = ConfigDict(extra="forbid")
    evidenceId: str = Field(min_length=1)
    excerpt: str = Field(min_length=1, max_length=2000)


class Hypothesis(BaseModel):
    """一个候选根因及其支持/反对证据，条数有上限。"""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=1000)
    supportingEvidence: list[Citation] = Field(max_length=12)
    opposingEvidence: list[Citation] = Field(max_length=12)


class StructuredDiagnosis(BaseModel):
    """模型输出的结构化诊断契约；version=1 与前端/报告格式对齐。"""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    assessment: Literal["supported", "insufficient_evidence", "conflicting_evidence"]
    summary: str = Field(min_length=1, max_length=2000)
    hypotheses: list[Hypothesis] = Field(max_length=8)
    missingInformation: list[str] = Field(max_length=16)
    recommendations: list[str] = Field(max_length=16)
    verificationSteps: list[str] = Field(max_length=16)


class PlannedStep(BaseModel):
    """planner/replanner 产出的单个工具步骤。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str | None = None
    tool: str
    arguments: dict[str, object] = Field(default_factory=dict)
    purpose: str | None = None


class PlannedPlan(BaseModel):
    """planner 的结构化计划输出；steps 数量由上层再截断。"""

    model_config = ConfigDict(extra="ignore")

    steps: list[PlannedStep] = Field(default_factory=list[PlannedStep])


class ReplanDecision(BaseModel):
    """replanner 的结构化决策：停止、继续或修订计划。"""

    model_config = ConfigDict(extra="ignore")

    action: Literal["stop", "continue", "revise"]
    reason: str = Field(min_length=1)
    steps: list[PlannedStep] = Field(default_factory=list[PlannedStep])


def validate_diagnosis(
    raw: str, evidence: list[DiagnosticEvidenceRecord], owner: str, task: str
) -> StructuredDiagnosis:
    """校验模型诊断：引用必须属于当前 owner/task，且摘要是真实子串。

    校验失败抛 ValueError，由 _report 捕获后降级为 insufficient。
    """
    diagnosis = StructuredDiagnosis.model_validate_json(raw)
    available: dict[str, object] = {}
    for item in evidence:
        # owner/task 双重过滤：即使 evidence id 被猜到，也不能跨任务引用。
        if item.owner_user_id != owner or item.task_id != task:
            continue
        output = item.payload.get("output")
        if not isinstance(output, dict):
            continue
        output_mapping = cast(JsonDict, output)
        if item.kind == "log":
            available[item.id] = output_mapping.get("records")
        elif item.kind == "metric":
            available[item.id] = output_mapping.get("text")

    def strings(value: object) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [part for item in cast(JsonDict, value).values() for part in strings(item)]
        if isinstance(value, list):
            return [part for item in cast(list[object], value) for part in strings(item)]
        return []

    for hypothesis in diagnosis.hypotheses:
        for citation in [*hypothesis.supportingEvidence, *hypothesis.opposingEvidence]:
            # 只做“真实摘录”校验，不代表因果结论已独立验证。
            if citation.evidenceId not in available or not any(
                citation.excerpt in text for text in strings(available[citation.evidenceId])
            ):
                raise ValueError("引用不属于当前任务的保存结果，或引用片段不存在。")
    if diagnosis.assessment == "supported" and not any(
        h.supportingEvidence and not h.opposingEvidence for h in diagnosis.hypotheses
    ):
        raise ValueError("有证据支持的结论必须包含有效支持引用。")
    if diagnosis.assessment == "conflicting_evidence" and not any(
        h.supportingEvidence and h.opposingEvidence for h in diagnosis.hypotheses
    ):
        raise ValueError("证据冲突必须包含支持与反对引用。")
    return diagnosis


def insufficient(reason: str) -> StructuredDiagnosis:
    """构造确定性的“证据不足”诊断，作为所有报告失败路径的安全回退。"""
    return StructuredDiagnosis(
        version=1,
        assessment="insufficient_evidence",
        summary="证据不足，无法确认根因。",
        hypotheses=[],
        missingInformation=[reason],
        recommendations=["补充定位条件及相关日志，由操作者确认后执行处理建议。"],
        verificationSteps=["对齐事故时间与 trace，检查新增证据后重新诊断。"],
    )


def diagnosis_markdown(diagnosis: StructuredDiagnosis) -> str:
    """渲染稳定的中文 Markdown 报告；证据锚点与前端 #evidence-{id} 对齐。"""
    label = {
        "supported": "有证据支持",
        "insufficient_evidence": "证据不足",
        "conflicting_evidence": "证据冲突",
    }[diagnosis.assessment]
    lines = ["# 告警分析报告", "", f"## 结论：{label}", "", diagnosis.summary]
    for hypothesis in diagnosis.hypotheses:
        lines.extend(["", f"### 候选根因：{hypothesis.title}"])
        for title, citations in (
            ("支持证据", hypothesis.supportingEvidence),
            ("反对证据", hypothesis.opposingEvidence),
        ):
            lines.extend(["", f"**{title}**"])
            lines.extend(
                f"- [{c.evidenceId}](#evidence-{c.evidenceId})：{c.excerpt}" for c in citations
            )
            if not citations:
                lines.append("- 未获取")
    for title, values in (
        ("缺失信息", diagnosis.missingInformation),
        ("处理建议（由操作者执行）", diagnosis.recommendations),
        ("验证步骤", diagnosis.verificationSteps),
    ):
        lines.extend(["", f"## {title}", "", *[f"- {value}" for value in values]])
    return "\n".join(lines)
