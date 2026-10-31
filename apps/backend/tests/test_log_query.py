from __future__ import annotations

import json

import pytest

from super_ai.log_store.query import LogQuery, parse_legacy_query
from super_ai.memory.repositories import JsonDict

SCOPE: JsonDict = {
    "service": "worker",
    "incidentId": "incident-1",
    "traceId": "trace-1",
    "from": 1_000,
    "to": 5_000,
}


def test_structured_arguments_intersect_scope_time_and_clamp_limit() -> None:
    query = LogQuery.from_step(
        {
            "arguments": {
                "service": "worker",
                "incident_id": "incident-1",
                "level": "ERROR",
                "text": "cpu_pressure",
                "from": 2_000,
                "To": 9_000,
                "limit": 500,
            }
        },
        SCOPE,
    )

    assert query.service == "worker"
    assert query.incident_id == "incident-1"
    assert query.trace_id == "trace-1"
    assert query.level == "ERROR"
    assert query.text == "cpu_pressure"
    assert (query.from_ms, query.to_ms) == (2_000, 5_000)
    assert query.limit == 100
    assert query.to_arguments() == {
        "service": "worker",
        "incidentId": "incident-1",
        "traceId": "trace-1",
        "level": "ERROR",
        "text": "cpu_pressure",
        "from": 2_000,
        "to": 5_000,
        "limit": 100,
    }


def test_structured_scope_conflict_and_empty_window_are_rejected() -> None:
    with pytest.raises(ValueError, match="service"):
        LogQuery.from_step({"arguments": {"service": "checkout"}}, SCOPE)
    with pytest.raises(ValueError, match="没有交集"):
        LogQuery.from_step({"arguments": {"from": 6_000}}, SCOPE)


@pytest.mark.parametrize(
    "arguments",
    [
        {"from": True},
        {"to": "5000"},
        {"limit": 0},
        {"level": 123},
        {"text": "bad\nvalue"},
        {"unknownField": "ignored-but-present"},
    ],
)
def test_invalid_structured_arguments_fail_clearly(arguments: dict[str, object]) -> None:
    if "unknownField" in arguments:
        # Unknown fields are ignored rather than spliced into a query.
        query = LogQuery.from_step({"arguments": arguments}, SCOPE)
        assert query.to_cls_arguments(region="r", topic_id="t")["Query"] == (
            'service:"worker" AND incident_id:"incident-1" AND trace_id:"trace-1"'
        )
        return
    with pytest.raises(ValueError):
        LogQuery.from_step({"arguments": arguments}, SCOPE)


def test_legacy_query_falls_back_and_renders_cls_arguments() -> None:
    query = LogQuery.from_step(
        {"arguments": {"Query": 'level:"ERROR" AND event:"cpu_pressure"', "Limit": 5}},
        SCOPE,
    )

    assert query.level == "ERROR"
    assert query.exact_fields == (("event", "cpu_pressure"),)
    assert query.limit == 5
    arguments = query.to_cls_arguments(region="ap-guangzhou", topic_id="topic-a")

    assert arguments == {
        "Region": "ap-guangzhou",
        "TopicId": "topic-a",
        "From": 1_000,
        "To": 5_000,
        "Query": (
            'service:"worker" AND incident_id:"incident-1" AND trace_id:"trace-1" '
            'AND level:"ERROR" AND event:"cpu_pressure"'
        ),
        "Limit": 5,
    }


def test_lenient_mode_preserves_legacy_cls_passthrough() -> None:
    step: JsonDict = {
        "arguments": {"Query": 'level:ERROR OR (event:"cpu_pressure")'}
    }

    with pytest.raises(ValueError):
        LogQuery.from_step(step, SCOPE)

    query = LogQuery.from_step(step, SCOPE, strict=False)
    rendered = str(query.to_cls_arguments(region="r", topic_id="t")["Query"])

    assert query.raw_query == 'level:ERROR OR (event:"cpu_pressure")'
    assert rendered.startswith('service:"worker" AND incident_id:"incident-1" ')
    assert rendered.endswith('AND (level:ERROR OR (event:"cpu_pressure"))')


def test_local_matching_filters_scope_query_and_text_fields() -> None:
    query = LogQuery.from_step(
        {
            "arguments": {
                "level": "ERROR",
                "text": "cpu_pressure",
                "from": 2_000,
                "to": 4_000,
            }
        },
        SCOPE,
    )
    matching = {
        "timestamp": "1970-01-01T00:00:03+00:00",
        "service": "worker",
        "incident_id": "incident-1",
        "trace_id": "trace-1",
        "level": "ERROR",
        "event": "cpu_pressure",
    }

    assert query.matches(matching) is True
    assert query.matches({**matching, "level": "INFO"}) is False
    assert query.matches({**matching, "trace_id": "other"}) is False
    assert query.matches({**matching, "timestamp": "1970-01-01T00:00:01+00:00"}) is False
    assert query.matches({**matching, "event": "timeout", "message": "CPU_PRESSURE"}) is True
    assert query.matches({**matching, "event": "timeout"}) is False


def test_legacy_parser_rejects_unknown_or_unsafe_syntax() -> None:
    for raw in ("ownerUserId:other", 'level:"ERROR" OR event:"x"', "message:\"open"):
        with pytest.raises(ValueError):
            parse_legacy_query(raw)
    assert parse_legacy_query("*") == LogQuery()
    assert parse_legacy_query('service:"worker"').service == "worker"


def test_cls_rendering_quotes_values_to_keep_scope_grouped() -> None:
    query = LogQuery.from_step(
        {"arguments": {"text": 'cpu "pressure"'}},
        {"service": "worker", "from": 1, "to": 2},
    )

    rendered = json.dumps(
        query.to_cls_arguments(region="r", topic_id="t"), ensure_ascii=False
    )
    assert 'service:\\"worker\\"' in rendered
    assert "message:" in rendered
