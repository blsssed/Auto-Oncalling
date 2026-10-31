"""观测旁路：可选的 Langfuse LLM 链路追踪配置与回调 provider。

链路位置：聊天流 / AIOps 诊断流 / 记忆压缩 → 本模块 → Langfuse 云端
上游调用：api/app.py 的 _tracing_provider 装配、各 runner 的 stream()
下游消费：langchain config={"callbacks": [...], "metadata": {...}}、Langfuse 控制台
设计约束：
- 配置缺失、enabled=false 都静默关闭，且绝不导入 langfuse（导入即连接违反项目约定）；
- enabled=true 但凭据为空时明确报配置错误，错误文案不得包含配置值；
- SDK 导入、客户端构造、handler 创建的任何异常都降级为“无追踪”，不进入业务流；
- 客户端按进程共享一个（经 SDK 按 public_key 注册），handler 每次流/调用创建。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from super_ai.observability import emit_event
from super_ai.project_config import ProjectConfigurationError, load_project_config

if TYPE_CHECKING:
    from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger("super_ai.tracing")

DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com"


@dataclass(frozen=True, slots=True)
class TracingSettings:
    """已校验的追踪配置：云端项目凭据与 host。"""

    public_key: str
    secret_key: str
    host: str = DEFAULT_LANGFUSE_HOST


@dataclass(frozen=True, slots=True)
class TraceCall:
    """一次流/调用的追踪载荷：回调 handler + 进 runnable metadata 的字段。

    metadata 使用 langfuse.langchain 的保留键（langfuse_trace_name 等），
    由 handler 在根 run 上应用；其余键原样进入 trace metadata。
    """

    handler: BaseCallbackHandler
    metadata: dict[str, str]


class TracingCallbackProvider(Protocol):
    """追踪回调边界：为一次流/调用产出 handler，失败降级为 None。"""

    def trace_for(
        self,
        *,
        name: str,
        session_id: str,
        user_id: str,
        request_id: str | None = None,
    ) -> TraceCall | None: ...

    def flush(self) -> None: ...


def load_tracing_settings(
    config_path: Path | str | None = None,
) -> TracingSettings | None:
    """读取 langfuse 配置段；返回 None 表示追踪关闭。

    配置缺失、enabled=false 都静默关闭；enabled=true 但 publicKey/secretKey
    为空时明确报配置错误，避免“看似启用实际不上报”的静默失效。
    """
    config = load_project_config(config_path)
    section = config.get("langfuse")
    if section is None:
        return None
    if not isinstance(section, Mapping):
        raise ProjectConfigurationError("langfuse must be an object.")
    values: Mapping[str, object] = cast(Mapping[str, object], section)
    enabled = values.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ProjectConfigurationError("langfuse.enabled must be a boolean.")
    if not enabled:
        return None
    public_key = values.get("publicKey", "")
    secret_key = values.get("secretKey", "")
    if not isinstance(public_key, str) or not public_key.strip():
        raise ProjectConfigurationError(
            "langfuse.publicKey is required when tracing is enabled."
        )
    if not isinstance(secret_key, str) or not secret_key.strip():
        raise ProjectConfigurationError(
            "langfuse.secretKey is required when tracing is enabled."
        )
    host_value = values.get("host", "")
    if host_value in (None, ""):
        host = DEFAULT_LANGFUSE_HOST
    elif isinstance(host_value, str):
        host = host_value.strip() or DEFAULT_LANGFUSE_HOST
    else:
        raise ProjectConfigurationError("langfuse.host must be a string.")
    return TracingSettings(
        public_key=public_key.strip(),
        secret_key=secret_key.strip(),
        host=host,
    )


class LangfuseTracingProvider:
    """持有已校验配置；懒导入 SDK、懒建共享客户端，故障一律降级为无追踪。"""

    def __init__(self, settings: TracingSettings) -> None:
        self._settings = settings
        self._client_initialized = False

    def trace_for(
        self,
        *,
        name: str,
        session_id: str,
        user_id: str,
        request_id: str | None = None,
    ) -> TraceCall | None:
        """为一次流/调用创建 handler；SDK 任何异常都返回 None（无追踪继续）。"""
        try:
            self._ensure_client()
            # 懒导入：仅在实际启用追踪时才加载 langfuse。
            from langfuse.langchain import CallbackHandler

            handler = CallbackHandler(public_key=self._settings.public_key)
        except Exception as exc:  # noqa: BLE001 - 追踪故障绝不能进入业务流
            self._emit_degrade_event(stage="handler", error=exc)
            return None
        metadata: dict[str, str] = {
            "langfuse_trace_name": name,
            "langfuse_session_id": session_id,
            "langfuse_user_id": user_id,
            "requestId": request_id or "",
        }
        return TraceCall(handler=handler, metadata=metadata)

    def flush(self) -> None:
        """best-effort 上报已缓冲数据；未建客户端时是无害 no-op。"""
        if not self._client_initialized:
            return
        try:
            client = self._client_cached()
            flush = getattr(client, "flush", None)
            if callable(flush):
                flush()
        except Exception as exc:  # noqa: BLE001 - flush 故障不外传
            self._emit_degrade_event(stage="flush", error=exc)

    def _ensure_client(self) -> object:
        """懒导入 SDK 并构建共享客户端；成功后缓存初始化标记。"""
        if self._client_initialized:
            return self._client_cached()
        from langfuse import Langfuse

        client = Langfuse(
            public_key=self._settings.public_key,
            secret_key=self._settings.secret_key,
            host=self._settings.host,
        )
        self._client_initialized = True
        # 客户端由 SDK 按 public_key 注册管理；这里只保留引用用于 flush。
        self._client = client
        return client

    def _client_cached(self) -> object:
        return self._client

    def _emit_degrade_event(self, *, stage: str, error: Exception) -> None:
        """记录固定文案的降级事件；不携带配置值与异常详情中的敏感信息。"""
        emit_event(
            logger,
            "tracing_degraded",
            stage=stage,
            errorCategory=type(error).__name__,
        )


def build_tracing_provider(
    config_path: Path | str | None = None,
) -> TracingCallbackProvider | None:
    """按配置构建追踪 provider；追踪关闭时返回 None。

    配置非法时抛 ProjectConfigurationError（与 aiopsAutoDiagnosis 一致），
    由 /config/check 与装配方决定如何呈现。
    """
    settings = load_tracing_settings(config_path)
    if settings is None:
        return None
    return LangfuseTracingProvider(settings)
