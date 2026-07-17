from __future__ import annotations

from typing import get_args

import pytest

from app.adapters.provider.base import ProviderTaskViewStatus
from app.adapters.provider.status import (
    provider_view_status_to_task_status,
    task_status_to_provider_view_status,
)
from app.task.contracts.provider_task import ProviderTaskStatus


def test_current_task_contract_keeps_canceled_as_internal_canonical() -> None:
    task_statuses = set(get_args(ProviderTaskStatus))
    view_statuses = set(get_args(ProviderTaskViewStatus))

    assert "canceled" in task_statuses
    assert "cancelled" not in task_statuses
    assert "cancelled" in view_statuses
    assert "canceled" not in view_statuses


def test_cancel_spelling_is_mapped_explicitly_at_provider_boundary() -> None:
    assert provider_view_status_to_task_status("cancelled") == "canceled"
    assert task_status_to_provider_view_status("canceled") == "cancelled"


@pytest.mark.parametrize(
    ("view_status", "task_status"),
    [
        ("queued", "queued"),
        ("running", "running"),
        ("succeeded", "succeeded"),
        ("failed", "failed"),
        ("waiting_upstream", "submitted"),
    ],
)
def test_other_representable_statuses_have_declared_mappings(
    view_status: ProviderTaskViewStatus,
    task_status: ProviderTaskStatus,
) -> None:
    assert provider_view_status_to_task_status(view_status) == task_status
    assert task_status_to_provider_view_status(task_status) == view_status


@pytest.mark.parametrize("status", ["expired", "unknown"])
def test_lossy_task_statuses_are_not_silently_collapsed(status: ProviderTaskStatus) -> None:
    with pytest.raises(ValueError, match="no lossless ProviderTaskView mapping"):
        task_status_to_provider_view_status(status)
