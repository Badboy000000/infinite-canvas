"""`app.task.contracts.task_event` — TaskEvent Snapshot / Draft / kind 字面量。

主键类型**破例**为 `int`（`BIGINT AUTOINCREMENT`；
[[50 决策记录/决策 - 主键类型]] §"允许自增 INTEGER 的破例场景"）。

`seq` 字段是应用层的单调事件号，由 Store 层在 append 时按 `task_id` 分组
生成（等于该 task 已存在事件数 + 1）；`id` 是数据库自增主键，用于全局
排序与审计溯源。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Optional
from uuid import UUID


#: 治理方案 §"目标对象 · TaskEvent · 建议事件" 全量清单。
TaskEventKind = Literal[
    "task.created",
    "task.queued",
    "task.leased",
    "task.started",
    "provider.submitted",
    "provider.polled",
    "task.downloading",
    "artifact.saved",
    "history.written",
    "task.retry_scheduled",
    "task.cancel_requested",
    "task.cancelled",
    "task.failed",
    "task.succeeded",
    "task.recovered",
]


@dataclass(frozen=True)
class TaskEvent:
    """TaskEvent Snapshot。

    - `id`：数据库自增 BIGINT；append 后由 Store 回填。
    - `seq`：按 `task_id` 分组的应用层顺序号（1-based，严格单调）；
      即使多个 worker 并发 append，Store 也保证同一 `task_id` 内
      `seq` 单调不减。
    """

    id: int
    task_id: UUID
    seq: int
    kind: str
    ts: datetime
    payload_json: Mapping[str, Any]
    schema_version: str = "v1"


@dataclass(frozen=True)
class TaskEventDraft:
    """TaskEvent 追加侧输入 dataclass。"""

    task_id: UUID
    kind: str
    payload_json: Mapping[str, Any] = field(default_factory=dict)
    ts: Optional[datetime] = None  # 缺省由 Store 填充为 UTC now
    schema_version: str = "v1"


__all__ = ["TaskEvent", "TaskEventDraft", "TaskEventKind"]
