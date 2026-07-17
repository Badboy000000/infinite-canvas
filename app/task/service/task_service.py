from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence
from uuid import UUID

from app.task.contracts import (
    CasFailure,
    RecoveryFilter,
    Task,
    TaskDraft,
    TaskEvent,
    TaskEventDraft,
)
from app.task.store import TaskEventStore, TaskStore

from .state_machine import TaskNotFound, TaskStateError, ensure_transition
from .unit_of_work import TaskUnitOfWork, TaskWritePorts, task_unit_of_work


_EVENT_FOR_STATUS: Mapping[str, str] = {
    "queued": "task.queued",
    "leased": "task.leased",
    "running": "task.started",
    "downloading": "task.downloading",
    "retrying": "task.retry_scheduled",
    "succeeded": "task.succeeded",
    "failed": "task.failed",
    "cancel_requested": "task.cancel_requested",
    "cancelled": "task.cancelled",
    "unknown_recoverable": "task.recovered",
}


class TaskService:
    def __init__(
        self,
        task_store: TaskStore,
        event_store: TaskEventStore,
        unit_of_work: Optional[TaskUnitOfWork] = None,
    ) -> None:
        self.task_store = task_store
        self.event_store = event_store
        self.unit_of_work = unit_of_work or task_unit_of_work(
            task_store=task_store, event_store=event_store
        )
        self._lock = threading.RLock()

    def submit(self, draft: TaskDraft) -> Task:
        with self._lock:
            if draft.status not in {"created", "queued"}:
                raise TaskStateError(
                    f"new tasks must start in created or queued, got {draft.status}"
                )
            if draft.max_attempts < 1:
                raise TaskStateError("max_attempts must be at least 1")
            with self.unit_of_work.transaction() as tx:
                task_store, event_store = _task_ports(tx)
                if draft.idempotency_key:
                    existing = task_store.get_by_idempotency_key(
                        draft.idempotency_key
                    )
                    if existing is not None:
                        return existing
                task = task_store.create(draft)
                if event_store.count_for_task(task.id) != 0:
                    return task
                _append(event_store, task.id, "task.created", {"status": task.status})
                if task.status == "queued":
                    _append(event_store, task.id, "task.queued", {})
                return task

    def query(self, task_id: UUID | str) -> Task:
        normalized = _task_id(task_id)
        task = self.task_store.get(normalized)
        if task is None:
            raise TaskNotFound(f"task not found: {normalized}")
        return task

    def transition(
        self,
        task_id: UUID | str,
        status: str,
        *,
        expected: Optional[str] = None,
        updates: Optional[Mapping[str, object]] = None,
        event_payload: Optional[Mapping[str, object]] = None,
    ) -> Task:
        with self._lock:
            with self.unit_of_work.transaction() as tx:
                return self._transition_in(
                    tx,
                    task_id,
                    status,
                    expected=expected,
                    updates=updates,
                    event_payload=event_payload,
                )

    def cancel(self, task_id: UUID | str) -> Task:
        with self._lock:
            with self.unit_of_work.transaction() as tx:
                task_store, _ = _task_ports(tx)
                current = _query(task_store, task_id)
                if current.status == "cancelled":
                    return current
                if current.status in {"succeeded", "failed", "expired"}:
                    raise TaskStateError(
                        f"cannot cancel terminal task in status {current.status}"
                    )
                if current.status != "cancel_requested":
                    current = self._transition_in(
                        tx,
                        current.id,
                        "cancel_requested",
                        updates={"cancel_requested": True},
                    )
                if current.lease_owner is None:
                    return self._transition_in(tx, current.id, "cancelled")
                return current

    def retry(self, task_id: UUID | str) -> Task:
        with self._lock:
            with self.unit_of_work.transaction() as tx:
                task_store, _ = _task_ports(tx)
                current = _query(task_store, task_id)
                if current.status not in {"failed", "timed_out", "cancelled"}:
                    raise TaskStateError(
                        f"task in status {current.status} cannot be retried"
                    )
                if current.attempt >= current.max_attempts:
                    raise TaskStateError("task attempts exhausted")
                # retry 是正式状态迁移，不得绕过状态机直改 status。
                ensure_transition(current.status, "retrying")
                return self._transition_in(
                    tx,
                    current.id,
                    "retrying",
                    updates={
                        "cancel_requested": False,
                        "retry_after": None,
                        "finished_at": None,
                        "error_code": None,
                        "error_message": None,
                        "error_category": None,
                    },
                    event_payload={"attempt": current.attempt + 1},
                )

    def recover(self, filters: Optional[RecoveryFilter] = None) -> list[Task]:
        active_filter = filters or RecoveryFilter(
            statuses=(
                "leased",
                "running",
                "waiting_upstream",
                "downloading",
                "retrying",
                "unknown_recoverable",
            ),
            lease_expired_before=datetime.now(timezone.utc),
        )
        recovered: list[Task] = []
        with self._lock:
            for candidate in self.task_store.scan(active_filter):
                with self.unit_of_work.transaction() as tx:
                    task_store, event_store = _task_ports(tx)
                    current = _query(task_store, candidate.id)
                    updates: dict[str, object] = {}
                    target = current.status
                    if current.status in {"leased", "running", "downloading"}:
                        target = "unknown_recoverable"
                        updates.update(
                            lease_owner=None,
                            lease_until=None,
                            heartbeat_at=current.heartbeat_at,
                        )
                    elif current.status == "retrying":
                        now = datetime.now(timezone.utc)
                        if current.retry_after is None or current.retry_after <= now:
                            target = "queued"
                            updates["queued_at"] = now
                    if target == current.status:
                        continue
                    ensure_transition(current.status, target)
                    updates["status"] = target
                    changed = task_store.update_with_expected(
                        current.id,
                        updates,
                        expected={
                            "status": current.status,
                            "lease_owner": current.lease_owner,
                        },
                    )
                    _append(
                        event_store,
                        changed.id,
                        "task.recovered",
                        {"from_status": current.status, "to_status": target},
                    )
                    recovered.append(changed)
        return recovered

    def lease(self, task_id: UUID | str, owner: str, *, ttl_sec: int) -> Task:
        with self._lock:
            with self.unit_of_work.transaction() as tx:
                task_store, event_store = _task_ports(tx)
                current = _query(task_store, task_id)
                ensure_transition(current.status, "leased")
                if current.attempt >= current.max_attempts:
                    raise TaskStateError("task attempts exhausted")
                try:
                    leased = task_store.acquire_lease(current.id, owner, ttl_sec)
                    leased = task_store.update_with_expected(
                        leased.id,
                        {"attempt": current.attempt + 1},
                        expected={
                            "status": "leased",
                            "lease_owner": owner,
                            "attempt": current.attempt,
                        },
                    )
                except CasFailure as exc:
                    raise TaskStateError(
                        f"lease acquisition failed: {exc.key}"
                    ) from exc
                _append(
                    event_store,
                    leased.id,
                    "task.leased",
                    {"lease_owner": owner, "attempt": leased.attempt},
                )
                return leased

    def heartbeat(
        self, task_id: UUID | str, owner: str, *, ttl_sec: int
    ) -> Task:
        try:
            return self.task_store.heartbeat(
                _task_id(task_id), owner, ttl_sec=ttl_sec
            )
        except CasFailure as exc:
            raise TaskStateError(
                f"heartbeat rejected for lease owner {owner}"
            ) from exc

    def report(self, task_id: UUID | str, event: TaskEvent) -> None:
        normalized = _task_id(task_id)
        if event.kind == "task.started":
            self.transition(normalized, "running", expected="leased")
            return
        self._append(normalized, event.kind, event.payload_json)

    def release(
        self,
        task_id: UUID | str,
        owner: str,
        *,
        status: str,
        output_refs: Sequence[object] = (),
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        error_category: Optional[str] = None,
    ) -> Task:
        with self._lock:
            with self.unit_of_work.transaction() as tx:
                task_store, event_store = _task_ports(tx)
                current = _query(task_store, task_id)
                target = (
                    "cancelled" if current.status == "cancel_requested" else status
                )
                ensure_transition(current.status, target)
                updates: dict[str, object] = {
                    "output_refs": tuple(output_refs),
                    "error_code": error_code,
                    "error_message": error_message,
                    "error_category": error_category,
                }
                task_store.update_with_expected(
                    current.id,
                    updates,
                    expected={
                        "status": current.status,
                        "lease_owner": owner,
                    },
                )
                try:
                    released = task_store.release_lease(
                        current.id, owner, new_status=target
                    )
                except CasFailure as exc:
                    raise TaskStateError(
                        f"release rejected for lease owner {owner}"
                    ) from exc
                event_kind = _EVENT_FOR_STATUS.get(target)
                if event_kind:
                    _append(
                        event_store,
                        released.id,
                        event_kind,
                        {"error_code": error_code} if error_code else {},
                    )
                return released

    def _transition_in(
        self,
        tx: TaskWritePorts,
        task_id: UUID | str,
        status: str,
        *,
        expected: Optional[str] = None,
        updates: Optional[Mapping[str, object]] = None,
        event_payload: Optional[Mapping[str, object]] = None,
    ) -> Task:
        task_store, event_store = _task_ports(tx)
        current = _query(task_store, task_id)
        if expected is not None and current.status != expected:
            raise TaskStateError(f"expected status {expected}, got {current.status}")
        ensure_transition(current.status, status)
        payload = dict(updates or {})
        payload["status"] = status
        now = datetime.now(timezone.utc)
        if status == "running" and current.started_at is None:
            payload["started_at"] = now
        if status in {"succeeded", "failed", "cancelled", "expired"}:
            payload["finished_at"] = now
        changed = task_store.update_with_expected(
            current.id, payload, expected={"status": current.status}
        )
        event_kind = _EVENT_FOR_STATUS.get(status)
        if event_kind:
            _append(event_store, changed.id, event_kind, event_payload or {})
        return changed

    def _append(
        self,
        task_id: UUID,
        kind: str,
        payload: Mapping[str, object],
    ) -> TaskEvent:
        return self.event_store.append(
            TaskEventDraft(task_id=task_id, kind=kind, payload_json=payload)
        )


def _task_id(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(value)


def _query(task_store: TaskStore, task_id: UUID | str) -> Task:
    normalized = _task_id(task_id)
    task = task_store.get(normalized)
    if task is None:
        raise TaskNotFound(f"task not found: {normalized}")
    return task


def _task_ports(tx: TaskWritePorts) -> tuple[TaskStore, TaskEventStore]:
    assert tx.task_store is not None and tx.event_store is not None
    return tx.task_store, tx.event_store


def _append(
    event_store: TaskEventStore,
    task_id: UUID,
    kind: str,
    payload: Mapping[str, object],
) -> TaskEvent:
    return event_store.append(
        TaskEventDraft(task_id=task_id, kind=kind, payload_json=payload)
    )


__all__ = ["TaskService"]
