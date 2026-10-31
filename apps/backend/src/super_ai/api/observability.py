"""监控链路第 0 层：进程内 HTTP 请求指标。

链路位置：observe_request 中间件 → RequestMetrics → GET /metrics
上游调用：api/app.py 的请求中间件
下游消费：/metrics 返回的 requestCount/failureCount/avgLatencyMs
设计约束：
- 单进程内存计数，重启清零，多 worker 之间不共享；
- 只有 status >= 500 计为 failure；
- 读取必须在锁内复制，避免多字段撕裂读。
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class RequestMetricsSnapshot:
    """某一时刻的请求计数快照，供 /metrics 只读序列化。"""

    request_count: int
    failure_count: int
    total_latency_ms: float


class RequestMetrics:
    """线程安全的进程内计数器；中间件写、/metrics 读。"""

    def __init__(self) -> None:
        self._failure_count = 0
        self._lock = Lock()
        self._request_count = 0
        self._total_latency_ms = 0.0

    def record(self, *, latency_ms: float, status_code: int) -> None:
        """记录一次请求；只有 5xx 计为服务端失败，4xx 属于客户端错误。"""
        with self._lock:
            self._request_count += 1
            self._total_latency_ms += latency_ms
            if status_code >= 500:
                self._failure_count += 1

    def snapshot(self) -> RequestMetricsSnapshot:
        """在锁内一次性复制三个计数，保证 /metrics 读到的是同一时刻的值。"""
        with self._lock:
            return RequestMetricsSnapshot(
                request_count=self._request_count,
                failure_count=self._failure_count,
                total_latency_ms=self._total_latency_ms,
            )
