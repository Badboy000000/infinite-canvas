from __future__ import annotations

from typing import Optional
from uuid import UUID

from app.task.contracts import ProviderTask, ProviderTaskDraft, TaskEventDraft
from app.task.store import ProviderTaskStore, TaskEventStore, TaskStore

from .state_machine import TaskNotFound, TaskStateError
from .unit_of_work import TaskUnitOfWork, task_unit_of_work


class ProviderTaskNotFound(TaskStateError):
    pass


class ProviderTaskService:
    """Provider 协议翻译层之上的持久化服务边界。"""

    def __init__(
        self,
        task_store: TaskStore,
        provider_task_store: ProviderTaskStore,
        event_store: TaskEventStore,
        unit_of_work: Optional[TaskUnitOfWork] = None,
    ) -> None:
        self.task_store = task_store
        self.provider_task_store = provider_task_store
        self.event_store = event_store
        self.unit_of_work = unit_of_work or task_unit_of_work(
            task_store=task_store,
            provider_task_store=provider_task_store,
            event_store=event_store,
        )

    def submit(self, draft: ProviderTaskDraft) -> ProviderTask:
        with self.unit_of_work.transaction() as tx:
            assert tx.task_store and tx.provider_task_store and tx.event_store
            if tx.task_store.get(draft.task_id) is None:
                raise TaskNotFound(f"task not found: {draft.task_id}")
            provider_task = tx.provider_task_store.create(draft)
            tx.event_store.append(
                TaskEventDraft(
                    task_id=draft.task_id,
                    kind="provider.submitted",
                    payload_json={
                        "provider_task_id": str(provider_task.id),
                        "provider_id": provider_task.provider_id,
                        "upstream_task_id": provider_task.upstream_task_id,
                    },
                )
            )
            return provider_task

    def query(self, provider_task_id: UUID | str) -> ProviderTask:
        normalized = (
            provider_task_id
            if isinstance(provider_task_id, UUID)
            else UUID(provider_task_id)
        )
        provider_task = self.provider_task_store.get(normalized)
        if provider_task is None:
            raise ProviderTaskNotFound(
                f"provider task not found: {normalized}"
            )
        return provider_task

    def recover(self, provider_id: str, upstream_task_id: str) -> ProviderTask:
        provider_task = self.provider_task_store.find_by_upstream(
            provider_id, upstream_task_id
        )
        if provider_task is None:
            raise ProviderTaskNotFound(
                f"provider task not found: {provider_id}/{upstream_task_id}"
            )
        return provider_task


__all__ = ["ProviderTaskNotFound", "ProviderTaskService"]
