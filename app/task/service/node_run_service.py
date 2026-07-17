from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Optional, Sequence
from uuid import UUID

from app.task.contracts import NodeRun, NodeRunDraft, TaskEventDraft
from app.task.store import NodeRunStore, TaskEventStore, TaskStore

from .state_machine import TaskNotFound, TaskStateError
from .unit_of_work import TaskUnitOfWork, task_unit_of_work


class NodeRunNotFound(TaskStateError):
    pass


class NodeRunService:
    """NodeRun 创建、Task 关联与终态结果的一致性边界。"""

    def __init__(
        self,
        task_store: TaskStore,
        node_run_store: NodeRunStore,
        event_store: TaskEventStore,
        unit_of_work: Optional[TaskUnitOfWork] = None,
    ) -> None:
        self.task_store = task_store
        self.node_run_store = node_run_store
        self.event_store = event_store
        self.unit_of_work = unit_of_work or task_unit_of_work(
            task_store=task_store,
            node_run_store=node_run_store,
            event_store=event_store,
        )

    def create(self, draft: NodeRunDraft) -> NodeRun:
        if draft.status != "created":
            raise TaskStateError("new node runs must start in created")
        with self.unit_of_work.transaction() as tx:
            assert tx.node_run_store
            return tx.node_run_store.create(draft)

    def query(self, node_run_id: UUID | str) -> NodeRun:
        normalized = node_run_id if isinstance(node_run_id, UUID) else UUID(node_run_id)
        node_run = self.node_run_store.get(normalized)
        if node_run is None:
            raise NodeRunNotFound(f"node run not found: {normalized}")
        return node_run

    def attach(
        self, node_run_id: UUID | str, task_ids: Sequence[UUID]
    ) -> NodeRun:
        normalized = node_run_id if isinstance(node_run_id, UUID) else UUID(node_run_id)
        with self.unit_of_work.transaction() as tx:
            assert tx.task_store and tx.node_run_store and tx.event_store
            current = tx.node_run_store.get(normalized)
            if current is None:
                raise NodeRunNotFound(f"node run not found: {normalized}")
            merged = list(dict.fromkeys((*current.task_ids, *task_ids)))
            for task_id in task_ids:
                if tx.task_store.get(task_id) is None:
                    raise TaskNotFound(f"task not found: {task_id}")
            updates: dict[str, object] = {"task_ids": merged}
            if current.status == "created":
                updates.update(status="running", started_at=datetime.now(timezone.utc))
            changed = tx.node_run_store.update_with_expected(
                current.id, updates, expected={"status": current.status}
            )
            for task_id in task_ids:
                tx.event_store.append(
                    TaskEventDraft(
                        task_id=task_id,
                        kind="node_run.attached",
                        payload_json={"node_run_id": str(current.id)},
                    )
                )
            return changed

    def finalize(
        self,
        node_run_id: UUID | str,
        *,
        status: str,
        output_refs: Sequence[object] = (),
        summary: Optional[str] = None,
        error: Optional[Mapping[str, object]] = None,
    ) -> NodeRun:
        if status not in {"succeeded", "failed", "cancelled"}:
            raise TaskStateError(f"invalid terminal node run status: {status}")
        normalized = node_run_id if isinstance(node_run_id, UUID) else UUID(node_run_id)
        with self.unit_of_work.transaction() as tx:
            assert tx.node_run_store and tx.event_store
            current = tx.node_run_store.get(normalized)
            if current is None:
                raise NodeRunNotFound(f"node run not found: {normalized}")
            if current.status not in {"created", "running"}:
                raise TaskStateError(
                    f"node run in status {current.status} cannot be finalized"
                )
            finished_at = datetime.now(timezone.utc)
            started_at = current.started_at or current.created_at
            elapsed_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
            changed = tx.node_run_store.update_with_expected(
                current.id,
                {
                    "status": status,
                    "output_refs": tuple(output_refs),
                    "summary": summary,
                    "error": dict(error) if error else None,
                    "finished_at": finished_at,
                    "elapsed_ms": elapsed_ms,
                },
                expected={"status": current.status},
            )
            for task_id in current.task_ids:
                tx.event_store.append(
                    TaskEventDraft(
                        task_id=task_id,
                        kind="node_run.finalized",
                        payload_json={
                            "node_run_id": str(current.id),
                            "status": status,
                        },
                    )
                )
            return changed


__all__ = ["NodeRunNotFound", "NodeRunService"]
