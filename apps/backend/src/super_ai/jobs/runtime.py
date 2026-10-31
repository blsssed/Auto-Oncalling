"""持久后台任务运行时：SQLite 租约 + 心跳续租 + 协作式取消。

阅读顺序：_worker_loop → _execute → _heartbeat → raise_if_cancelled。
_execute 只有四条出路：成功、取消、失败重试、超时（也走失败重试）。
第一次读请跳过：注册与启停、租约 SQL 细节（在 memory/extended_sqlite.py）。

不变量：
- 长任务只能走这里，不能在请求里裸 asyncio.create_task；
- 任务结束必须停心跳，否则已结束的任务会一直续租；
- 取消是协作式的，handler 必须在安全点调用 raise_if_cancelled；
- 失败按 min(30, 2**attempt) 退避，错误文本脱敏并截断。

【学习路线 · 监控链路 第 1 站「任务启动」】
上一站：api/app.py 的 create_aiops_diagnostic（enqueue）→ 本站：
BackgroundJobRuntime（_worker_loop → _execute → raise_if_cancelled）→
下一站：aiops/diagnostics.py 的 AiopsDiagnosticService.stream。
学习重点：_execute 的四条出路（成功/取消/失败重试/超时）分别把任务
置成什么状态；取消为什么必须是协作式的，安全点在哪里。
自检：失败、超时、取消各自走哪条分支？答不出再回读 _execute。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TypeAlias
from uuid import uuid4

from super_ai.memory.repositories import (
    BackgroundJobRecord,
    BackgroundJobRepository,
    JsonDict,
)
from super_ai.observability import emit_event

logger = logging.getLogger(__name__)
JobHandler: TypeAlias = Callable[["BackgroundJobContext"], Awaitable[None]]


class JobCancelled(RuntimeError):
    """handler 在安全检查点发现取消请求时抛出的控制流异常。

    runtime 捕获后会写 cancelled 终态，不再重试。
    """


@dataclass(frozen=True, slots=True)
class BackgroundJobContext:
    """传给 handler 的最小上下文：任务记录 + 持久化仓库。

    handler 只能通过它追加事件和检查取消，不直接操作数据库会话。
    """

    job: BackgroundJobRecord
    repository: BackgroundJobRepository

    async def append_event(self, payload: JsonDict) -> None:
        """持久化一条任务事件；这是 SSE 断线回放的数据来源。"""
        await self.repository.append_event(
            owner_user_id=self.job.owner_user_id,
            job_id=self.job.id,
            payload=payload,
        )

    async def raise_if_cancelled(self) -> None:
        """重新读取任务状态；任务消失或已请求取消都视为取消。

        必须重新读库而不是信任启动时的快照，因为取消请求来自另一个请求。
        """
        current = await self.repository.get(
            owner_user_id=self.job.owner_user_id,
            job_id=self.job.id,
        )
        if current is None or current.cancel_requested_at is not None:
            raise JobCancelled("Background job cancellation was requested.")


class BackgroundJobRuntime:
    """用可续租 SQLite 租约驱动一组固定并发 worker。

    单进程内运行；多进程部署时依赖数据库原子 claim 避免重复执行。
    """

    def __init__(
        self,
        repository: BackgroundJobRepository,
        *,
        concurrency: int = 2,
        lease_seconds: int = 30,
        poll_seconds: float = 0.2,
    ) -> None:
        self._repository = repository
        self._concurrency = max(1, concurrency)
        self._lease_seconds = max(6, lease_seconds)
        self._poll_seconds = max(0.05, poll_seconds)
        self._handlers: dict[str, JobHandler] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._stopping = asyncio.Event()
        self._runtime_id = f"runtime_{uuid4().hex}"

    def register(self, kind: str, handler: JobHandler) -> None:
        """注册 job kind 的 handler；同一 kind 重复注册视为编程错误。"""
        if kind in self._handlers:
            raise ValueError(f"Background job handler already registered: {kind}")
        self._handlers[kind] = handler

    async def start(self) -> None:
        """启动固定数量的 worker；重复调用保持幂等。"""
        if self._workers:
            return
        self._stopping.clear()
        self._workers = [
            asyncio.create_task(self._worker_loop(index), name=f"background-worker-{index}")
            for index in range(self._concurrency)
        ]

    async def stop(self) -> None:
        """通知所有 worker 停止，取消并等待它们退出。"""
        self._stopping.set()
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def _worker_loop(self, index: int) -> None:
        """单个 worker 的主循环：claim 一个任务，执行完再 claim 下一个。

        worker_id 由 runtime 前缀 + 序号组成，claim 时写入租约，
        后续续租/完成都必须匹配同一个 worker_id。
        """
        worker_id = f"{self._runtime_id}:{index}"
        while not self._stopping.is_set():
            now = _utc_now()
            job = await self._repository.claim_next(
                worker_id=worker_id,
                lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                now=now,
            )
            if job is None:
                await asyncio.sleep(self._poll_seconds)
                continue
            await self._execute(job, worker_id)

    async def _execute(self, job: BackgroundJobRecord, worker_id: str) -> None:
        """执行一次任务，并把结果落到成功/取消/失败三种终态之一。

        心跳与 handler 并行运行；无论走哪个分支，finally 都会停掉心跳，
        避免任务结束后还继续续租。
        """
        handler = self._handlers.get(job.kind)
        if handler is None:
            # 未知 kind 不直接丢弃：走统一失败路径，保留可观测性和重试语义。
            await self._repository.handle_failure(
                job_id=job.id,
                worker_id=worker_id,
                error_message=f"No handler is registered for job kind: {job.kind}",
                retry_at=_utc_now(),
            )
            return

        emit_event(logger, "background.job.started", jobId=job.id, kind=job.kind)
        context = BackgroundJobContext(job=job, repository=self._repository)
        heartbeat = asyncio.create_task(self._heartbeat(job.id, worker_id))
        try:
            # 执行前检查一次，避免启动一个已经被用户取消的任务。
            await context.raise_if_cancelled()
            await asyncio.wait_for(handler(context), timeout=job.timeout_seconds)
            # 执行后再检查一次，覆盖 handler 内部未主动轮询取消的情况。
            await context.raise_if_cancelled()
        except JobCancelled:
            await self._repository.mark_cancelled(job_id=job.id, worker_id=worker_id)
            emit_event(logger, "background.job.cancelled", jobId=job.id, kind=job.kind)
        except Exception as exc:
            # 指数退避但封顶 30 秒，防止故障源把重试间隔拉得不可控。
            retry_at = _utc_now() + timedelta(seconds=min(30, 2**job.attempt))
            updated = await self._repository.handle_failure(
                job_id=job.id,
                worker_id=worker_id,
                error_message=_safe_error(exc),
                retry_at=retry_at,
            )
            emit_event(
                logger,
                "background.job.failed",
                jobId=job.id,
                kind=job.kind,
                final=updated is not None and updated.status == "failed",
                errorCategory=exc.__class__.__name__,
            )
        else:
            await self._repository.mark_succeeded(job_id=job.id, worker_id=worker_id)
            emit_event(logger, "background.job.completed", jobId=job.id, kind=job.kind)
        finally:
            # 任务已结束，必须停心跳；否则这个任务会一直被续租，其他 worker 无法接管。
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, job_id: str, worker_id: str) -> None:
        """按租约时长的 1/3 周期续租；续租失败说明租约已被接管，立即退出。"""
        interval = self._lease_seconds / 3
        while not self._stopping.is_set():
            await asyncio.sleep(interval)
            renewed = await self._repository.renew_lease(
                job_id=job_id,
                worker_id=worker_id,
                lease_expires_at=_utc_now() + timedelta(seconds=self._lease_seconds),
            )
            if not renewed:
                return


def _safe_error(error: Exception) -> str:
    """把异常转成可持久化的短文本：超时归一化，其它截断到 1000 字符。"""
    if isinstance(error, asyncio.TimeoutError):
        return "Background job timed out."
    text = str(error).strip()
    return (text or error.__class__.__name__)[:1000]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
