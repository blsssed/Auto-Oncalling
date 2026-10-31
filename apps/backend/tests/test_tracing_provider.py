"""可选 Langfuse 追踪：provider 行为（降级、flush、metadata 输出）。"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest

from super_ai.tracing import (
    DEFAULT_LANGFUSE_HOST,
    LangfuseTracingProvider,
    TracingSettings,
)


class _FakeLangfuse:
    last_kwargs: dict[str, object] = {}
    flush_calls: int = 0

    def __init__(self, **kwargs: object) -> None:
        _FakeLangfuse.last_kwargs = dict(kwargs)
        self.flush_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1


class _FakeCallbackHandler:
    def __init__(self, *, public_key: str | None = None) -> None:
        self.public_key = public_key


def _patch_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_langfuse = ModuleType("langfuse")
    setattr(fake_langfuse, "Langfuse", _FakeLangfuse)  # noqa: B010 - ModuleType 动态属性
    fake_langchain = ModuleType("langfuse.langchain")
    setattr(fake_langchain, "CallbackHandler", _FakeCallbackHandler)  # noqa: B010
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain)


def test_trace_for_builds_handler_and_reserved_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_langfuse(monkeypatch)
    provider = LangfuseTracingProvider(
        TracingSettings(public_key="pk", secret_key="sk", host="https://langfuse.test")
    )
    trace = provider.trace_for(
        name="chat-agent", session_id="session-1", user_id="user-1", request_id="req-1"
    )
    assert trace is not None
    assert isinstance(trace.handler, _FakeCallbackHandler)
    assert trace.metadata == {
        "langfuse_trace_name": "chat-agent",
        "langfuse_session_id": "session-1",
        "langfuse_user_id": "user-1",
        "requestId": "req-1",
    }
    assert _FakeLangfuse.last_kwargs == {
        "public_key": "pk",
        "secret_key": "sk",
        "host": "https://langfuse.test",
    }


def test_trace_for_degrades_to_none_when_sdk_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_langfuse(monkeypatch)
    provider = LangfuseTracingProvider(TracingSettings(public_key="pk", secret_key="sk"))

    def _boom(**_kwargs: object) -> object:
        raise RuntimeError("langfuse unavailable")

    provider._ensure_client = _boom  # type: ignore[method-assign]
    assert provider.trace_for(name="n", session_id="s", user_id="u") is None


def test_flush_never_raises_before_client_creation() -> None:
    provider = LangfuseTracingProvider(
        TracingSettings(public_key="pk", secret_key="sk", host=DEFAULT_LANGFUSE_HOST)
    )
    provider.flush()
    assert provider._client_initialized is False  # pyright: ignore[reportPrivateUsage]


def test_flush_uses_shared_client(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_langfuse(monkeypatch)
    provider = LangfuseTracingProvider(TracingSettings(public_key="pk", secret_key="sk"))
    provider.trace_for(name="n", session_id="s", user_id="u")
    provider.flush()
    provider.flush()
    client: Any = provider._client  # pyright: ignore[reportPrivateUsage]
    assert client.flush_calls == 2
