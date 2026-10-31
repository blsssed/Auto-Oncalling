from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config

from super_ai.chat.memory import ChatContextLimitReached, ChatMemoryService
from super_ai.llm import LlmProvider
from super_ai.memory.database import create_memory_engine, create_memory_session_factory
from super_ai.memory.sqlite import create_sqlite_memory_repositories
from super_ai.tracing import TraceCall


@dataclass
class FakeMessage:
    content: str


class FakeChatModel:
    def __init__(self) -> None:
        self.inputs: list[object] = []
        self.last_config: Mapping[str, object] | None = None

    async def ainvoke(
        self, input: object, config: Mapping[str, object] | None = None
    ) -> object:
        self.inputs.append(input)
        self.last_config = config
        return FakeMessage("用户正在排查 API；已确认需要保留工具结果和后续任务。")


class FakeProvider:
    def __init__(self) -> None:
        self.model = FakeChatModel()

    def create_chat_model(self) -> FakeChatModel:
        return self.model


@pytest.fixture
def migrated_database_url(tmp_path: Path) -> str:
    database_path = tmp_path / "memory.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path}")
    command.upgrade(config, "head")
    return f"sqlite+aiosqlite:///{database_path}"


@pytest.mark.asyncio
async def test_thirty_turn_mode_compacts_without_deleting_history(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(
            create_memory_session_factory(engine)
        )
        session = await repositories.chat.create_session(
            owner_user_id="user-a", session_id="chat-thirty"
        )
        for index in range(30):
            for role in ("user", "assistant"):
                await repositories.chat.append_message(
                    owner_user_id="user-a",
                    message_id=f"message-{index}-{role}",
                    session_id=session.id,
                    role=role,
                    content=f"turn {index} {role}",
                )
        history = await repositories.chat.list_messages(
            owner_user_id="user-a", session_id=session.id
        )
        provider = FakeProvider()
        service = ChatMemoryService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            context_window_tokens=131072,
        )

        prepared = await service.prepare_message(
            owner_user_id="user-a",
            session=session,
            history=history,
            system_prompt="你是助手。",
            content="继续",
        )
        persisted = await repositories.chat.list_messages(
            owner_user_id="user-a", session_id=session.id
        )
    finally:
        await engine.dispose()

    assert len(provider.model.inputs) == 1
    assert prepared.session.compacted_message_count == 60
    assert prepared.session.memory_summary is not None
    assert len(prepared.messages) == 1
    assert len(persisted) == 60


@pytest.mark.asyncio
async def test_context_threshold_and_manual_mode_are_session_scoped(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(
            create_memory_session_factory(engine)
        )
        threshold_session = await repositories.chat.create_session(
            owner_user_id="user-a", session_id="chat-threshold"
        )
        manual_session = await repositories.chat.create_session(
            owner_user_id="user-a", session_id="chat-manual"
        )
        for session in (threshold_session, manual_session):
            await repositories.chat.append_message(
                owner_user_id="user-a",
                message_id=f"message-{session.id}",
                session_id=session.id,
                role="user",
                content="需要保留的历史内容 " * 30,
            )
        await repositories.chat.update_memory_state(
            owner_user_id="user-a",
            session_id=threshold_session.id,
            memory_mode="context_70_percent",
        )
        provider = FakeProvider()
        service = ChatMemoryService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            context_window_tokens=120,
        )
        threshold_record = await repositories.chat.get_session(
            owner_user_id="user-a", session_id="chat-threshold"
        )
        manual_record = await repositories.chat.get_session(
            owner_user_id="user-a", session_id="chat-manual"
        )
        assert threshold_record is not None and manual_record is not None
        threshold_history = await repositories.chat.list_messages(
            owner_user_id="user-a", session_id=threshold_record.id
        )
        manual_history = await repositories.chat.list_messages(
            owner_user_id="user-a", session_id=manual_record.id
        )

        threshold_result = await service.prepare_message(
            owner_user_id="user-a",
            session=threshold_record,
            history=threshold_history,
            system_prompt="你是助手。",
            content="继续",
        )
        manual_result = await service.set_mode(
            owner_user_id="user-a",
            session=manual_record,
            mode="manual",
            history=manual_history,
            system_prompt="你是助手。",
        )
    finally:
        await engine.dispose()

    assert threshold_result.session.memory_mode == "context_70_percent"
    assert threshold_result.session.compacted_message_count == 1
    assert manual_result.memory_mode == "manual"
    assert manual_result.compacted_message_count == 1
    assert len(provider.model.inputs) == 2


@pytest.mark.asyncio
async def test_hard_limit_rejects_candidate_without_persisting_it(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(
            create_memory_session_factory(engine)
        )
        session = await repositories.chat.create_session(
            owner_user_id="user-a", session_id="chat-limit"
        )
        service = ChatMemoryService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, FakeProvider()),
            context_window_tokens=20,
        )

        with pytest.raises(ChatContextLimitReached):
            await service.prepare_message(
                owner_user_id="user-a",
                session=session,
                history=[],
                system_prompt="system prompt with enough context",
                content="a candidate message that must not be saved",
            )
        history = await repositories.chat.list_messages(
            owner_user_id="user-a", session_id=session.id
        )
    finally:
        await engine.dispose()

    assert history == []


class _RecordingTracingProvider:
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


@pytest.mark.asyncio
async def test_compaction_passes_trace_config_and_flushes(
    migrated_database_url: str,
) -> None:
    engine = create_memory_engine(migrated_database_url)
    try:
        repositories = create_sqlite_memory_repositories(
            create_memory_session_factory(engine)
        )
        session = await repositories.chat.create_session(
            owner_user_id="user-a", session_id="chat-trace"
        )
        await repositories.chat.append_message(
            owner_user_id="user-a",
            message_id="message-trace",
            session_id=session.id,
            role="user",
            content="需要压缩的历史内容",
        )
        history = await repositories.chat.list_messages(
            owner_user_id="user-a", session_id=session.id
        )
        provider = FakeProvider()
        tracing = _RecordingTracingProvider()
        service = ChatMemoryService(
            repositories=repositories,
            llm_provider=cast(LlmProvider, provider),
            context_window_tokens=120,
            tracing_provider=tracing,
        )
        record = await repositories.chat.get_session(
            owner_user_id="user-a", session_id="chat-trace"
        )
        assert record is not None

        await service.set_mode(
            owner_user_id="user-a",
            session=record,
            mode="manual",
            history=history,
            system_prompt="你是助手。",
        )
    finally:
        await engine.dispose()

    assert provider.model.last_config is not None
    assert provider.model.last_config["metadata"] == {
        "langfuse_trace_name": "chat-memory-compaction"
    }
    assert tracing.captured["session_id"] == "chat-trace"
    assert tracing.captured["user_id"] == "user-a"
    assert tracing.flush_calls == 1
