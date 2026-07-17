"""Task 聚合的组合事务边界。

既有五个 Store Protocol 继续保持独立、向后兼容；服务层通过
``TaskUnitOfWork`` 把状态、结果与 TaskEvent 纳入同一原子边界。
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional, Protocol

from app.db.session import get_session
from app.task.store import (
    ArtifactStore,
    NodeRunStore,
    ProviderTaskStore,
    TaskEventStore,
    TaskStore,
)
from app.task.store.memory_impl import (
    MemoryArtifactStore,
    MemoryNodeRunStore,
    MemoryProviderTaskStore,
    MemoryTaskEventStore,
    MemoryTaskStore,
)
from app.task.store.sqlite_impl import (
    SqliteArtifactStore,
    SqliteNodeRunStore,
    SqliteProviderTaskStore,
    SqliteTaskEventStore,
    SqliteTaskStore,
)


@dataclass(frozen=True)
class TaskWritePorts:
    task_store: Optional[TaskStore] = None
    node_run_store: Optional[NodeRunStore] = None
    provider_task_store: Optional[ProviderTaskStore] = None
    event_store: Optional[TaskEventStore] = None
    artifact_store: Optional[ArtifactStore] = None


class TaskUnitOfWork(Protocol):
    def transaction(self): ...


class MemoryTaskUnitOfWork:
    """锁住同一组 Memory Store，失败时恢复进入前快照。"""

    def __init__(self, ports: TaskWritePorts) -> None:
        self._ports = ports

    @contextmanager
    def transaction(self) -> Iterator[TaskWritePorts]:
        stores = [
            store
            for store in (
                self._ports.task_store,
                self._ports.node_run_store,
                self._ports.provider_task_store,
                self._ports.event_store,
                self._ports.artifact_store,
            )
            if store is not None
        ]
        with ExitStack() as stack:
            for store in stores:
                stack.enter_context(store._lock)  # type: ignore[attr-defined]
            snapshots = _memory_snapshots(stores)
            try:
                yield self._ports
            except Exception:
                _restore_memory_snapshots(snapshots)
                raise


class SqliteTaskUnitOfWork:
    """为所有 SQLite Store 代理绑定同一 Session/事务。"""

    @contextmanager
    def transaction(self) -> Iterator[TaskWritePorts]:
        with get_session() as session:
            yield TaskWritePorts(
                task_store=SqliteTaskStore(session),
                node_run_store=SqliteNodeRunStore(session),
                provider_task_store=SqliteProviderTaskStore(session),
                event_store=SqliteTaskEventStore(session),
                artifact_store=SqliteArtifactStore(session),
            )


def task_unit_of_work(
    *,
    task_store: Optional[TaskStore] = None,
    node_run_store: Optional[NodeRunStore] = None,
    provider_task_store: Optional[ProviderTaskStore] = None,
    event_store: Optional[TaskEventStore] = None,
    artifact_store: Optional[ArtifactStore] = None,
) -> TaskUnitOfWork:
    """从现有 Store 组合推导 UoW，不改变任何 Store contract。"""

    supplied = [
        store
        for store in (
            task_store,
            node_run_store,
            provider_task_store,
            event_store,
            artifact_store,
        )
        if store is not None
    ]
    memory_types = (
        MemoryTaskStore,
        MemoryNodeRunStore,
        MemoryProviderTaskStore,
        MemoryTaskEventStore,
        MemoryArtifactStore,
    )
    sqlite_types = (
        SqliteTaskStore,
        SqliteNodeRunStore,
        SqliteProviderTaskStore,
        SqliteTaskEventStore,
        SqliteArtifactStore,
    )
    if supplied and all(isinstance(store, memory_types) for store in supplied):
        return MemoryTaskUnitOfWork(
            TaskWritePorts(
                task_store=task_store,
                node_run_store=node_run_store,
                provider_task_store=provider_task_store,
                event_store=event_store,
                artifact_store=artifact_store,
            )
        )
    if supplied and all(isinstance(store, sqlite_types) for store in supplied):
        return SqliteTaskUnitOfWork()
    raise TypeError(
        "multi-store writes require an explicit TaskUnitOfWork for custom stores"
    )


def _memory_snapshots(stores):
    snapshots = []
    for store in stores:
        state = {}
        for name in ("_data", "_by_idem", "_events", "_per_task_seq"):
            if hasattr(store, name):
                value = getattr(store, name)
                state[name] = value.copy() if hasattr(value, "copy") else list(value)
        snapshots.append((store, state))
    return snapshots


def _restore_memory_snapshots(snapshots) -> None:
    for store, state in snapshots:
        for name, value in state.items():
            setattr(store, name, value)


__all__ = [
    "MemoryTaskUnitOfWork",
    "SqliteTaskUnitOfWork",
    "TaskUnitOfWork",
    "TaskWritePorts",
    "task_unit_of_work",
]
