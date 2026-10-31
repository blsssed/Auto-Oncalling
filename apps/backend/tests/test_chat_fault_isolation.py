"""聊天流可选依赖降级：MCP 工具源、记忆与标题故障不再终止整条流。"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text

from super_ai.chat.streaming import (
    ChatAgentContentDelta,
    ChatAgentEvent,
    ChatAgentNotice,
    ChatAgentRequest,
    ChatStreamingService,
    LangChainChatAgentRunner,
)
from super_ai.mcp_client import McpClientError
from super_ai.memory.database import create_memory_engine
from super_ai.memory.repositories import (
    ChatMessageRecord,
    ChatSessionRecord,
    MemoryRepositories,
)


class FakeChatAgentRunner:
    def __init__(
        self,
        events: list[ChatAgentEvent],
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.error = error
        self.requests: list[ChatAgentRequest] = []

    async def stream(self, request: ChatAgentRequest) -> AsyncIterator[ChatAgentEvent]:
        self.requests.append(request)
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


class _FakeMessage:
    role = "user"
    content = "hi"


class _FakeLlmProvider:
    def create_chat_model(self) -> object:
        return object()


class _FakeAgent:
    def astream_events(
        self, _input: object, *, version: str, **kwargs: object
    ) -> AsyncIterator[dict[str, object]]:
        async def _gen() -> AsyncIterator[dict[str, object]]:
            return
            yield  # pragma: no cover - 使函数成为异步生成器

        return _gen()


class _BreakingMcpClient:
    async def discover_tools(self) -> list[object]:
        raise McpClientError("SYSTEM_UNAVAILABLE", "connection refused")

    async def get_langchain_tools(self) -> list[object]:
        return []


class _BreakingMcpClientProvider:
    async def client_for_user(self, *, owner_user_id: str) -> object:
        raise RuntimeError("mcp connection storage unavailable")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session(session_id: str = "chat_1") -> ChatSessionRecord:
    return ChatSessionRecord(
        id=session_id,
        owner_user_id="user_1",
        title="New chat",
        created_at=_now(),
        updated_at=_now(),
    )


class InMemoryChatRepository:
    def __init__(self, session: ChatSessionRecord) -> None:
        self.session = session
        self.messages: list[ChatMessageRecord] = []
        self.title_updates = 0

    async def create_session(self, **_kwargs: object) -> ChatSessionRecord:
        return self.session

    async def get_session(self, **_kwargs: object) -> ChatSessionRecord | None:
        return self.session

    async def update_session_title(self, **_kwargs: object) -> ChatSessionRecord | None:
        self.title_updates += 1
        return self.session

    async def list_sessions(self, **_kwargs: object) -> list[ChatSessionRecord]:
        return [self.session]

    async def append_message(
        self,
        *,
        owner_user_id: str,
        message_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, object] | None = None,
        **_kwargs: object,
    ) -> ChatMessageRecord:
        message = ChatMessageRecord(
            id=message_id,
            owner_user_id=owner_user_id,
            session_id=session_id,
            role=role,
            content=content,
            metadata=metadata or {},
            created_at=_now(),
        )
        self.messages.append(message)
        return message

    async def clear_messages(self, **_kwargs: object) -> int:
        return 0

    async def delete_session(self, **_kwargs: object) -> bool:
        return False

    async def list_messages(self, **_kwargs: object) -> list[ChatMessageRecord]:
        return list(self.messages)


def _repositories(chat_repository: object) -> MemoryRepositories:
    return MemoryRepositories(
        chat=cast(Any, chat_repository),
        documents=cast(Any, object()),
        document_index_tasks=cast(Any, object()),
        diagnostics=cast(Any, object()),
    )


class _BreakingMemoryService:
    context_window_tokens = 131072

    async def prepare_message(self, **_kwargs: object) -> object:
        raise RuntimeError("memory storage unavailable")

    async def refresh_usage(self, **kwargs: object) -> object:
        return kwargs["session"]


@pytest.mark.asyncio
async def test_notice_event_passes_through_and_stream_completes() -> None:
    session = _session()
    repository = InMemoryChatRepository(session)
    runner = FakeChatAgentRunner(
        events=[
            ChatAgentNotice(code="CHAT_MCP_TOOLS_UNAVAILABLE"),
            ChatAgentContentDelta("好"),
        ]
    )
    service = ChatStreamingService(
        repositories=_repositories(repository),
        agent_runner=runner,
    )

    events = [
        event
        async for event in service.stream_message(
            owner_user_id="user_1",
            session=session,
            content="你好",
            accessible_knowledge_base_ids=(),
        )
    ]

    assert [event["type"] for event in events] == ["notice", "content.delta", "complete"]
    notice_payload = cast(dict[str, Any], events[0]["notice"])
    assert notice_payload["code"] == "CHAT_MCP_TOOLS_UNAVAILABLE"
    assert "MCP" in notice_payload["message"]
    complete_result = cast(dict[str, Any], events[-1]["result"])
    assert complete_result["message"]["role"] == "assistant"
    assert complete_result["session"]["id"] == "chat_1"


@pytest.mark.asyncio
async def test_memory_failure_degrades_to_current_message_only() -> None:
    session = _session()
    repository = InMemoryChatRepository(session)
    runner = FakeChatAgentRunner(events=[ChatAgentContentDelta("答")])
    service = ChatStreamingService(
        repositories=_repositories(repository),
        agent_runner=runner,
        memory_service=cast(Any, _BreakingMemoryService()),
    )

    events = [
        event
        async for event in service.stream_message(
            owner_user_id="user_1",
            session=session,
            content="你好",
            accessible_knowledge_base_ids=(),
        )
    ]

    assert [event["type"] for event in events] == ["notice", "content.delta", "complete"]
    notice_payload = cast(dict[str, Any], events[0]["notice"])
    assert notice_payload["code"] == "CHAT_MEMORY_UNAVAILABLE"
    assert "会话记忆" in notice_payload["message"]
    assert len(runner.requests) == 1
    assert [message.role for message in runner.requests[0].messages] == ["user"]


@pytest.mark.asyncio
async def test_title_failure_does_not_break_the_stream() -> None:
    session = _session()
    repository = InMemoryChatRepository(session)

    async def _breaking_title(**_kwargs: object) -> ChatSessionRecord | None:
        raise RuntimeError("database unavailable")

    repository.update_session_title = _breaking_title  # type: ignore[method-assign]
    service = ChatStreamingService(
        repositories=_repositories(repository),
        agent_runner=FakeChatAgentRunner(events=[ChatAgentContentDelta("答")]),
    )

    events = [
        event
        async for event in service.stream_message(
            owner_user_id="user_1",
            session=session,
            content="你好",
            accessible_knowledge_base_ids=(),
        )
    ]

    assert [event["type"] for event in events] == ["content.delta", "complete"]


@pytest.mark.asyncio
async def test_runner_degrades_when_mcp_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "super_ai.chat.streaming._create_langchain_agent",
        _fake_create_agent,
    )
    runner = LangChainChatAgentRunner(
        llm_provider=cast(Any, _FakeLlmProvider()),
        retrieval_tool=cast(Any, object()),
        mcp_client=cast(Any, _BreakingMcpClient()),
    )

    events = [event async for event in runner.stream(_request())]

    assert events == [ChatAgentNotice(code="CHAT_MCP_TOOLS_UNAVAILABLE")]


@pytest.mark.asyncio
async def test_runner_degrades_when_mcp_client_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "super_ai.chat.streaming._create_langchain_agent",
        _fake_create_agent,
    )
    runner = LangChainChatAgentRunner(
        llm_provider=cast(Any, _FakeLlmProvider()),
        retrieval_tool=cast(Any, object()),
        mcp_client_provider=cast(Any, _BreakingMcpClientProvider()),
    )

    events = [event async for event in runner.stream(_request())]

    assert events == []


def _request() -> ChatAgentRequest:
    return ChatAgentRequest(
        owner_user_id="user-a",
        session_id="chat-1",
        messages=(cast(Any, _FakeMessage()),),
        accessible_knowledge_base_ids=(),
        system_prompt="你是助手。",
    )


def _fake_create_agent(**_kwargs: object) -> _FakeAgent:
    return _FakeAgent()


@pytest.mark.asyncio
async def test_memory_engine_applies_sqlite_pragmas(tmp_path: Path) -> None:
    engine = create_memory_engine(f"sqlite+aiosqlite:///{(tmp_path / 'memory.sqlite3').as_posix()}")
    try:
        async with engine.connect() as connection:
            journal_mode = (
                await connection.execute(text("PRAGMA journal_mode"))
            ).scalar()
            busy_timeout = (
                await connection.execute(text("PRAGMA busy_timeout"))
            ).scalar()
            synchronous = (
                await connection.execute(text("PRAGMA synchronous"))
            ).scalar()
    finally:
        await engine.dispose()

    assert str(journal_mode).lower() == "wal"
    assert busy_timeout == 5000
    assert synchronous == 1  # NORMAL
