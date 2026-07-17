"""`app.task.contracts` — 任务层契约包。

导出：

- `Task`、`NodeRun`、`ProviderTask`、`TaskEvent`、`Artifact`：Snapshot dataclass
  (`@dataclass(frozen=True)`)，Store 层对外唯一交换类型。
- `TaskStatus`、`ProviderTaskStatus`、`TaskEventKind`：字符串枚举（`Literal`），
  与治理方案状态清单严格对齐。
- `TaskDraft` / `NodeRunDraft` / `ProviderTaskDraft` / `TaskEventDraft`
  / `ArtifactDraft`：写入侧输入 dataclass；`id` 缺省由 Store 生成。
- `RecoveryFilter`：批量恢复扫描过滤器。
- `LeaseInfo`：`lease / heartbeat / deadline` 相关字段的聚合视图。
- `CasFailure`：条件更新（compare-and-swap / 乐观锁）失败异常。

**约束**：

- 本包**不 import SQLAlchemy**（层间可 review 硬约束）。
- 本包**不 import FastAPI / Pydantic**（保持 Snapshot 与 API DTO 分离；
  Snapshot 层用标准库 dataclass）。
- 所有字段名严格对齐 [[30 治理方案/任务模型与后台任务治理方案]] §"目标对象"。

详见 [[40 实施计划/任务模型与后台任务治理实施计划与PR清单]] PR-0/PR-1、
[[50 决策记录/决策 - ORM 与迁移工具选型]] §7、
[[50 决策记录/决策 - 主键类型]]。
"""

from __future__ import annotations

from app.task.contracts.artifact import Artifact, ArtifactDraft
from app.task.contracts.node_run import NodeRun, NodeRunDraft
from app.task.contracts.provider_task import ProviderTask, ProviderTaskDraft
from app.task.contracts.task import (
    CasFailure,
    LeaseInfo,
    RecoveryFilter,
    Task,
    TaskDraft,
    TaskStatus,
)
from app.task.contracts.task_event import TaskEvent, TaskEventDraft, TaskEventKind

__all__ = [
    "Task",
    "TaskDraft",
    "TaskStatus",
    "LeaseInfo",
    "RecoveryFilter",
    "CasFailure",
    "NodeRun",
    "NodeRunDraft",
    "ProviderTask",
    "ProviderTaskDraft",
    "TaskEvent",
    "TaskEventDraft",
    "TaskEventKind",
    "Artifact",
    "ArtifactDraft",
]
