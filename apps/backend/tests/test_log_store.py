from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import pytest

from super_ai.aiops import AiopsDiagnosticService, DiagnosisCasePersistor
from super_ai.llm import LlmProvider
from super_ai.log_store import ClsLogStore, FileLogStore, build_log_store
from super_ai.mcp_client import LocalMcpClient
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.repositories import JsonDict
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.project_config import ProjectConfigurationError
from super_ai.retrieval import KnowledgeRetrievalTool
from test_aiops_diagnostics import (
    FakeCaseIndexScheduler,
    FakeEmbeddingModel,
    FakeLlmProvider,
    FakeMcpClient,
    FakeRerankModel,
    FakeVectorStore,
)
from test_aiops_diagnostics import migrated_database_url as migrated_database_url

NOW = datetime(2026, 7, 11, 6, tzinfo=timezone.utc)
SCOPE: JsonDict = {
    "service": "worker",
    "from": int((NOW - timedelta(minutes=15)).timestamp() * 1000),
    "to": int((NOW + timedelta(minutes=15)).timestamp() * 1000),
}


@pytest.mark.asyncio
async def test_cls_log_store_returns_sanitized_scope_filtered_records() -> None:
    mcp = FakeMcpClient()
    store = ClsLogStore(
        region="ap-guangzhou",
        topic_id="topic-a",
        mcp_client=cast(LocalMcpClient, mcp),
    )
    step = store.build_args({"tool": "SearchLog", "arguments": {"Query": "*"}}, SCOPE)
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert mcp.calls[0][0] == "SearchLog"
    assert mcp.calls[0][1]["Region"] == "ap-guangzhou"
    assert mcp.calls[0][1]["TopicId"] == "topic-a"
    assert result["recordCount"] == 1
    assert result["excludedRecordCount"] == 0
    assert result["records"][0]["event"] == "cpu_pressure"
    assert "must-not-enter-report-context" not in json.dumps(result["records"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_cls_log_store_renders_structured_arguments() -> None:
    mcp = FakeMcpClient()
    store = ClsLogStore(
        region="ap-guangzhou",
        topic_id="topic-a",
        mcp_client=cast(LocalMcpClient, mcp),
    )
    step = store.build_args(
        {
            "id": "s1",
            "tool": "SearchLog",
            "arguments": {"level": "ERROR", "text": "cpu_pressure", "limit": 5},
        },
        SCOPE,
    )
    arguments = cast(JsonDict, step["arguments"])

    assert arguments == {
        "Region": "ap-guangzhou",
        "TopicId": "topic-a",
        "From": SCOPE["from"],
        "To": SCOPE["to"],
        "Query": 'service:"worker" AND level:"ERROR" AND message:"cpu_pressure"',
        "Limit": 5,
    }
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")
    assert mcp.calls[0][1] == arguments
    assert result["recordCount"] == 1


def test_file_log_store_build_args_are_structured() -> None:
    store = FileLogStore(file_path=Path("logs.jsonl"))
    step = store.build_args(
        {
            "tool": "SearchLog",
            "arguments": {"level": "ERROR", "text": "cpu_pressure", "limit": 2},
        },
        SCOPE,
    )
    arguments = cast(JsonDict, step["arguments"])

    assert arguments == {
        "service": "worker",
        "level": "ERROR",
        "text": "cpu_pressure",
        "from": SCOPE["from"],
        "to": SCOPE["to"],
        "limit": 2,
    }
    assert "Query" not in arguments


@pytest.mark.asyncio
async def test_file_log_store_filters_by_scope(tmp_path: Path) -> None:
    log_file = tmp_path / "logs.json"
    log_file.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-07-11T06:00:00Z",
                    "level": "ERROR",
                    "service": "worker",
                    "event": "cpu_pressure",
                    "message": "worker cpu_pressure",
                    "secret": "must-not-leak",
                },
                {
                    "timestamp": "2026-07-11T07:00:00Z",
                    "level": "ERROR",
                    "service": "worker",
                    "event": "late",
                    "message": "outside window",
                },
                {
                    "timestamp": "2026-07-11T06:00:00Z",
                    "level": "ERROR",
                    "service": "checkout",
                    "event": "timeout",
                    "message": "other service",
                },
            ]
        ),
        encoding="utf-8",
    )
    store = FileLogStore(file_path=log_file)
    step = store.build_args({"tool": "SearchLog"}, SCOPE)
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert result["recordCount"] == 1
    assert result["excludedRecordCount"] == 2
    assert result["records"][0]["event"] == "cpu_pressure"
    assert "must-not-leak" not in json.dumps(result["records"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_file_log_store_reads_jsonl_and_filters_query_fields(tmp_path: Path) -> None:
    log_file = tmp_path / "logs.jsonl"
    log_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-07-11T06:00:00Z",
                        "level": "ERROR",
                        "service": "worker",
                        "event": "cpu_pressure",
                        "message": "worker cpu_pressure exceeded threshold",
                        "secret": "must-not-leak",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-11T06:01:00Z",
                        "level": "INFO",
                        "service": "worker",
                        "event": "cpu_pressure",
                        "message": "worker recovered",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-07-11T06:02:00Z",
                        "level": "ERROR",
                        "service": "worker",
                        "event": "timeout",
                        "message": "upstream timeout",
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )
    store = FileLogStore(file_path=log_file)
    step = store.build_args(
        {
            "tool": "SearchLog",
            "arguments": {"Query": 'level:"ERROR" AND text:"cpu_pressure"'},
        },
        SCOPE,
    )
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert result["recordCount"] == 1
    assert result["records"][0]["event"] == "cpu_pressure"
    assert result["excludedRecordCount"] == 2
    assert "must-not-leak" not in json.dumps(result["records"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_file_log_store_reads_newest_directory_files_first(tmp_path: Path) -> None:
    older = tmp_path / "app-1.jsonl"
    newer = tmp_path / "app-2.jsonl"
    older.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-11T06:00:00Z",
                "level": "ERROR",
                "service": "worker",
                "event": "older",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-11T06:01:00Z",
                "level": "ERROR",
                "service": "worker",
                "event": "newer",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(older, (1_000_000_000, 1_000_000_000))
    os.utime(newer, (1_000_000_100, 1_000_000_100))

    store = FileLogStore(file_path=tmp_path, max_records=1)
    step = store.build_args({"tool": "SearchLog", "arguments": {"Limit": 10}}, SCOPE)
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert result["recordCount"] == 1
    assert result["records"][0]["event"] == "newer"


@pytest.mark.asyncio
async def test_file_log_store_supports_glob_paths(tmp_path: Path) -> None:
    for name, event in (("app-a.jsonl", "alpha"), ("app-b.jsonl", "beta")):
        (tmp_path / name).write_text(
            json.dumps(
                {
                    "timestamp": "2026-07-11T06:00:00Z",
                    "level": "ERROR",
                    "service": "worker",
                    "event": event,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    store = FileLogStore(file_path=tmp_path / "app-*.jsonl")
    step = store.build_args(
        {"tool": "SearchLog", "arguments": {"Query": 'event:"beta"'}},
        SCOPE,
    )
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert [record["event"] for record in result["records"]] == ["beta"]


@pytest.mark.asyncio
async def test_file_log_store_bounds_jsonl_reads_by_tail_bytes(tmp_path: Path) -> None:
    log_file = tmp_path / "logs.jsonl"
    omitted = {
        "timestamp": "2026-07-11T05:59:00Z",
        "level": "ERROR",
        "service": "worker",
        "event": "omitted",
        "message": "x" * 400,
    }
    kept = {
        "timestamp": "2026-07-11T06:00:00Z",
        "level": "ERROR",
        "service": "worker",
        "event": "kept",
    }
    kept_line = json.dumps(kept)
    log_file.write_text(
        json.dumps(omitted) + "\n" + kept_line + "\n",
        encoding="utf-8",
    )
    store = FileLogStore(file_path=log_file, max_bytes=len(kept_line) + 10)
    step = store.build_args({"tool": "SearchLog", "arguments": {"Limit": 10}}, SCOPE)
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert [record["event"] for record in result["records"]] == ["kept"]


@pytest.mark.asyncio
async def test_file_log_store_rejects_oversized_json_array(tmp_path: Path) -> None:
    log_file = tmp_path / "logs.json"
    log_file.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-07-11T06:00:00Z",
                    "level": "ERROR",
                    "service": "worker",
                    "event": "cpu_pressure",
                }
            ]
        ),
        encoding="utf-8",
    )
    store = FileLogStore(file_path=log_file, max_bytes=20)
    step = store.build_args({"tool": "SearchLog", "arguments": {"Limit": 10}}, SCOPE)

    with pytest.raises(ValueError, match="JSONL"):
        await store.search(step=step, scope=SCOPE, owner_user_id="user-a")


@pytest.mark.asyncio
async def test_file_log_store_normalizes_epoch_times_and_skips_bad_lines(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "logs.jsonl"
    epoch_ms = int(NOW.timestamp() * 1000)
    log_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "time": epoch_ms,
                        "level": "ERROR",
                        "service": "worker",
                        "event": "epoch_ms",
                    }
                ),
                json.dumps(
                    {
                        "time": int(NOW.timestamp()),
                        "level": "ERROR",
                        "service": "worker",
                        "event": "epoch_seconds",
                    }
                ),
                "{not-json",
                json.dumps(["not", "a", "record"]),
            ]
        ),
        encoding="utf-8",
    )
    store = FileLogStore(file_path=log_file)
    step = store.build_args({"tool": "SearchLog", "arguments": {"Limit": 10}}, SCOPE)
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert [record["event"] for record in result["records"]] == [
        "epoch_ms",
        "epoch_seconds",
    ]
    assert result["excludedRecordCount"] == 2
    assert cast(str, result["records"][0]["timestamp"]).endswith("+00:00")


