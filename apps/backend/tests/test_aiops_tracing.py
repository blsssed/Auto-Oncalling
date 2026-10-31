"""可选 Langfuse 追踪：诊断服务注入与 LangGraph 回调传播门禁。"""

# langgraph 未提供类型存根，与 src/super_ai/aiops/diagnostics.py 的处理方式一致。
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config
from langchain_core.callbacks import BaseCallbackHandler

from super_ai.aiops.diagnostics import AiopsDiagnosticService
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.tracing import TraceCall


class _FakeGraph:
    def __init__(self) -> None:
        self.captured: dict[str, object] = {}

    def astream(
        self, _input: object, **kwargs: object
    ) -> AsyncIterator[Mapping[str, object]]:
        self.captured = dict(kwargs)

        async def _gen() -> AsyncIterator[Mapping[str, object]]:
            return
            yield  # pragma: no cover - 使函数成为异步生成器

        return _gen()


class _RecordingProvider:
    def __init__(self) -> None:
        self.captured: dict[str, object] = {}
        self.flush_calls = 0

    def trace_for(
        self, *, name: str, session_id: str, user_id: str, request_id: str | None = None
    ) -> TraceCall:
        self.captured = {
            "name": name,
            "session_id": session_id,
            "user_id": user_id,
            "request_id": request_id,
        }
        return TraceCall(handler=cast(Any, object()), metadata={"langfuse_trace_name": name})

    def flush(self) -> None:
        self.flush_calls += 1


def _service(
    repositories: object, provider: _RecordingProvider | None, graph: _FakeGraph
) -> AiopsDiagnosticService:
    class _Service(AiopsDiagnosticService):
        def _build_graph(self) -> object:
            return graph

    return _Service(
        repositories=cast(Any, repositories),
        llm_provider=cast(Any, object()),
        retrieval_tool=cast(Any, object()),
        mcp_client=cast(Any, object()),
        tracing_provider=cast(Any, provider) if provider is not None else None,
    )


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "aiops-tracing.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"


@pytest.mark.asyncio
async def test_stream_passes_trace_config_and_flushes_once(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(
            create_memory_session_factory(engine)
        )
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-trace",
            status="accepted",
            query="排查 worker",
            input_payload={},
        )
        graph = _FakeGraph()
        provider = _RecordingProvider()
        service = _service(repositories, provider, graph)

        events = [
            event
            async for event in service.stream(
                task=task, accessible_knowledge_base_ids=()
            )
        ]
    finally:
        await engine.dispose()

    assert events == []
    config = cast(dict[str, object], graph.captured["config"])
    callbacks = cast(list[object], config["callbacks"])
    assert len(callbacks) == 1
    assert config["metadata"] == {"langfuse_trace_name": "aiops-diagnosis"}
    assert provider.captured["session_id"] == "diagnostic-trace"
    assert provider.captured["user_id"] == "user-a"
    assert provider.flush_calls == 1


@pytest.mark.asyncio
async def test_stream_without_provider_omits_config(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(
            create_memory_session_factory(engine)
        )
        task = await repositories.diagnostics.create_task(
            owner_user_id="user-a",
            task_id="diagnostic-no-trace",
            status="accepted",
            query="排查 worker",
            input_payload={},
        )
        graph = _FakeGraph()
        service = _service(repositories, None, graph)

        _events = [
            event
            async for event in service.stream(
                task=task, accessible_knowledge_base_ids=()
            )
        ]
    finally:
        await engine.dispose()

    assert "config" not in graph.captured


def test_langgraph_propagates_callbacks_to_node_invocations() -> None:
    from langchain_core.runnables import RunnableLambda
    from langgraph.graph import END, START, StateGraph
    from typing_extensions import TypedDict

    class _State(TypedDict):
        done: bool

    seen_run_ids: list[object] = []

    class _Recorder(BaseCallbackHandler):
        def on_chain_start(self, *args: object, **kwargs: object) -> None:
            seen_run_ids.append(kwargs.get("run_id", args))

    async def _node(state: _State) -> dict[str, bool]:
        await RunnableLambda(lambda value: value).ainvoke("payload")
        return {"done": True}

    graph = StateGraph(_State)
    graph.add_node("n", _node)
    graph.add_edge(START, "n")
    graph.add_edge("n", END)
    app = graph.compile()
    handler = _Recorder()

    async def _run() -> None:
        async for _update in app.astream(
            {"done": False},
            stream_mode="updates",
            config={"callbacks": [handler]},
        ):
            pass

    import anyio

    anyio.run(_run)
    assert seen_run_ids, "节点内的 runnable 调用必须继承 graph.astream 的 callbacks"
