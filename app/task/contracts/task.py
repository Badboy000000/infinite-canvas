"""`app.task.contracts.task` — Task Snapshot / Draft / 状态字面量 / 恢复过滤器。

字段严格对齐 [[30 治理方案/任务模型与后台任务治理方案]] §"目标对象 · Task"。
主键类型为 `uuid.UUID`（[[50 决策记录/决策 - 主键类型]] §"决策结论"）。

**本 PR 起冻结**：字段名、字段顺序、字段类型的稳定视为契约；未来 PR 允许
追加字段，不允许删改。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Optional, Sequence
from uuid import UUID

# ---------------------------------------------------------------------------
# 状态与字面量
# ---------------------------------------------------------------------------

#: [[任务模型与后台任务治理方案]] §"状态机 · 系统 Task 状态" 全部 14 态。
TaskStatus = Literal[
    "created",
    "queued",
    "leased",
    "running",
    "waiting_upstream",
    "downloading",
    "retrying",
    "succeeded",
    "failed",
    "timed_out",
    "cancel_requested",
    "cancelled",
    "expired",
    "unknown_recoverable",
]

#: 状态机中的**终态**（不再迁移）。恢复扫描必须排除这些状态。
TERMINAL_TASK_STATUSES: frozenset = frozenset(
    {"succeeded", "failed", "cancelled", "expired"}
)

#: 恢复扫描默认关注的状态（治理方案 §"恢复策略"）。
RECOVERABLE_TASK_STATUSES: frozenset = frozenset(
    {"running", "waiting_upstream", "downloading", "retrying", "unknown_recoverable"}
)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


class CasFailure(RuntimeError):
    """条件更新 (compare-and-swap) / 乐观锁失败。

    - `expected` / `actual`：期望与实际的版本号或状态，供调用方决策重试
      策略。
    - `key`：冲突判定字段名，例如 `"revision"` / `"lease_owner"`。
    """

    def __init__(
        self,
        message: str,
        *,
        key: str,
        expected: Any = None,
        actual: Any = None,
    ) -> None:
        super().__init__(message)
        self.key = key
        self.expected = expected
        self.actual = actual


# ---------------------------------------------------------------------------
# 值对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeaseInfo:
    """租约 / 心跳 / 期限的聚合视图。

    Store 端口对外暴露此值对象，避免 8 个入参散布在 `update_lease` 之类
    的方法上。
    """

    lease_owner: Optional[str]
    lease_until: Optional[datetime]
    heartbeat_at: Optional[datetime]
    deadline_at: Optional[datetime]


@dataclass(frozen=True)
class RecoveryFilter:
    """批量恢复扫描过滤器。

    - `statuses`：只扫描这些状态；缺省 `RECOVERABLE_TASK_STATUSES`。
    - `lease_expired_before`：只捞 `lease_until < 该时间` 的任务
      （worker 心跳超时判据）。
    - `workspace_id` / `project_id` / `owner_user_id`：多租户过滤。
    - `limit` / `offset`：分页。
    """

    statuses: Sequence[str] = field(default=())
    lease_expired_before: Optional[datetime] = None
    workspace_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    limit: int = 100
    offset: int = 0


# ---------------------------------------------------------------------------
# Snapshot / Draft
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """Task Snapshot — Store 层对外唯一交换类型。

    字段清单严格对齐治理方案 §"目标对象 · Task"，含 `schema_version` 字段
    （治理方案要求预留）。
    """

    id: UUID
    task_type: str
    status: str  # 运行时约束为 TaskStatus；类型层用 str 允许 Store 层演进
    priority: int
    idempotency_key: Optional[str]
    cancel_requested: bool
    owner_user_id: Optional[UUID]
    workspace_id: Optional[UUID]
    project_id: Optional[UUID]
    canvas_id: Optional[str]
    node_id: Optional[str]
    node_run_id: Optional[UUID]
    provider_id: Optional[str]
    model: Optional[str]
    workflow_id: Optional[str]
    input_snapshot: Mapping[str, Any]
    output_refs: Sequence[Any]
    attempt: int
    max_attempts: int
    retry_after: Optional[datetime]
    lease_owner: Optional[str]
    lease_until: Optional[datetime]
    heartbeat_at: Optional[datetime]
    deadline_at: Optional[datetime]
    timeout_policy: Mapping[str, Any]
    error_code: Optional[str]
    error_message: Optional[str]
    error_category: Optional[str]
    cost_estimate: Optional[float]
    cost_actual: Optional[float]
    quota_bucket: Optional[str]
    created_at: datetime
    queued_at: Optional[datetime]
    started_at: Optional[datetime]
    updated_at: datetime
    finished_at: Optional[datetime]
    schema_version: str = "v1"


@dataclass(frozen=True)
class TaskDraft:
    """Task 提交侧的输入 dataclass。

    - `id` 缺省时由 Store 生成 UUIDv7；调用方也可指定（例如从
      `idempotency_key` 回查后透传）。
    - `status` 缺省 `"queued"`（治理方案 §"状态机" 默认入口）。
    - `input_snapshot` 必须是 JSON 可序列化的 mapping；Store 层内部
      走 SQLAlchemy `JSON()` 列。
    """

    task_type: str
    input_snapshot: Mapping[str, Any] = field(default_factory=dict)
    id: Optional[UUID] = None
    status: str = "queued"
    priority: int = 0
    idempotency_key: Optional[str] = None
    owner_user_id: Optional[UUID] = None
    workspace_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    canvas_id: Optional[str] = None
    node_id: Optional[str] = None
    node_run_id: Optional[UUID] = None
    provider_id: Optional[str] = None
    model: Optional[str] = None
    workflow_id: Optional[str] = None
    output_refs: Sequence[Any] = field(default_factory=tuple)
    max_attempts: int = 1
    timeout_policy: Mapping[str, Any] = field(default_factory=dict)
    quota_bucket: Optional[str] = None
    cost_estimate: Optional[float] = None
    deadline_at: Optional[datetime] = None
    schema_version: str = "v1"


__all__ = [
    "Task",
    "TaskDraft",
    "TaskStatus",
    "TERMINAL_TASK_STATUSES",
    "RECOVERABLE_TASK_STATUSES",
    "LeaseInfo",
    "RecoveryFilter",
    "CasFailure",
]
