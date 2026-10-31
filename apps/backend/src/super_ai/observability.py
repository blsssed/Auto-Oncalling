"""监控链路第 0 层：请求关联、结构化日志与递归脱敏。

链路位置：FastAPI 中间件/后台任务 → emit_event → 本地 JSON 日志
上游调用：api/app.py 的 observe_request、jobs/runtime.py、MCP/AIOps 各模块
下游消费：运维日志采集、requestId 关联排查、错误分类
设计约束：
- 只输出单行 JSON，禁止原始 header/body/token/CLS 凭据进入日志；
- requestId 通过 ContextVar 传播，必须在 finally 中 reset；
- 脱敏递归作用于 mapping/list/tuple，且先看 key 再看 value。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from contextvars import ContextVar, Token
from time import monotonic
from typing import cast

_request_id: ContextVar[str | None] = ContextVar("super_ai_request_id", default=None)
_STRUCTURED_HANDLER_NAME = "super_ai_structured_events"
_SENSITIVE_KEYS = {
    "access_token",
    "accesstoken",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "key",
    "password",
    "secret",
    "secret_id",
    "secret_key",
    "secretid",
    "secretkey",
    "token",
}


def set_request_id(request_id: str) -> Token[str | None]:
    """把当前协程的 requestId 绑定到 ContextVar，返回用于恢复的 token。

    调用方必须在 finally 中把 token 交给 reset_request_id，否则请求之间
    会串用同一个 requestId。
    """
    return _request_id.set(request_id)


def configure_structured_logging() -> None:
    """启用 super_ai 命名空间的单行 JSON 日志 handler（幂等）。

    子 logger 可能被第三方库或测试单独禁用，这里显式重新启用；
    handler 以固定 name 识别，重复调用不会叠加输出。
    """
    logger = logging.getLogger("super_ai")
    logger.disabled = False
    logger.setLevel(logging.INFO)
    for name, configured_logger in logger.manager.loggerDict.items():
        if name.startswith("super_ai.") and isinstance(configured_logger, logging.Logger):
            configured_logger.disabled = False
    # 按 name 判断而不是按 handler 数量，保证多次 create_app/测试初始化只挂一个 handler。
    if any(handler.get_name() == _STRUCTURED_HANDLER_NAME for handler in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.set_name(_STRUCTURED_HANDLER_NAME)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def current_request_id() -> str | None:
    """返回当前协程绑定的 requestId；未绑定时返回 None。

    供追踪旁路把 trace 与结构化日志关联（例如 Langfuse 的 metadata）。
    """
    return _request_id.get()


def reset_request_id(token: Token[str | None]) -> None:
    """恢复 set_request_id 之前的上下文，通常在请求 finally 中调用。"""
    _request_id.reset(token)


def emit_event(logger: logging.Logger, event: str, **fields: object) -> None:
    """输出一条紧凑 JSON 事件，自动附带 requestId 并递归脱敏。

    事件字段由调用方传入；不要传入原始请求体、工具参数值或模型输出。
    """
    payload: dict[str, object] = {"event": event}
    request_id = _request_id.get()
    if request_id is not None:
        payload["requestId"] = request_id
    payload.update(fields)
    # ensure_ascii=True 避免多行/不可见字符破坏“一行一条日志”的采集约定。
    encoded = json.dumps(
        _redact(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    logger.info(encoded)


def elapsed_ms(started_at: float) -> float:
    """返回从 monotonic 起点到现在的毫秒数，避免受系统时钟回拨影响。"""
    return round((monotonic() - started_at) * 1000, 3)


def _redact(value: object, *, parent_key: str | None = None) -> object:
    """递归复制并脱敏任意 JSON 形状；敏感 key 的整个 value 直接替换。

    parent_key 会向下传递到 list/tuple 元素，保证
    ``{"headers": [{"authorization": ...}]}`` 这类嵌套结构也能命中。
    """
    if parent_key is not None and _is_sensitive_key(parent_key):
        return "[redacted]"
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): _redact(item, parent_key=str(key)) for key, item in mapping.items()}
    if isinstance(value, list):
        return [_redact(item, parent_key=parent_key) for item in cast(list[object], value)]
    if isinstance(value, tuple):
        return [_redact(item, parent_key=parent_key) for item in cast(tuple[object, ...], value)]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    """判断字段名是否敏感：精确名单 + 常见后缀规则。"""
    normalized = key.replace("-", "_").lower()
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_key", "_password", "_secret", "_token")
    )
