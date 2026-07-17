from __future__ import annotations

from typing import Mapping


class TaskStateError(RuntimeError):
    pass


class TaskNotFound(TaskStateError):
    pass


class InvalidTaskTransition(TaskStateError):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"invalid task transition: {current} -> {target}")
        self.current = current
        self.target = target


TASK_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "created": frozenset({"queued", "cancel_requested", "cancelled"}),
    "queued": frozenset({"leased", "cancel_requested", "cancelled"}),
    "leased": frozenset(
        {"running", "queued", "cancel_requested", "cancelled", "unknown_recoverable"}
    ),
    "running": frozenset(
        {
            "waiting_upstream",
            "downloading",
            "retrying",
            "succeeded",
            "failed",
            "timed_out",
            "cancel_requested",
            "cancelled",
            "unknown_recoverable",
        }
    ),
    "waiting_upstream": frozenset(
        {
            "downloading",
            "succeeded",
            "failed",
            "timed_out",
            "cancel_requested",
            "cancelled",
            "unknown_recoverable",
        }
    ),
    "downloading": frozenset(
        {
            "retrying",
            "succeeded",
            "failed",
            "timed_out",
            "cancel_requested",
            "cancelled",
            "unknown_recoverable",
        }
    ),
    "retrying": frozenset(
        {"queued", "leased", "failed", "cancel_requested", "cancelled", "expired"}
    ),
    "timed_out": frozenset(
        {"retrying", "cancel_requested", "cancelled", "unknown_recoverable"}
    ),
    "cancel_requested": frozenset({"cancelled"}),
    "unknown_recoverable": frozenset(
        {"queued", "leased", "waiting_upstream", "failed", "cancel_requested", "cancelled"}
    ),
    "succeeded": frozenset(),
    "failed": frozenset({"retrying"}),
    "cancelled": frozenset({"retrying"}),
    "expired": frozenset(),
}


def ensure_transition(current: str, target: str) -> None:
    if target not in TASK_TRANSITIONS.get(current, frozenset()):
        raise InvalidTaskTransition(current, target)


__all__ = [
    "InvalidTaskTransition",
    "TASK_TRANSITIONS",
    "TaskNotFound",
    "TaskStateError",
    "ensure_transition",
]
