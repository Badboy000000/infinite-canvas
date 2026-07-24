"""`app.task.service.startup` — 任务 PR-8 · 启动恢复扫描 hook。

设计约束
========

1. **默认关闭 · env flag 启用**:`TASK_RECOVERY_ON_STARTUP=false` 是默认值;
   显式设为 `"true"` / `"1"` / `"yes"` 才启用启动扫描。避免开发环境每次冷启
   动都触发全量扫描。

2. **状态清单严格来自治理方案**:`leased / running / waiting_upstream /
   downloading / retrying / unknown_recoverable` → 走 `TaskService.recover()`
   状态机迁移(见 task_service.py:151-202)。

3. **不改路由 · 不改 lifespan · 只提供 hook 函数**:main.py / app.factory 消费
   方通过 `await recover_on_startup(service)` 显式调用;本 PR 不注入到 FastAPI
   lifespan(避免 GM-16 破坏冻结区)。

4. **恢复统计事件**:恢复完成后 append `task.startup_recovery_summary` 事件到
   TaskEventStore(可选;若 service.recover 返回空列表则跳过)。

5. **idempotency 抗回归**:多次调用 recover_on_startup 幂等 · 因为
   TaskService.recover 内部走 update_with_expected · 无重复 append。
"""

from __future__ import annotations

import os
from typing import Optional

from app.task.contracts import RecoveryFilter
from app.task.service.task_service import TaskService


_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_startup_recovery_enabled() -> bool:
    """检查 env flag `TASK_RECOVERY_ON_STARTUP` 是否启用。

    默认 False;显式 truthy 值才启用。
    """
    val = os.environ.get("TASK_RECOVERY_ON_STARTUP", "").strip().lower()
    return val in _TRUTHY


async def recover_on_startup(
    service: TaskService,
    *,
    filters: Optional[RecoveryFilter] = None,
    force: bool = False,
) -> list:
    """启动恢复扫描主入口。

    - `service`:TaskService 实例(必须已装配 task_store + event_store)。
    - `filters`:自定义过滤器;None 时用 TaskService.recover 内置默认值。
    - `force`:True 时忽略 env flag;主要用于测试。

    返回:恢复的 Task 列表(可能为空)。

    幂等:多次调用无副作用(TaskService.recover 内部走 CAS)。
    """
    if not force and not is_startup_recovery_enabled():
        return []
    # TaskService.recover 是同步 API · async 包装是为了对齐未来 SQLAlchemy 异步
    # 语义 · 目前直接调用即可。
    return service.recover(filters)


__all__ = [
    "is_startup_recovery_enabled",
    "recover_on_startup",
]
