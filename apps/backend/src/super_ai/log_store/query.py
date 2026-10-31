"""日志查询的中立模型：把计划步骤翻译成各数据源参数。

阅读顺序：LogQuery.from_step → to_cls_arguments（或 to_arguments）→ matches。
每个方法只看三件事：scope 怎么约束、时间怎么取交集、非法输入怎么拒绝。
第一次读请跳过：历史 Query 字符串解析（to_legacy_query 与宽松解析）。

不变量：
- 查询必须落在任务 scope 内，时间取交集，无交集直接失败；
- service/incident/trace 至少有一个，且不能与 scope 冲突；
- Limit 有硬上限，模型不能靠大数字绕过预算。

【学习路线 · 监控链路支撑层】链路定位：第 2 站 _executor 的日志查询
翻译层，把计划步骤转成 CLS 参数。重点函数：LogQuery.from_step、
to_cls_arguments。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import cast

from super_ai.aiops.investigation import parse_time
from super_ai.memory.repositories import JsonDict

_SCOPE_FIELDS = (
    ("service", "service"),
    ("incidentId", "incident_id"),
    ("traceId", "trace_id"),
)
_IDENTIFIER_FIELDS = {
    "service": "service",
    "incident_id": "incident_id",
    "incidentId": "incident_id",
    "trace_id": "trace_id",
    "traceId": "trace_id",
    "level": "level",
    "text": "text",
}
_EXACT_FIELDS = {"event", "message", "host", "request_id"}
_CONDITION = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|[^\s]+)"
)
_AND_SEPARATOR = re.compile(r"\s+AND\s+", re.IGNORECASE)
_UNSUPPORTED_OPERATOR = re.compile(r"\b(?:OR|NOT)\b", re.IGNORECASE)
_MAX_QUERY_LENGTH = 2000
_MAX_IDENTIFIER_LENGTH = 240
_MAX_TEXT_LENGTH = 500
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class LogQuery:
    """有界的中性日志查询请求，字段与具体日志厂商无关。

    raw_query 只保存经过安全校验的旧 CLS passthrough，本地 adapter
    无法解释它，因此 matches() 会直接返回 False。
    """

    service: str | None = None
    incident_id: str | None = None
    trace_id: str | None = None
    level: str | None = None
    text: str | None = None
    from_ms: int | None = None
    to_ms: int | None = None
    limit: int = _DEFAULT_LIMIT
    exact_fields: tuple[tuple[str, str], ...] = ()
    raw_query: str | None = None

    @classmethod
    def from_step(
        cls, step: JsonDict, scope: JsonDict, *, strict: bool = True
    ) -> LogQuery:
        """从 planner 步骤参数构建查询，并强制合并任务 scope。

        结构化字段优先；完全没有结构化字段时才解析旧 Query。
        strict=True 用于本地 adapter，strict=False 允许 CLS 原始 passthrough。
        """
        raw = step.get("arguments")
        args = cast(JsonDict, raw) if isinstance(raw, dict) else {}
        # 只要出现任一结构化字段，就走结构化分支，避免与旧 Query 混用。
        if any(
            key in args
            for key in (
                "service",
                "incidentId",
                "incident_id",
                "traceId",
                "trace_id",
                "level",
                "text",
            )
        ):
            query = _from_structured_arguments(args)
        else:
            legacy = str(args.get("Query") or args.get("query") or "*").strip()
            if strict:
                query = parse_legacy_query(legacy)
            else:
                query = _parse_lenient_query(legacy)

        start = _optional_int(args, ("From", "from"))
        end = _optional_int(args, ("To", "to"))
        scope_start = _optional_int(scope, ("from",))
        scope_end = _optional_int(scope, ("to",))
        # 时间窗取“模型请求”与“任务范围”的交集，模型不能把范围放宽。
        if start is not None and scope_start is not None:
            start = max(start, scope_start)
        elif start is None:
            start = scope_start
        if end is not None and scope_end is not None:
            end = min(end, scope_end)
        elif end is None:
            end = scope_end
        if start is not None and end is not None and start >= end:
            raise ValueError("模型查询时间与任务范围没有交集。")

        resolved: dict[str, str] = {}
        for scope_key, field in _SCOPE_FIELDS:
            scope_value = scope.get(scope_key)
            if scope_value is None:
                continue
            value = _identifier(scope_value, scope_key)
            current = getattr(query, field)
            # scope 是硬边界：模型给出的 service/trace 与 scope 不一致时直接拒绝。
            if current is not None and current != value:
                raise ValueError(f"日志查询的 {field} 超出当前任务范围。")
            resolved[field] = value
        # 没有任何 scope 标识就无法保证 owner/事故隔离，宁可失败也不做全量日志扫描。
        if not resolved:
            raise ValueError("请补充服务、事故 ID 或 trace ID，才能限定日志查询范围。")

        limit = _optional_int(args, ("Limit", "limit")) or _DEFAULT_LIMIT
        return replace(
            query,
            **resolved,
            from_ms=start,
            to_ms=end,
            # limit 是硬上限：模型不能通过传大数字把结果集撑大。
            limit=max(1, min(_MAX_LIMIT, limit)),
        )

    def to_arguments(self) -> JsonDict:
        """渲染结构化参数，供本地 adapter 和未来新 adapter 直接使用。"""
        arguments: JsonDict = {}
        if self.service is not None:
            arguments["service"] = self.service
        if self.incident_id is not None:
            arguments["incidentId"] = self.incident_id
        if self.trace_id is not None:
            arguments["traceId"] = self.trace_id
        if self.level is not None:
            arguments["level"] = self.level
        if self.text is not None:
            arguments["text"] = self.text
        for field, value in self.exact_fields:
            arguments[field] = value
        if self.from_ms is not None:
            arguments["from"] = self.from_ms
        if self.to_ms is not None:
            arguments["to"] = self.to_ms
        arguments["limit"] = self.limit
        return arguments

    def to_legacy_query(self) -> str:
        """渲染历史 CLS 风格 Query 字符串，仅用于兼容既有工具接口。"""
        parts: list[str] = []
        for field in ("service", "incident_id", "trace_id", "level"):
            value = getattr(self, field)
            if value is not None:
                # JSON 引号保证值里的空格/特殊字符不会破坏 field:value 结构。
                parts.append(f"{field}:{json.dumps(value, ensure_ascii=False)}")
        if self.text is not None:
            parts.append(f"message:{json.dumps(self.text, ensure_ascii=False)}")
        parts.extend(
            f"{field}:{json.dumps(value, ensure_ascii=False)}"
            for field, value in self.exact_fields
        )
        if self.raw_query is not None and self.raw_query != "*":
            parts.append(f"({self.raw_query})")
        return " AND ".join(parts) if parts else "*"

    def to_cls_arguments(self, *, region: str, topic_id: str) -> JsonDict:
        """翻译成腾讯云 CLS SearchLog 参数。

        Region/TopicId 来自服务端配置；时间必须完整，否则 CLS 会扫描过宽。
        """
        if not region.strip() or not topic_id.strip():
            raise ValueError("CLS 日志查询需要有效的 Region 与 TopicId。")
        if self.from_ms is None or self.to_ms is None:
            raise ValueError("日志查询需要有效的起止时间。")
        return {
            "Region": region,
            "TopicId": topic_id,
            "From": self.from_ms,
            "To": self.to_ms,
            "Query": self.to_legacy_query(),
            "Limit": self.limit,
        }

    def matches(self, record: Mapping[str, object]) -> bool:
        """判断一条已归一化记录是否满足本查询（本地 adapter 使用）。"""
        # 原始 CQL 无法在本地求值，不能猜测语义，直接判定不匹配。
        if self.raw_query is not None:
            # Provider-specific passthrough syntax cannot be evaluated locally.
            return False
        for field in ("service", "incident_id", "trace_id", "level"):
            expected = getattr(self, field)
            if expected is not None and record.get(field) != expected:
                return False
        for field, expected in self.exact_fields:
            if record.get(field) != expected:
                return False
        if self.text is not None:
            # text 是普通关键词，大小写不敏感，只在常见正文字段里查找。
            needle = self.text.casefold()
            haystacks = ("message", "event", "exception")
            if not any(
                needle in str(record.get(field) or "").casefold() for field in haystacks
            ):
                return False
        if self.from_ms is not None or self.to_ms is not None:
            timestamp = parse_time(record.get("timestamp"))
            if timestamp is None:
                return False
            milliseconds = int(timestamp.timestamp() * 1000)
            if self.from_ms is not None and milliseconds < self.from_ms:
                return False
            if self.to_ms is not None and milliseconds > self.to_ms:
                return False
        return True


def parse_legacy_query(raw: str) -> LogQuery:
    """解析旧 CLS Query 的严格子集：只允许 AND 连接的 field:value。

    本地日志源没有 CQL 引擎，因此管道、括号、OR/NOT、控制字符一律拒绝；
    CLS adapter 使用下面的宽松模式保留历史能力。
    """
    query = raw.strip()
    if not query or query == "*":
        return LogQuery()
    # 先做全局安全校验，再进入逐字段解析，避免解析器成为注入入口。
    if (
        "|" in query
        or len(query) > _MAX_QUERY_LENGTH
        or any(ord(char) < 32 for char in query)
    ):
        raise ValueError("仅接受保留原始日志的简单检索条件。")
    if "(" in query or ")" in query:
        raise ValueError("本地日志查询不支持括号分组。")
    if _UNSUPPORTED_OPERATOR.search(query):
        raise ValueError("本地日志查询仅支持 AND 连接的条件。")

    values: dict[str, str] = {}
    exact: dict[str, str] = {}
    position = 0
    length = len(query)
    while position < length:
        while position < length and query[position].isspace():
            position += 1
        if position >= length:
            break
        match = _CONDITION.match(query, position)
        if match is None:
            raise ValueError(f"无法解析日志查询条件：{query[position:position + 40]}")
        field, raw_value = match.group(1), match.group(2)
        value = _unquote(raw_value)
        if not value:
            raise ValueError("日志查询条件不能为空值。")
        if field in _IDENTIFIER_FIELDS:
            canonical = _IDENTIFIER_FIELDS[field]
            existing = values.get(canonical)
            # 同一字段出现两次且值不同时无法确定意图，直接拒绝而不是后者覆盖前者。
            if existing is not None and existing != value:
                raise ValueError(f"日志查询字段重复且取值冲突：{field}")
            values[canonical] = value
        elif field in _EXACT_FIELDS:
            existing_exact = exact.get(field)
            if existing_exact is not None and existing_exact != value:
                raise ValueError(f"日志查询字段重复且取值冲突：{field}")
            exact[field] = value
        else:
            raise ValueError(f"不支持的日志查询字段：{field}")
        position = match.end()
        if not query[position:].strip():
            break
        separator = _AND_SEPARATOR.match(query, position)
        if separator is None:
            raise ValueError("日志查询仅支持 AND 连接的 field:value 条件。")
        position = separator.end()

    return LogQuery(
        service=values.get("service"),
        incident_id=values.get("incident_id"),
        trace_id=values.get("trace_id"),
        level=values.get("level"),
        text=values.get("text"),
        exact_fields=tuple(sorted(exact.items())),
    )


def _parse_lenient_query(raw: str) -> LogQuery:
    """严格解析失败时，退化为“安全校验后的 CLS 原样查询”。

    这是旧计划和外部调用方的兼容路径；本地 adapter 永远不会走这里。
    """
    query = raw.strip()
    if not query or query == "*":
        return LogQuery()
    try:
        return parse_legacy_query(query)
    except ValueError:
        _validate_raw_query(query)
        return LogQuery(raw_query=query)


def _validate_raw_query(query: str) -> None:
    """对原样透传的 CQL 做结构校验：禁止管道/控制字符，括号与引号必须配平。"""
    if (
        "|" in query
        or len(query) > _MAX_QUERY_LENGTH
        or any(ord(char) < 32 for char in query)
    ):
        raise ValueError("仅接受保留原始日志的 CLS 检索条件。")
    depth = 0
    quote = ""
    escaped = False
    for char in query:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = ""
        elif char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("CLS 查询括号不匹配。")
    if depth or quote or escaped:
        raise ValueError("CLS 查询括号或引号不匹配。")


def _from_structured_arguments(args: JsonDict) -> LogQuery:
    """把结构化字段转成 LogQuery；只读取白名单字段，未知字段忽略。"""
    exact: list[tuple[str, str]] = []
    for field in sorted(_EXACT_FIELDS):
        raw = args.get(field)
        if raw is not None:
            exact.append((field, _text_value(raw, field, _MAX_TEXT_LENGTH)))
    return LogQuery(
        service=_optional_identifier(args, "service"),
        incident_id=_optional_identifier(args, "incidentId", "incident_id"),
        trace_id=_optional_identifier(args, "traceId", "trace_id"),
        level=_optional_identifier(args, "level"),
        text=_optional_text(args, "text"),
        exact_fields=tuple(exact),
    )


def _optional_identifier(args: JsonDict, *keys: str) -> str | None:
    for key in keys:
        if key in args and args[key] is not None:
            return _identifier(args[key], key)
    return None


def _optional_text(args: JsonDict, key: str) -> str | None:
    if key not in args or args[key] is None:
        return None
    return _text_value(args[key], key, _MAX_TEXT_LENGTH)


def _identifier(value: object, field: str) -> str:
    return _text_value(value, field, _MAX_IDENTIFIER_LENGTH)


def _text_value(value: object, field: str, max_length: int) -> str:
    """校验字符串字段：非空、长度受限、不含控制字符。"""
    if not isinstance(value, str):
        raise ValueError(f"日志查询字段 {field} 必须是字符串。")
    text = value.strip()
    if not text:
        raise ValueError(f"日志查询字段 {field} 不能为空。")
    if len(text) > max_length:
        raise ValueError(f"日志查询字段 {field} 过长。")
    if any(ord(char) < 32 for char in text):
        raise ValueError(f"日志查询字段 {field} 包含非法控制字符。")
    return text


def _optional_int(args: Mapping[str, object], keys: tuple[str, ...]) -> int | None:
    """读取可选正整数；bool 不算整数，零/负数直接拒绝。"""
    for key in keys:
        if key not in args or args[key] is None:
            continue
        value = args[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"日志查询字段 {key} 必须是整数。")
        if value <= 0:
            raise ValueError(f"日志查询字段 {key} 必须为正数。")
        return value
    return None


def _unquote(raw: str) -> str:
    """去掉条件值两侧引号：双引号按 JSON 解码，单引号只处理转义。"""
    if raw.startswith('"'):
        try:
            decoded: object = json.loads(raw)
        except ValueError as exc:
            raise ValueError("日志查询引号不匹配。") from exc
        if not isinstance(decoded, str):
            raise ValueError("日志查询值必须是字符串。")
        return decoded
    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            raise ValueError("日志查询引号不匹配。")
        return raw[1:-1].replace("\\'", "'")
    return raw
