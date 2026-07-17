"""`app.task.contracts.artifact` — Artifact Snapshot / Draft。

字段严格对齐 [[30 治理方案/任务模型与后台任务治理方案]] §"目标对象 · Artifact"。
`file_object_id` 是与 [[30 治理方案/文件对象与 MinIO 治理方案]] 的连接点；
治理期允许为空（承接 legacy URL）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class Artifact:
    """Artifact Snapshot。"""

    id: UUID
    task_id: Optional[UUID]
    node_run_id: Optional[UUID]
    provider_task_id: Optional[UUID]
    kind: str  # image / video / json / text / file / thumbnail / ...
    url: Optional[str]
    file_object_id: Optional[UUID]
    legacy_url: Optional[str]
    mime_type: Optional[str]
    name: Optional[str]
    width: Optional[int]
    height: Optional[int]
    duration: Optional[float]
    size: Optional[int]
    sha256: Optional[str]
    node_id: Optional[str]
    output_key: Optional[str]
    role: Optional[str]
    workspace_id: Optional[UUID]
    project_id: Optional[UUID]
    owner_user_id: Optional[UUID]
    created_at: datetime
    schema_version: str = "v1"


@dataclass(frozen=True)
class ArtifactDraft:
    """Artifact 登记侧输入 dataclass。"""

    kind: str
    id: Optional[UUID] = None
    task_id: Optional[UUID] = None
    node_run_id: Optional[UUID] = None
    provider_task_id: Optional[UUID] = None
    url: Optional[str] = None
    file_object_id: Optional[UUID] = None
    legacy_url: Optional[str] = None
    mime_type: Optional[str] = None
    name: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    size: Optional[int] = None
    sha256: Optional[str] = None
    node_id: Optional[str] = None
    output_key: Optional[str] = None
    role: Optional[str] = None
    workspace_id: Optional[UUID] = None
    project_id: Optional[UUID] = None
    owner_user_id: Optional[UUID] = None
    schema_version: str = "v1"


__all__ = ["Artifact", "ArtifactDraft"]
