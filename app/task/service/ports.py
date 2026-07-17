from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Optional, Protocol, Sequence, runtime_checkable

from app.task.contracts import RecoveryFilter, Task, TaskDraft, TaskEvent


CancelScope = Literal["local", "upstream", "attention"]


@dataclass(frozen=True)
class TaskLease:
    task: Task
    pool: str
    worker_id: str


@dataclass(frozen=True)
class TaskOutcome:
    status: str
    output_refs: Sequence[object] = field(default_factory=tuple)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    error_category: Optional[str] = None


@dataclass(frozen=True)
class CancelResult:
    task: Task
    scope: CancelScope
    accepted: bool


@runtime_checkable
class TaskExecutor(Protocol):
    async def lease(
        self, pool: str, worker_id: str, ttl_sec: int
    ) -> Optional[TaskLease]: ...

    async def report(self, task_id: str, event: TaskEvent) -> None: ...

    async def heartbeat(self, task_id: str, lease_owner: str) -> bool: ...

    async def release(self, task_id: str, outcome: TaskOutcome) -> None: ...


@runtime_checkable
class TaskDispatcher(Protocol):
    async def submit(self, task: TaskDraft) -> Task: ...

    async def cancel(
        self, task_id: str, scope: CancelScope
    ) -> CancelResult: ...

    async def retry(self, task_id: str) -> Task: ...

    async def recover(self, filters: RecoveryFilter) -> list[Task]: ...


__all__ = [
    "CancelResult",
    "CancelScope",
    "TaskDispatcher",
    "TaskExecutor",
    "TaskLease",
    "TaskOutcome",
]
