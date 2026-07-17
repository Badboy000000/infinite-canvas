"""`app.task.contracts.provider_task` — ProviderTask Snapshot / Draft。

字段严格对齐 [[30 治理方案/任务模型与后台任务治理方案]] §"目标对象 · ProviderTask"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, Optional
from uuid import UUID


ProviderTaskStatus = Literal[
    "queued",
    "submitted",
    "running",
    "succeeded",
    "failed",
    "canceled",
    "expired",
    "unknown",
]


@dataclass(frozen=True)
class ProviderTask:
    """ProviderTask Snapshot。"""

    id: UUID
    task_id: UUID
    provider_id: str
    provider_protocol: str
    capability: Optional[str]
    operation: Optional[str]
    upstream_task_id: Optional[str]
    upstream_task_kind: Optional[str]
    remote_status: Optional[str]
    status: str
    progress: Optional[float]
    poll_after: Optional[datetime]
    poll_count: int
    last_poll_at: Optional[datetime]
    outputs: Mapping[str, Any]
    error: Optional[Mapping[str, Any]]
    raw_excerpt: Optional[str]
    query_params: Mapping[str, Any]
    adapter_kind: Optional[str]
    created_at: datetime
    submitted_at: Optional[datetime]
    updated_at: datetime
    completed_at: Optional[datetime]
    schema_version: str = "v1"


@dataclass(frozen=True)
class ProviderTaskDraft:
    """ProviderTask 提交侧输入 dataclass。"""

    task_id: UUID
    provider_id: str
    provider_protocol: str
    id: Optional[UUID] = None
    capability: Optional[str] = None
    operation: Optional[str] = None
    upstream_task_id: Optional[str] = None
    upstream_task_kind: Optional[str] = None
    status: str = "queued"
    remote_status: Optional[str] = None
    outputs: Mapping[str, Any] = field(default_factory=dict)
    query_params: Mapping[str, Any] = field(default_factory=dict)
    adapter_kind: Optional[str] = None
    schema_version: str = "v1"


__all__ = ["ProviderTask", "ProviderTaskDraft", "ProviderTaskStatus"]
