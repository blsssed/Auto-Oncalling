"""可选 Langfuse 追踪：聊天 Agent runner 的回调注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest

from super_ai.chat.streaming import ChatAgentRequest, LangChainChatAgentRunner
from super_ai.tracing import TraceCall


class _FakeAgent:
    def __init__(self) -> None:
        self.captured: dict[str, object] = {}

    def astream_events(
        self, _input: object, *, version: str, **kwargs: object
    ) -> AsyncIterator[dict[str, object]]:
        self.captured = {"version": version, **kwargs}

        async def _gen() -> AsyncIterator[dict[str, object]]:
            return
            yield  # pragma: no cover - 使函数成为异步生成器

        return _gen()


class _FakeProvider:
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
        handler = cast(Any, object())
        return TraceCall(handler=handler, metadata={"langfuse_trace_name": name})

    def flush(self) -> None:
        self.flush_calls += 1


class _BreakingProvider:
    def trace_for(self, **_kwargs: object) -> TraceCall:
        raise RuntimeError("tracing failed")

    def flush(self) -> None:
        raise RuntimeError("flush failed")


class _FakeMessage:
    role = "user"
    content = "hi"


def _request(session_id: str = "chat-1") -> ChatAgentRequest:
    return ChatAgentRequest(
        owner_user_id="user-a",
        session_id=session_id,
        messages=(cast(Any, _FakeMessage()),),
        accessible_knowledge_base_ids=(),
        system_prompt="你是助手。",
    )


class _FakeLlmProvider:
    def create_chat_model(self) -> object:
        return object()


def _runner(
    tracing_provider: object | None, monkeypatch: pytest.MonkeyPatch
) -> tuple[LangChainChatAgentRunner, _FakeAgent]:
    agent = _FakeAgent()

    def _fake_create_agent(**_kwargs: object) -> _FakeAgent:
        return agent

    monkeypatch.setattr("super_ai.chat.streaming._create_langchain_agent", _fake_create_agent)
    return (
        LangChainChatAgentRunner(
            llm_provider=cast(Any, _FakeLlmProvider()),
            retrieval_tool=cast(Any, object()),
            tracing_provider=cast(Any, tracing_provider)
            if tracing_provider is not None
            else None,
        ),
        agent,
    )


@pytest.mark.asyncio
async def test_runner_passes_trace_config_when_provider_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeProvider()
    runner, agent = _runner(provider, monkeypatch)

    _events = [event async for event in runner.stream(_request())]

    config = cast(dict[str, object], agent.captured["config"])
    callbacks = cast(list[object], config["callbacks"])
    assert len(callbacks) == 1
    assert config["metadata"] == {"langfuse_trace_name": "chat-agent"}
    assert provider.captured == {
        "name": "chat-agent",
        "session_id": "chat-1",
        "user_id": "user-a",
        "request_id": None,
    }
    assert provider.flush_calls == 1


@pytest.mark.asyncio
async def test_runner_passes_no_config_without_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, agent = _runner(None, monkeypatch)

    _events = [event async for event in runner.stream(_request())]

    assert "config" not in agent.captured


@pytest.mark.asyncio
async def test_runner_survives_tracing_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    runner, _agent = _runner(_BreakingProvider(), monkeypatch)

    _events = [event async for event in runner.stream(_request())]

    assert _events == []
