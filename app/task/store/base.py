"""`app.task.store.base` — 五个 Store 端口 `Protocol` 定义。

签名冻结（本 PR 起）。任何实现类需实现相同签名；`Protocol` 使用
`runtime_checkable` 让 `isinstance(x, TaskStore)` 在测试中可用。

设计原则：

- Store 端口只暴露 Snapshot（`app.task.contracts` 定义），不返回底层
  Row / Session。
- 条件更新 / 乐观锁通过 `CasFailure` 表达，不用返回 `bool`（避免调用方
  忘记检查）。
- 事件 append 顺序化：同一 `task_id` 内的 `seq` 单调不减，由 Store 保证。
- 恢复扫描接收 `RecoveryFilter`，参数聚合避免签名膨胀。
"""

from __future__ import annotations

from typing import List, Mapping, Optional, Protocol, Tuple, runtime_checkable
from uuid import UUID

from app.task.contracts import (
    Artifact,
    ArtifactDraft,
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


@runtime_checkable
class TaskStore(Protocol):
    """Task 事实层 CRUD + 条件更新 + 租约 + 恢复扫描端口。"""

    # --- CRUD ---
    def create(self, draft: TaskDraft) -> Task: ...
    def get(self, task_id: UUID) -> Optional[Task]: ...
    def get_by_idempotency_key(self, key: str) -> Optional[Task]: ...
    def list_by_canvas_node(
        self, canvas_id: str, node_id: Optional[str] = None, *, limit: int = 100
    ) -> List[Task]: ...

    # --- 条件更新（乐观锁 / compare-and-swap）---
    def update_with_expected(
        self,
        task_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> Task:
        """按 `expected` 比对当前字段值：全部匹配才提交 `updates`；否则
        抛 `CasFailure`。`updates` 与 `expected` 的 key 必须是 Task 字段名。
        """
        ...

    # --- 租约 / 心跳 / 期限 ---
    def acquire_lease(
        self, task_id: UUID, owner: str, ttl_sec: int
    ) -> Task:
        """把 `queued` / `unknown_recoverable` 或 `lease_until < now()` 的
        Task 抢占为 `leased`；成功返回新 snapshot，失败抛 `CasFailure`。
        """
        ...

    def heartbeat(self, task_id: UUID, owner: str, *, ttl_sec: int) -> Task:
        """`lease_owner == owner` 时刷新 `heartbeat_at` 与 `lease_until`；
        失败抛 `CasFailure`。"""
        ...

    def release_lease(
        self,
        task_id: UUID,
        owner: str,
        *,
        new_status: Optional[str] = None,
    ) -> Task:
        """释放租约（清除 `lease_owner` / `lease_until`）；可同时切换到
        `new_status`（例如 `succeeded` / `failed` / `retrying`）。"""
        ...

    # --- 批量恢复扫描 ---
    def scan(self, filter: RecoveryFilter) -> List[Task]:
        """按 filter 返回可恢复 Task 列表；`filter.limit` 保护结果规模。"""
        ...


@runtime_checkable
class NodeRunStore(Protocol):
    """NodeRun 事实层端口。"""

    def create(self, draft: NodeRunDraft) -> NodeRun: ...
    def get(self, node_run_id: UUID) -> Optional[NodeRun]: ...
    def list_by_canvas(
        self, canvas_id: str, *, limit: int = 100
    ) -> List[NodeRun]: ...
    def update_with_expected(
        self,
        node_run_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> NodeRun: ...


@runtime_checkable
class ProviderTaskStore(Protocol):
    """ProviderTask 事实层端口。"""

    def create(self, draft: ProviderTaskDraft) -> ProviderTask: ...
    def get(self, provider_task_id: UUID) -> Optional[ProviderTask]: ...
    def find_by_upstream(
        self, provider_id: str, upstream_task_id: str
    ) -> Optional[ProviderTask]: ...
    def list_by_task(self, task_id: UUID) -> List[ProviderTask]: ...
    def update_with_expected(
        self,
        provider_task_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> ProviderTask: ...


@runtime_checkable
class TaskEventStore(Protocol):
    """TaskEvent append-only 事件流端口。

    - `append` 按 `task_id` 分组给出严格单调 `seq`。
    - `list_for_task` 按 `seq ASC` 或 `id ASC` 返回。
    """

    def append(self, draft: TaskEventDraft) -> TaskEvent: ...
    def list_for_task(
        self,
        task_id: UUID,
        *,
        since_seq: Optional[int] = None,
        limit: int = 500,
    ) -> List[TaskEvent]: ...
    def count_for_task(self, task_id: UUID) -> int: ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Artifact 登记端口。"""

    def create(self, draft: ArtifactDraft) -> Artifact: ...
    def get(self, artifact_id: UUID) -> Optional[Artifact]: ...
    def list_by_task(self, task_id: UUID) -> List[Artifact]: ...
    def list_by_node_run(self, node_run_id: UUID) -> List[Artifact]: ...


#: 五件套 Store 元组类型别名（便于工厂返回值标注）
StoreBundle = Tuple[
    TaskStore, NodeRunStore, ProviderTaskStore, TaskEventStore, ArtifactStore
]

__all__ = [
    "TaskStore",
    "NodeRunStore",
    "ProviderTaskStore",
    "TaskEventStore",
    "ArtifactStore",
    "StoreBundle",
]
