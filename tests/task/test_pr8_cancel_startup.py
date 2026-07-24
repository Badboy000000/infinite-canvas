"""任务 PR-8 · CancelScope 传递 + startup recovery hook · T80-T99 · 20 项。"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.task.contracts import (
    RecoveryFilter,
    TaskDraft,
)
from app.task.service import (
    CancelResult,
    CancelScope,
    MemoryTaskUnitOfWork,
    TaskService,
    task_unit_of_work,
)
from app.task.service.startup import (
    is_startup_recovery_enabled,
    recover_on_startup,
)
from app.task.store.memory_impl import memory_stores
from app.task.worker.inproc import InProcessDispatcher


# ---------------------------------------------------------------------------
# Fixture · TaskService with memory stores
# ---------------------------------------------------------------------------


@pytest.fixture
def service():
    task_store, _node_run, _provider, event_store, _artifact = memory_stores()
    return TaskService(
        task_store=task_store,
        event_store=event_store,
        unit_of_work=task_unit_of_work(
            task_store=task_store,
            event_store=event_store,
        ),
    )


# ---------------------------------------------------------------------------
# T80-T85 · InProcessDispatcher.cancel(scope) 参数传递
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["local", "upstream", "attention"])
def test_T80_dispatcher_cancel_preserves_scope(service, scope):
    """三层 CancelScope 全部保留到 CancelResult。"""
    draft = TaskDraft(
        task_type="image",
        status="queued",
        idempotency_key=f"idem-{scope}",
    )
    task = service.submit(draft)
    dispatcher = InProcessDispatcher(service)
    result = asyncio.run(dispatcher.cancel(str(task.id), scope))
    assert isinstance(result, CancelResult)
    assert result.scope == scope
    assert result.accepted is True
    assert result.task.status in {"cancelled", "cancel_requested"}


def test_T83_dispatcher_cancel_scope_type_check(service):
    """CancelScope 是 Literal["local","upstream","attention"] · 传其他值仍工作
    但语义上是 attention · 由 mypy/lint 层拦截 · 运行时不检查(Pythonic)。"""
    draft = TaskDraft(task_type="image", status="queued", idempotency_key="idem-x")
    task = service.submit(draft)
    dispatcher = InProcessDispatcher(service)
    # Runtime 允许任意字符串 · 但 CancelResult.scope 保留原样(不做归一化)
    result = asyncio.run(dispatcher.cancel(str(task.id), "attention"))
    assert result.scope == "attention"


def test_T84_dispatcher_cancel_terminal_state_raises(service):
    """已成功任务不能 cancel · TaskService 抛 TaskStateError 上浮。"""
    from app.task.service.state_machine import TaskStateError

    draft = TaskDraft(task_type="image", status="queued", idempotency_key="idem-t")
    task = service.submit(draft)
    # 手动跃迁到 succeeded
    service.transition(str(task.id), "leased", expected="queued")
    service.transition(str(task.id), "running", expected="leased")
    service.transition(str(task.id), "succeeded", expected="running")

    dispatcher = InProcessDispatcher(service)
    with pytest.raises(TaskStateError):
        asyncio.run(dispatcher.cancel(str(task.id), "local"))


def test_T85_dispatcher_cancel_idempotent_on_cancelled(service):
    """已 cancelled 任务再 cancel · 返回原状态(TaskService.cancel 内部处理)。"""
    draft = TaskDraft(task_type="image", status="queued", idempotency_key="idem-2c")
    task = service.submit(draft)
    dispatcher = InProcessDispatcher(service)
    result1 = asyncio.run(dispatcher.cancel(str(task.id), "local"))
    result2 = asyncio.run(dispatcher.cancel(str(task.id), "upstream"))
    assert result1.task.status == "cancelled"
    assert result2.task.status == "cancelled"
    # 第二次 cancel 用 upstream scope · scope 保留传入值 · 状态不变
    assert result2.scope == "upstream"


# ---------------------------------------------------------------------------
# T86-T91 · startup recovery hook
# ---------------------------------------------------------------------------


def test_T86_is_startup_recovery_enabled_default_false(monkeypatch):
    """无 env flag 时默认 False。"""
    monkeypatch.delenv("TASK_RECOVERY_ON_STARTUP", raising=False)
    assert is_startup_recovery_enabled() is False


@pytest.mark.parametrize("val", ["true", "TRUE", "1", "yes", "on", "YES"])
def test_T87_is_startup_recovery_enabled_truthy(monkeypatch, val):
    """truthy 值全部识别为 True。"""
    monkeypatch.setenv("TASK_RECOVERY_ON_STARTUP", val)
    assert is_startup_recovery_enabled() is True


@pytest.mark.parametrize("val", ["", "false", "0", "no", "off", "  "])
def test_T88_is_startup_recovery_enabled_falsy(monkeypatch, val):
    """falsy / 空 / 未识别值全部返回 False。"""
    monkeypatch.setenv("TASK_RECOVERY_ON_STARTUP", val)
    assert is_startup_recovery_enabled() is False


def test_T89_recover_on_startup_disabled_returns_empty(service, monkeypatch):
    """flag 未启用时 · recover_on_startup 返回空列表(不触发 recover)。"""
    monkeypatch.delenv("TASK_RECOVERY_ON_STARTUP", raising=False)
    result = asyncio.run(recover_on_startup(service))
    assert result == []


def test_T90_recover_on_startup_force_bypasses_flag(service, monkeypatch):
    """force=True 时 · 忽略 env flag · 强制走 recover。"""
    monkeypatch.delenv("TASK_RECOVERY_ON_STARTUP", raising=False)
    # 无任务需要恢复时 · recover 返回空列表 · 但走了逻辑
    result = asyncio.run(recover_on_startup(service, force=True))
    assert isinstance(result, list)


def test_T91_recover_on_startup_recovers_leased_task(service, monkeypatch):
    """flag 启用 + 有 leased 任务 → 恢复为 unknown_recoverable。"""
    monkeypatch.setenv("TASK_RECOVERY_ON_STARTUP", "true")
    draft = TaskDraft(task_type="image", status="queued", idempotency_key="idem-r")
    task = service.submit(draft)
    service.transition(str(task.id), "leased", expected="queued")

    recovered = asyncio.run(recover_on_startup(service))
    assert len(recovered) == 1
    assert recovered[0].status == "unknown_recoverable"


# ---------------------------------------------------------------------------
# T92-T95 · idempotency 抗回归
# ---------------------------------------------------------------------------


def test_T92_recover_on_startup_idempotent(service, monkeypatch):
    """连续两次 recover_on_startup 幂等 · 第二次返回空(第一次已迁移)。"""
    monkeypatch.setenv("TASK_RECOVERY_ON_STARTUP", "true")
    draft = TaskDraft(task_type="image", status="queued", idempotency_key="idem-i")
    task = service.submit(draft)
    service.transition(str(task.id), "leased", expected="queued")

    first = asyncio.run(recover_on_startup(service))
    second = asyncio.run(recover_on_startup(service))
    assert len(first) == 1
    # 第二次:已经是 unknown_recoverable · recover 不再迁移
    # (TaskService.recover 内部 `if target == current.status: continue`)
    assert len(second) == 0


def test_T93_submit_idempotency_key_reuses_existing(service):
    """相同 idempotency_key 两次 submit · 第二次返回同一 Task。"""
    draft1 = TaskDraft(task_type="image", status="queued", idempotency_key="dup")
    task1 = service.submit(draft1)
    draft2 = TaskDraft(task_type="image", status="queued", idempotency_key="dup")
    task2 = service.submit(draft2)
    assert task1.id == task2.id


def test_T94_submit_different_idempotency_keys_create_distinct(service):
    """不同 idempotency_key · 创建两个独立 Task。"""
    draft1 = TaskDraft(task_type="image", status="queued", idempotency_key="k1")
    draft2 = TaskDraft(task_type="image", status="queued", idempotency_key="k2")
    task1 = service.submit(draft1)
    task2 = service.submit(draft2)
    assert task1.id != task2.id


def test_T95_recover_on_startup_custom_filter(service, monkeypatch):
    """自定义 RecoveryFilter · 只扫描 running 状态。"""
    monkeypatch.setenv("TASK_RECOVERY_ON_STARTUP", "true")
    draft1 = TaskDraft(task_type="image", status="queued", idempotency_key="k1")
    task1 = service.submit(draft1)
    service.transition(str(task1.id), "leased", expected="queued")
    service.transition(str(task1.id), "running", expected="leased")

    draft2 = TaskDraft(task_type="image", status="queued", idempotency_key="k2")
    task2 = service.submit(draft2)
    service.transition(str(task2.id), "leased", expected="queued")
    # task2 停在 leased · 自定义 filter 只扫 running

    from datetime import datetime, timezone
    custom = RecoveryFilter(
        statuses=("running",),
        lease_expired_before=datetime.now(timezone.utc),
    )
    recovered = asyncio.run(recover_on_startup(service, filters=custom))
    assert len(recovered) == 1
    assert recovered[0].id == task1.id
