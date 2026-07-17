"""`app.task.store.memory_impl` — 内存 Store 实现，供契约测试与 fake 场景使用。

实现原则：

- 每张表用 `dict[UUID, Task]` 存 Snapshot，事件用 `list[TaskEvent]`。
- 单进程内使用 `threading.Lock` 显式保护所有 mutate 路径。
- 与 SQLite 实现共享同一份端口签名与语义（`CasFailure` / lease / seq
  单调 / recovery filter）。

**本 PR 不做**：不引入 asyncio 锁；不做进程间共享；不持久化。
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional
from uuid import UUID

from app.task.contracts import (
    Artifact,
    ArtifactDraft,
    CasFailure,
    NodeRun,
    NodeRunDraft,
    ProviderTask,
    ProviderTaskDraft,
    RecoveryFilter,
    Task,
    TaskDraft,
    TaskEvent,
    TaskEventDraft,
)
from app.task.contracts.task import RECOVERABLE_TASK_STATUSES

# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> UUID:
    return uuid.uuid4()


def _draft_updates_task(current: Task, updates: Mapping[str, object]) -> Task:
    """把 `updates` 应用到 `current`，返回新 Task snapshot。

    `updated_at` 由本函数覆盖为 `_utcnow()`。禁止调用方直接改
    `id / created_at`。
    """
    forbidden = {"id", "created_at"}
    for key in updates.keys():
        if key in forbidden:
            raise ValueError(f"禁止通过 update 修改字段 {key!r}")
    payload = dict(updates)
    payload.setdefault("updated_at", _utcnow())
    return replace(current, **payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class MemoryTaskStore:
    """`TaskStore` 端口的内存实现。"""

    def __init__(self) -> None:
        self._data: Dict[UUID, Task] = {}
        self._by_idem: Dict[str, UUID] = {}
        self._lock = threading.RLock()

    # --- CRUD ---
    def create(self, draft: TaskDraft) -> Task:
        with self._lock:
            if (
                draft.idempotency_key
                and draft.idempotency_key in self._by_idem
            ):
                return self._data[self._by_idem[draft.idempotency_key]]
            now = _utcnow()
            task_id = draft.id or _new_id()
            task = Task(
                id=task_id,
                task_type=draft.task_type,
                status=draft.status,
                priority=draft.priority,
                idempotency_key=draft.idempotency_key,
                cancel_requested=False,
                owner_user_id=draft.owner_user_id,
                workspace_id=draft.workspace_id,
                project_id=draft.project_id,
                canvas_id=draft.canvas_id,
                node_id=draft.node_id,
                node_run_id=draft.node_run_id,
                provider_id=draft.provider_id,
                model=draft.model,
                workflow_id=draft.workflow_id,
                input_snapshot=dict(draft.input_snapshot),
                output_refs=list(draft.output_refs),
                attempt=0,
                max_attempts=draft.max_attempts,
                retry_after=None,
                lease_owner=None,
                lease_until=None,
                heartbeat_at=None,
                deadline_at=draft.deadline_at,
                timeout_policy=dict(draft.timeout_policy),
                error_code=None,
                error_message=None,
                error_category=None,
                cost_estimate=draft.cost_estimate,
                cost_actual=None,
                quota_bucket=draft.quota_bucket,
                created_at=now,
                queued_at=now if draft.status == "queued" else None,
                started_at=None,
                updated_at=now,
                finished_at=None,
                schema_version=draft.schema_version,
            )
            self._data[task_id] = task
            if draft.idempotency_key:
                self._by_idem[draft.idempotency_key] = task_id
            return task

    def get(self, task_id: UUID) -> Optional[Task]:
        with self._lock:
            return self._data.get(task_id)

    def get_by_idempotency_key(self, key: str) -> Optional[Task]:
        with self._lock:
            tid = self._by_idem.get(key)
            return self._data.get(tid) if tid else None

    def list_by_canvas_node(
        self, canvas_id: str, node_id: Optional[str] = None, *, limit: int = 100
    ) -> List[Task]:
        with self._lock:
            out: List[Task] = []
            for t in self._data.values():
                if t.canvas_id != canvas_id:
                    continue
                if node_id is not None and t.node_id != node_id:
                    continue
                out.append(t)
                if len(out) >= limit:
                    break
            return out

    # --- 条件更新（乐观锁）---
    def update_with_expected(
        self,
        task_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> Task:
        with self._lock:
            current = self._data.get(task_id)
            if current is None:
                raise CasFailure(
                    f"Task {task_id} 不存在", key="id", expected=task_id
                )
            for key, expected_value in expected.items():
                actual = getattr(current, key, None)
                if actual != expected_value:
                    raise CasFailure(
                        f"Task {task_id} 字段 {key!r} 期望 {expected_value!r}"
                        f" 实际 {actual!r}",
                        key=key,
                        expected=expected_value,
                        actual=actual,
                    )
            new_task = _draft_updates_task(current, updates)
            self._data[task_id] = new_task
            return new_task

    # --- 租约 / 心跳 / 释放 ---
    def acquire_lease(
        self, task_id: UUID, owner: str, ttl_sec: int
    ) -> Task:
        with self._lock:
            current = self._data.get(task_id)
            if current is None:
                raise CasFailure(f"Task {task_id} 不存在", key="id")
            now = _utcnow()
            # 抢占条件：当前无 lease，或 lease_until 已过期
            leaseable = (
                current.lease_owner is None
                or current.lease_until is None
                or current.lease_until <= now
            )
            if not leaseable:
                raise CasFailure(
                    f"Task {task_id} 已被 {current.lease_owner} 持有租约",
                    key="lease_owner",
                    actual=current.lease_owner,
                )
            new_task = replace(
                current,
                status="leased",
                lease_owner=owner,
                lease_until=now + timedelta(seconds=ttl_sec),
                heartbeat_at=now,
                updated_at=now,
            )
            self._data[task_id] = new_task
            return new_task

    def heartbeat(self, task_id: UUID, owner: str, *, ttl_sec: int) -> Task:
        with self._lock:
            current = self._data.get(task_id)
            if current is None:
                raise CasFailure(f"Task {task_id} 不存在", key="id")
            if current.lease_owner != owner:
                raise CasFailure(
                    f"Task {task_id} 租约不属于 {owner}",
                    key="lease_owner",
                    expected=owner,
                    actual=current.lease_owner,
                )
            now = _utcnow()
            new_task = replace(
                current,
                heartbeat_at=now,
                lease_until=now + timedelta(seconds=ttl_sec),
                updated_at=now,
            )
            self._data[task_id] = new_task
            return new_task

    def release_lease(
        self,
        task_id: UUID,
        owner: str,
        *,
        new_status: Optional[str] = None,
    ) -> Task:
        with self._lock:
            current = self._data.get(task_id)
            if current is None:
                raise CasFailure(f"Task {task_id} 不存在", key="id")
            if current.lease_owner != owner:
                raise CasFailure(
                    f"Task {task_id} 租约不属于 {owner}",
                    key="lease_owner",
                    expected=owner,
                    actual=current.lease_owner,
                )
            now = _utcnow()
            payload = {
                "lease_owner": None,
                "lease_until": None,
                "updated_at": now,
            }
            if new_status is not None:
                payload["status"] = new_status
                if new_status in {"succeeded", "failed", "cancelled", "expired"}:
                    payload["finished_at"] = now
            new_task = replace(current, **payload)  # type: ignore[arg-type]
            self._data[task_id] = new_task
            return new_task

    # --- 恢复扫描 ---
    def scan(self, filter: RecoveryFilter) -> List[Task]:
        statuses = frozenset(filter.statuses or RECOVERABLE_TASK_STATUSES)
        with self._lock:
            candidates: List[Task] = []
            for t in self._data.values():
                if t.status not in statuses:
                    continue
                if filter.lease_expired_before is not None:
                    if (
                        t.lease_until is not None
                        and t.lease_until >= filter.lease_expired_before
                    ):
                        continue
                if (
                    filter.workspace_id is not None
                    and t.workspace_id != filter.workspace_id
                ):
                    continue
                if (
                    filter.project_id is not None
                    and t.project_id != filter.project_id
                ):
                    continue
                if (
                    filter.owner_user_id is not None
                    and t.owner_user_id != filter.owner_user_id
                ):
                    continue
                candidates.append(t)
            # 稳定排序：按 created_at 升序
            candidates.sort(key=lambda t: t.created_at)
            start = filter.offset
            end = start + filter.limit
            return candidates[start:end]


# ---------------------------------------------------------------------------
# NodeRun
# ---------------------------------------------------------------------------


class MemoryNodeRunStore:
    def __init__(self) -> None:
        self._data: Dict[UUID, NodeRun] = {}
        self._lock = threading.RLock()

    def create(self, draft: NodeRunDraft) -> NodeRun:
        with self._lock:
            now = _utcnow()
            run_id = draft.id or _new_id()
            run = NodeRun(
                id=run_id,
                canvas_id=draft.canvas_id,
                node_id=draft.node_id,
                node_type=draft.node_type,
                source_node_id=draft.source_node_id,
                run_kind=draft.run_kind,
                status=draft.status,
                trigger_source=draft.trigger_source,
                input_snapshot=dict(draft.input_snapshot),
                settings_snapshot=dict(draft.settings_snapshot),
                dependency_snapshot=dict(draft.dependency_snapshot),
                task_ids=list(draft.task_ids),
                output_refs=list(draft.output_refs),
                parent_run_id=draft.parent_run_id,
                batch_key=draft.batch_key,
                attempt=draft.attempt,
                started_at=None,
                finished_at=None,
                elapsed_ms=None,
                summary=None,
                error=None,
                workspace_id=draft.workspace_id,
                project_id=draft.project_id,
                owner_user_id=draft.owner_user_id,
                created_at=now,
                updated_at=now,
                schema_version=draft.schema_version,
            )
            self._data[run_id] = run
            return run

    def get(self, node_run_id: UUID) -> Optional[NodeRun]:
        with self._lock:
            return self._data.get(node_run_id)

    def list_by_canvas(
        self, canvas_id: str, *, limit: int = 100
    ) -> List[NodeRun]:
        with self._lock:
            out = [r for r in self._data.values() if r.canvas_id == canvas_id]
            out.sort(key=lambda r: r.created_at)
            return out[:limit]

    def update_with_expected(
        self,
        node_run_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> NodeRun:
        with self._lock:
            current = self._data.get(node_run_id)
            if current is None:
                raise CasFailure(f"NodeRun {node_run_id} 不存在", key="id")
            for key, expected_value in expected.items():
                actual = getattr(current, key, None)
                if actual != expected_value:
                    raise CasFailure(
                        f"NodeRun 字段 {key!r} 期望 {expected_value!r} 实际 {actual!r}",
                        key=key,
                        expected=expected_value,
                        actual=actual,
                    )
            payload = dict(updates)
            payload.setdefault("updated_at", _utcnow())
            new_run = replace(current, **payload)  # type: ignore[arg-type]
            self._data[node_run_id] = new_run
            return new_run


# ---------------------------------------------------------------------------
# ProviderTask
# ---------------------------------------------------------------------------


class MemoryProviderTaskStore:
    def __init__(self) -> None:
        self._data: Dict[UUID, ProviderTask] = {}
        self._lock = threading.RLock()

    def create(self, draft: ProviderTaskDraft) -> ProviderTask:
        with self._lock:
            now = _utcnow()
            pt_id = draft.id or _new_id()
            pt = ProviderTask(
                id=pt_id,
                task_id=draft.task_id,
                provider_id=draft.provider_id,
                provider_protocol=draft.provider_protocol,
                capability=draft.capability,
                operation=draft.operation,
                upstream_task_id=draft.upstream_task_id,
                upstream_task_kind=draft.upstream_task_kind,
                remote_status=draft.remote_status,
                status=draft.status,
                progress=None,
                poll_after=None,
                poll_count=0,
                last_poll_at=None,
                outputs=dict(draft.outputs),
                error=None,
                raw_excerpt=None,
                query_params=dict(draft.query_params),
                adapter_kind=draft.adapter_kind,
                created_at=now,
                submitted_at=None,
                updated_at=now,
                completed_at=None,
                schema_version=draft.schema_version,
            )
            self._data[pt_id] = pt
            return pt

    def get(self, provider_task_id: UUID) -> Optional[ProviderTask]:
        with self._lock:
            return self._data.get(provider_task_id)

    def find_by_upstream(
        self, provider_id: str, upstream_task_id: str
    ) -> Optional[ProviderTask]:
        with self._lock:
            for pt in self._data.values():
                if (
                    pt.provider_id == provider_id
                    and pt.upstream_task_id == upstream_task_id
                ):
                    return pt
            return None

    def list_by_task(self, task_id: UUID) -> List[ProviderTask]:
        with self._lock:
            out = [pt for pt in self._data.values() if pt.task_id == task_id]
            out.sort(key=lambda pt: pt.created_at)
            return out

    def update_with_expected(
        self,
        provider_task_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> ProviderTask:
        with self._lock:
            current = self._data.get(provider_task_id)
            if current is None:
                raise CasFailure(
                    f"ProviderTask {provider_task_id} 不存在", key="id"
                )
            for key, expected_value in expected.items():
                actual = getattr(current, key, None)
                if actual != expected_value:
                    raise CasFailure(
                        f"ProviderTask 字段 {key!r} 期望 {expected_value!r}"
                        f" 实际 {actual!r}",
                        key=key,
                        expected=expected_value,
                        actual=actual,
                    )
            payload = dict(updates)
            payload.setdefault("updated_at", _utcnow())
            new_pt = replace(current, **payload)  # type: ignore[arg-type]
            self._data[provider_task_id] = new_pt
            return new_pt


# ---------------------------------------------------------------------------
# TaskEvent —— append-only, per-task 单调 seq
# ---------------------------------------------------------------------------


class MemoryTaskEventStore:
    def __init__(self) -> None:
        self._events: List[TaskEvent] = []
        self._per_task_seq: Dict[UUID, int] = {}
        self._lock = threading.RLock()

    def append(self, draft: TaskEventDraft) -> TaskEvent:
        with self._lock:
            next_seq = self._per_task_seq.get(draft.task_id, 0) + 1
            self._per_task_seq[draft.task_id] = next_seq
            event_id = len(self._events) + 1  # 全局自增
            ts = draft.ts or _utcnow()
            event = TaskEvent(
                id=event_id,
                task_id=draft.task_id,
                seq=next_seq,
                kind=draft.kind,
                ts=ts,
                payload_json=dict(draft.payload_json),
                schema_version=draft.schema_version,
            )
            self._events.append(event)
            return event

    def list_for_task(
        self,
        task_id: UUID,
        *,
        since_seq: Optional[int] = None,
        limit: int = 500,
    ) -> List[TaskEvent]:
        with self._lock:
            out = [e for e in self._events if e.task_id == task_id]
            if since_seq is not None:
                out = [e for e in out if e.seq > since_seq]
            out.sort(key=lambda e: e.seq)
            return out[:limit]

    def count_for_task(self, task_id: UUID) -> int:
        with self._lock:
            return self._per_task_seq.get(task_id, 0)


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class MemoryArtifactStore:
    def __init__(self) -> None:
        self._data: Dict[UUID, Artifact] = {}
        self._lock = threading.RLock()

    def create(self, draft: ArtifactDraft) -> Artifact:
        with self._lock:
            now = _utcnow()
            aid = draft.id or _new_id()
            art = Artifact(
                id=aid,
                task_id=draft.task_id,
                node_run_id=draft.node_run_id,
                provider_task_id=draft.provider_task_id,
                kind=draft.kind,
                url=draft.url,
                file_object_id=draft.file_object_id,
                legacy_url=draft.legacy_url,
                mime_type=draft.mime_type,
                name=draft.name,
                width=draft.width,
                height=draft.height,
                duration=draft.duration,
                size=draft.size,
                sha256=draft.sha256,
                node_id=draft.node_id,
                output_key=draft.output_key,
                role=draft.role,
                workspace_id=draft.workspace_id,
                project_id=draft.project_id,
                owner_user_id=draft.owner_user_id,
                created_at=now,
                schema_version=draft.schema_version,
            )
            self._data[aid] = art
            return art

    def get(self, artifact_id: UUID) -> Optional[Artifact]:
        with self._lock:
            return self._data.get(artifact_id)

    def list_by_task(self, task_id: UUID) -> List[Artifact]:
        with self._lock:
            out = [a for a in self._data.values() if a.task_id == task_id]
            out.sort(key=lambda a: a.created_at)
            return out

    def list_by_node_run(self, node_run_id: UUID) -> List[Artifact]:
        with self._lock:
            out = [
                a for a in self._data.values() if a.node_run_id == node_run_id
            ]
            out.sort(key=lambda a: a.created_at)
            return out


# ---------------------------------------------------------------------------
# 便捷工厂
# ---------------------------------------------------------------------------


def memory_stores() -> "tuple":
    """一次返回五件套内存 Store。"""
    return (
        MemoryTaskStore(),
        MemoryNodeRunStore(),
        MemoryProviderTaskStore(),
        MemoryTaskEventStore(),
        MemoryArtifactStore(),
    )


__all__ = [
    "MemoryTaskStore",
    "MemoryNodeRunStore",
    "MemoryProviderTaskStore",
    "MemoryTaskEventStore",
    "MemoryArtifactStore",
    "memory_stores",
]
