"""监控链路第 3 层：AIOps LLM 调用成本与延迟统计。

链路位置：planner/replanner/report 的模型调用 → LlmUsage → step/report/task payload
上游调用：AiopsDiagnosticService._planner / _replanner / _report
下游消费：诊断任务、步骤、报告的 usage 字段（前端展示 token/耗时）
设计约束：
- 统计以 provider 返回的 usage_metadata 为准，缺失时退化为 0；
- merge 是纯加法，调用方负责把各阶段结果汇总；
- 延迟使用 monotonic 计时并夹紧为非负。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter
from typing import cast


@dataclass(frozen=True)
class LlmUsage:
    """累计的调用次数、provider 上报 token 与耗时。"""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: int = 0

    def merge(self, other: LlmUsage) -> LlmUsage:
        """返回两个统计的逐字段之和，不修改原对象。"""
        return LlmUsage(
            calls=self.calls + other.calls,
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            latency_ms=self.latency_ms + other.latency_ms,
        )

    def to_dict(self) -> dict[str, int]:
        """序列化成 camelCase，直接写入任务/报告 payload。"""
        return {
            "calls": self.calls,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "totalTokens": self.total_tokens,
            "latencyMs": self.latency_ms,
        }


def usage_of(value: object) -> LlmUsage:
    """从已持久化的 state/payload 中容错读取 usage；缺失字段按 0 处理。"""
    if not isinstance(value, Mapping):
        return LlmUsage()
    stored = cast(Mapping[str, object], value)
    return LlmUsage(
        calls=_as_int(stored.get("calls")),
        prompt_tokens=_as_int(stored.get("promptTokens")),
        completion_tokens=_as_int(stored.get("completionTokens")),
        total_tokens=_as_int(stored.get("totalTokens")),
        latency_ms=_as_int(stored.get("latencyMs")),
    )


def usage_from_response(response: object, *, latency_ms: int) -> LlmUsage:
    """记录一次模型调用，并尽量读取 provider 的 usage_metadata。

    provider 未上报 metadata 时 token 记 0；total 缺失时退化为
    prompt + completion，仍然可观测但可能偏低。
    """
    prompt = completion = total = 0
    metadata = getattr(response, "usage_metadata", None)
    if isinstance(metadata, Mapping):
        values = cast(Mapping[str, object], metadata)
        prompt = _as_int(values.get("input_tokens"))
        completion = _as_int(values.get("output_tokens"))
        # 某些 provider 不返回 total_tokens，此时用输入+输出补齐。
        total = _as_int(values.get("total_tokens")) or prompt + completion
    return LlmUsage(
        calls=1,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        latency_ms=max(0, latency_ms),
    )


class LlmCallTimer:
    """用 perf_counter 测量单次模型调用耗时。"""

    def __init__(self) -> None:
        self._started = perf_counter()

    def elapsed_ms(self) -> int:
        """返回毫秒耗时；异常时钟回拨也不会得到负数。"""
        return max(0, int((perf_counter() - self._started) * 1000))


def _as_int(value: object) -> int:
    """只接受真正的 int；bool 是 int 子类，必须排除。"""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