@pytest.mark.parametrize(
    "query",
    ['level:"ERROR" OR event:"cpu_pressure"', 'level:"ERROR" | stats count()'],
    ids=["or-operator", "pipeline"],
)
def test_file_log_store_rejects_unsupported_query_syntax(
    tmp_path: Path, query: str
) -> None:
    store = FileLogStore(file_path=tmp_path / "logs.jsonl")

    with pytest.raises(ValueError):
        store.build_args(
            {"tool": "SearchLog", "arguments": {"Query": query}},
            SCOPE,
        )


@pytest.mark.asyncio
async def test_build_log_store_passes_file_reading_limits(tmp_path: Path) -> None:
    log_file = tmp_path / "logs.jsonl"
    log_file.write_text(
        "\n".join(
            json.dumps(
                {
                    "timestamp": "2026-07-11T06:00:00Z",
                    "level": "ERROR",
                    "service": "worker",
                    "event": event,
                }
            )
            for event in ("first", "second")
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "logStore": {
                    "type": "file",
                    "filePath": str(log_file),
                    "format": "jsonl",
                    "maxBytes": 4096,
                    "maxRecords": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    store = build_log_store(config_path=config_path)
    step = store.build_args({"tool": "SearchLog", "arguments": {"Limit": 10}}, SCOPE)
    result = await store.search(step=step, scope=SCOPE, owner_user_id="user-a")

    assert isinstance(store, FileLogStore)
    assert [record["event"] for record in result["records"]] == ["first"]

    config_path.write_text(
        json.dumps(
            {"logStore": {"type": "file", "filePath": str(log_file), "format": "csv"}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProjectConfigurationError):
        build_log_store(config_path=config_path)

    for invalid in ({"maxBytes": 0}, {"maxRecords": True}):
        config_path.write_text(
            json.dumps(
                {
                    "logStore": {
                        "type": "file",
                        "filePath": str(log_file),
                        **invalid,
                    }
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ProjectConfigurationError):
            build_log_store(config_path=config_path)


@pytest.mark.asyncio
async def test_file_log_store_drives_diagnostic_without_mcp(
    migrated_database_url: str, tmp_path: Path
) -> None:
    log_file = tmp_path / "incident-logs.json"
    log_file.write_text(
        json.dumps(
            [
                {
                    "timestamp": "2026-07-11T06:00:00Z",
                    "level": "ERROR",
                    "service": "worker",
                    "event": "cpu_pressure",
                    "message": "worker cpu_pressure exceeded threshold",
                }
            ]
        ),
        encoding="utf-8",
    )
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(create_memory_session_factory(engine))
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-file-logs",
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
        service = AiopsDiagnosticService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, FakeLlmProvider()),
            retrieval_tool=KnowledgeRetrievalTool(
                embedding_model=FakeEmbeddingModel(),
                vector_store=FakeVectorStore([]),
                rerank_model=FakeRerankModel(),
            ),
            log_store=FileLogStore(file_path=log_file),
            case_persistor=DiagnosisCasePersistor(
                repositories=repositories,
                index_task_scheduler=FakeCaseIndexScheduler(),
            ),
        )

        events = [
            event
            async for event in service.stream(
                task=task,
                accessible_knowledge_base_ids=(),
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
        evidence = await repositories.diagnostics.list_evidence(
            owner_user_id="user-a",
            task_id=task.id,
        )
    finally:
        await engine.dispose()

    assert persisted is not None
    assert persisted.status == "succeeded"
    assert reports[0].payload["reportGeneration"] == "llm"
    assert "cpu_pressure" in reports[0].content
    log_evidence = [item for item in evidence if item.kind == "log"]
    assert log_evidence
    assert "cpu_pressure" in log_evidence[0].summary
    assert [event["type"] for event in events][-1] == "complete"


def test_build_log_store_validates_config(tmp_path: Path) -> None:
    mcp = cast(LocalMcpClient, FakeMcpClient())
    config_path = tmp_path / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "logStore": {"type": "file", "filePath": "logs.json"},
                "clsLogUpload": {"region": "ap-guangzhou", "topicId": "topic-a"},
            }
        ),
        encoding="utf-8",
    )
    assert isinstance(build_log_store(config_path=config_path), FileLogStore)

    config_path.write_text(
        json.dumps(
            {
                "logStore": {"type": "cls", "filePath": ""},
                "clsLogUpload": {"region": "ap-guangzhou", "topicId": "topic-a"},
            }
        ),
        encoding="utf-8",
    )
    assert isinstance(
        build_log_store(config_path=config_path, mcp_client=mcp), ClsLogStore
    )

    # A config without a logStore section defaults to the CLS store.
    config_path.write_text(
        json.dumps({"clsLogUpload": {"region": "ap-guangzhou", "topicId": "topic-a"}}),
        encoding="utf-8",
    )
    assert isinstance(
        build_log_store(config_path=config_path, mcp_client=mcp), ClsLogStore
    )

    config_path.write_text(json.dumps({"logStore": {"type": "file"}}), encoding="utf-8")
    with pytest.raises(ProjectConfigurationError):
        build_log_store(config_path=config_path)

    config_path.write_text(json.dumps({"logStore": {"type": "splunk"}}), encoding="utf-8")
    with pytest.raises(ProjectConfigurationError):
        build_log_store(config_path=config_path)
