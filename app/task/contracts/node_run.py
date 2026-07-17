"""`app.task.contracts.node_run` — NodeRun Snapshot / Draft。

字段严格对齐 [[30 治理方案/任务模型与后台任务治理方案]] §"目标对象 · NodeRun"。
主键类型为 `uuid.UUID`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID


@dataclass(frozen=True)
class NodeRun:
    """NodeRun Snapshot。"""

    id: UUID
    canvas_id: str
    node_id: str
    node_type: str
    source_node_id: Optional[str]
    run_kind: str
    status: str
    trigger_source: Optional[str]
    input_snapshot: Mapping[str, Any]
    settings_snapshot: Mapping[str, Any]
    dependency_snapshot: Mapping[str, Any]
    task_ids: Sequence[UUID]
    output_refs: Sequence[Any]
    parent_run_id: Optional[UUID]
    batch_key: Optional[str]
    attempt: int
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    elapsed_ms: Optional[int]
    summary: Optional[str]
    error: Optional[Mapping[str, Any]]
    workspace_id: Optional[UUID]
    project_id: Optional[UUID]
    owner_user_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime
    schema_version: str = "v1"


@dataclass(frozen=True)
class NodeRunDraft:
    """NodeRun 提交侧输入 dataclass。"""

    canvas_id: str
    node_id: str
    node_type: str
    id: Optional[UUID] = None
    source_node_id: Optional[str] = None
    run_kind: str = "generation"
    status: str = "created"
    trigger_source: Optional[str] = None
    input_snapshot: Mapping[str, Any] = field(default_factory=dict)
    settings_snapshot: Mapping[str, Any] = field(default_factory=dict)
    dependency_snapshot: Mapping[str, Any] = field(default_factory=dict)
    task_ids: Sequence[UUID] = field(default_factory=tuple)
    output_refs: Sequence[Any] = field(default_factory=tuple)
    parent_run_id: Optional[UUID] = None
    batch_key: Optional[str] = None
    attempt: int = 1
    workspace_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    schema_version: str = "v1"


__all__ = ["NodeRun", "NodeRunDraft"]
