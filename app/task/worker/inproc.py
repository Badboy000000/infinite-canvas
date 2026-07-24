from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from app.task.contracts import RecoveryFilter, Task, TaskDraft, TaskEvent
from app.task.service import (
    CancelResult,
    CancelScope,
    TaskLease,
    TaskOutcome,
    TaskService,
    TaskStateError,
)


TaskHandler = Callable[[Task], Awaitable[TaskOutcome]]


class InProcessDispatcher:
    def __init__(
        self,
        service: TaskService,
        *,
        wake_event: Optional[asyncio.Event] = None,
    ) -> None:
        self.service = service
        self.wake_event = wake_event or asyncio.Event()

    async def submit(self, task: TaskDraft) -> Task:
        submitted = self.service.submit(task)
        self.wake_event.set()
        return submitted

    async def cancel(
        self, task_id: str, scope: CancelScope
    ) -> CancelResult:
        # PR-8 · 三层取消语义传递:local / upstream / attention 均先在本地
        # 调用 TaskService.cancel(内部走状态机)· accepted=True 表示本地已
        # 记录 cancel_requested;upstream 是否真取消由 Provider adapter 承接
        # (cancel_scope 声明能力 · 见 Provider 专题)。
        task = self.service.cancel(task_id)
        return CancelResult(task=task, scope=scope, accepted=True)

    async def retry(self, task_id: str) -> Task:
        task = self.service.retry(task_id)
        self.wake_event.set()
        return task

    async def recover(self, filters: RecoveryFilter) -> list[Task]:
        tasks = self.service.recover(filters)
        if any(task.status in {"queued", "retrying"} for task in tasks):
            self.wake_event.set()
        return tasks


class InProcessExecutor:
    def __init__(
        self,
        service: TaskService,
        *,
        heartbeat_ttl_sec: int = 30,
    ) -> None:
        self.service = service
        self.heartbeat_ttl_sec = heartbeat_ttl_sec
        self._owners: dict[str, str] = {}

    async def lease(
        self, pool: str, worker_id: str, ttl_sec: int
    ) -> Optional[TaskLease]:
        now = datetime.now(timezone.utc)
        candidates = self.service.task_store.scan(
            RecoveryFilter(statuses=("queued", "retrying"), limit=100)
        )
        candidates.sort(key=lambda task: (-task.priority, task.created_at))
        for candidate in candidates:
            if pool != "*" and candidate.task_type != pool:
                continue
            if candidate.retry_after is not None and candidate.retry_after > now:
                continue
            try:
                leased = self.service.lease(
                    candidate.id, worker_id, ttl_sec=ttl_sec
                )
            except TaskStateError:
                continue
            self._owners[str(leased.id)] = worker_id
            return TaskLease(task=leased, pool=pool, worker_id=worker_id)
        return None

    async def report(self, task_id: str, event: TaskEvent) -> None:
        self.service.report(task_id, event)

    async def heartbeat(self, task_id: str, lease_owner: str) -> bool:
        try:
            self.service.heartbeat(
                task_id,
                lease_owner,
                ttl_sec=self.heartbeat_ttl_sec,
            )
        except TaskStateError:
            return False
        return True

    async def release(self, task_id: str, outcome: TaskOutcome) -> None:
        owner = self._owners.get(task_id)
        if owner is None:
            raise TaskStateError(f"no local lease owner for task {task_id}")
        try:
            self.service.release(
                task_id,
                owner,
                status=outcome.status,
                output_refs=outcome.output_refs,
                error_code=outcome.error_code,
                error_message=outcome.error_message,
                error_category=outcome.error_category,
            )
        finally:
            self._owners.pop(task_id, None)


class InProcessWorker:
    def __init__(
        self,
        executor: InProcessExecutor,
        *,
        pool: str,
        worker_id: str,
        handler: TaskHandler,
        lease_ttl_sec: int = 30,
        heartbeat_interval_sec: float = 15.0,
        poll_interval_sec: float = 1.0,
        wake_event: Optional[asyncio.Event] = None,
    ) -> None:
        self.executor = executor
        self.pool = pool
        self.worker_id = worker_id
        self.handler = handler
        self.lease_ttl_sec = lease_ttl_sec
        self.heartbeat_interval_sec = heartbeat_interval_sec
        self.poll_interval_sec = poll_interval_sec
        self.wake_event = wake_event or asyncio.Event()
        self._runner: Optional[asyncio.Task[None]] = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._runner is not None and not self._runner.done()

    def start(self) -> None:
        if self.running:
            return
        self._stopping = False
        self._runner = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stopping = True
        self.wake_event.set()
        if self._runner is not None:
            await self._runner
            self._runner = None

    async def run_once(self) -> bool:
        lease = await self.executor.lease(
            self.pool, self.worker_id, self.lease_ttl_sec
        )
        if lease is None:
            return False
        task_id = str(lease.task.id)
        await self.executor.report(
            task_id,
            _event(lease.task, "task.started", {"worker_id": self.worker_id}),
        )
        heartbeat = asyncio.create_task(self._heartbeat(task_id))
        cancelled = False
        try:
            outcome = await self.handler(lease.task)
        except asyncio.CancelledError:
            cancelled = True
            outcome = TaskOutcome(
                status="cancelled",
                error_code="worker_cancelled",
                error_category="cancelled",
            )
        except Exception as exc:
            outcome = TaskOutcome(
                status="failed",
                error_code="worker_error",
                error_message=str(exc),
                error_category="internal",
            )
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
        await self.executor.release(task_id, outcome)
        if cancelled:
            raise asyncio.CancelledError
        return True

    async def _run_loop(self) -> None:
        while not self._stopping:
            worked = await self.run_once()
            if worked:
                continue
            self.wake_event.clear()
            try:
                await asyncio.wait_for(
                    self.wake_event.wait(), timeout=self.poll_interval_sec
                )
            except asyncio.TimeoutError:
                pass

    async def _heartbeat(self, task_id: str) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval_sec)
            if not await self.executor.heartbeat(task_id, self.worker_id):
                return


def _event(task: Task, kind: str, payload: dict[str, object]) -> TaskEvent:
    return TaskEvent(
        id=0,
        task_id=task.id,
        seq=0,
        kind=kind,
        ts=datetime.now(timezone.utc),
        payload_json=payload,
    )


__all__ = [
    "InProcessDispatcher",
    "InProcessExecutor",
    "InProcessWorker",
    "TaskHandler",
]
