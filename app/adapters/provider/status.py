"""Explicit status boundary between Provider views and task persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.adapters.provider.base import ProviderTaskViewStatus

if TYPE_CHECKING:
    from app.task.contracts.provider_task import ProviderTaskStatus


_VIEW_TO_TASK: dict[ProviderTaskViewStatus, ProviderTaskStatus] = {
    "queued": "queued",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "canceled",
    "waiting_upstream": "submitted",
}

_TASK_TO_VIEW: dict[ProviderTaskStatus, ProviderTaskViewStatus] = {
    "queued": "queued",
    "submitted": "waiting_upstream",
    "running": "running",
    "succeeded": "succeeded",
    "failed": "failed",
    "canceled": "cancelled",
}


def provider_view_status_to_task_status(status: ProviderTaskViewStatus) -> ProviderTaskStatus:
    """Normalize the adapter boundary spelling to task-layer canonical status."""

    return _VIEW_TO_TASK[status]


def task_status_to_provider_view_status(status: ProviderTaskStatus) -> ProviderTaskViewStatus:
    """Map a representable task status to the planned ProviderTaskView status set.

    ``expired`` and ``unknown`` require Provider-specific policy and are intentionally
    left to the later mapper PR instead of being silently collapsed here.
    """

    try:
        return _TASK_TO_VIEW[status]
    except KeyError as exc:
        raise ValueError(f"task status {status!r} has no lossless ProviderTaskView mapping") from exc


__all__ = [
    "provider_view_status_to_task_status",
    "task_status_to_provider_view_status",
]
