"""`app.task.store` — Store 端口 + 内存 / SQLite 双实现。

导出：

- 五个 `Protocol` 端口：`TaskStore` / `NodeRunStore` / `ProviderTaskStore`
  / `TaskEventStore` / `ArtifactStore`。
- 两套实现：`MemoryTaskStore`... 与 `SqliteTaskStore`... —— 分别用于契约
  测试与真实 SQLite 后端。
- 便捷工厂：`memory_stores()` 与 `sqlite_stores()` 一次返回五件套元组。
- **数据 PR-11（Wave 3-N.6 Batch 1 主线 A）新增**：`create_stores()` 无参
  分派工厂——按 `Settings.task_primary_write`（→ `main.TASK_PRIMARY_WRITE`）
  转发到 `memory_stores()` / `sqlite_stores()`。**不改这两个既有工厂签名**。

**接口签名冻结**（任务 PR-0 起，覆盖 [[40 实施计划/任务模型与后台任务治理实施计划与PR清单]] PR-1 契约）：

- CRUD：`create` / `get` / `list`（`list` 按 `RecoveryFilter` 或等价 filter）
- 条件更新（compare-and-swap / 乐观锁）：`update_with_expected(id, updates,
  *, expected)` — 冲突抛 `CasFailure`
- 租约 / 心跳 / 期限：`acquire_lease(id, owner, ttl_sec)` / `heartbeat(id,
  owner)` / `release_lease(id, owner, ...)`
- 事件追加顺序：`append(event)` 返回 `TaskEvent` snapshot 且 `seq` 严格
  单调（同一 task_id 内）
- 批量恢复扫描：`scan(filter: RecoveryFilter)` 返回 `list[Task]`

具体实现内部通过 `from app.db.session import get_session` 消费 SQLite；
Memory 实现使用线程锁保护 dict / list。

不做（本 PR）：

- 不引入 worker loop / dispatcher。
- 不接入 `main.py` 现有生成路径。
- 不新增 store public 方法之外的 API 层入口。
"""

from __future__ import annotations

from app.task.store.base import (
    ArtifactStore,
    NodeRunStore,
    ProviderTaskStore,
    StoreBundle,
    TaskEventStore,
    TaskStore,
)
from app.task.store.memory_impl import (
    MemoryArtifactStore,
    MemoryNodeRunStore,
    MemoryProviderTaskStore,
    MemoryTaskEventStore,
    MemoryTaskStore,
    memory_stores,
)
from app.task.store.sqlite_impl import (
    SqliteArtifactStore,
    SqliteNodeRunStore,
    SqliteProviderTaskStore,
    SqliteTaskEventStore,
    SqliteTaskStore,
    sqlite_stores,
)


def create_stores() -> StoreBundle:
    """数据 PR-11：按 `Settings.task_primary_write` 分派五件套 Store。

    - `"memory"`（默认）→ `memory_stores()`（`MemoryTaskStore` 五件套；
      承接 PR-0 参考实现）。
    - `"sqlite"`         → `sqlite_stores()`（`SqliteTaskStore` 五件套；
      消费 `app.task.tables` metadata + `0001_task_layer` 已建表）。

    值域校验发生在 `_validate_task_primary_write` 里（`Settings` 构造期
    fail-fast），此工厂只做分派、不再重复校验。

    **本 PR 只加分派机制，不切默认**（GM-22 反转是后续独立 PR）。签名
    与既有 `memory_stores()` / `sqlite_stores()` 平级，`__all__` 一并
    导出。返回类型 `StoreBundle` 保证与 `app.task.service.unit_of_work`
    的 Store 消费点类型对齐。
    """

    from app.shared.settings import get_settings

    mode = get_settings().task_primary_write
    if mode == "sqlite":
        return sqlite_stores()
    # `_validate_task_primary_write` 已把值域收敛到 {"memory","sqlite"}；
    # 未知值不可能落到这里（会先在 Settings 构造期抛 ValueError）。
    return memory_stores()


__all__ = [
    # ports
    "TaskStore",
    "NodeRunStore",
    "ProviderTaskStore",
    "TaskEventStore",
    "ArtifactStore",
    "StoreBundle",
    # memory impl
    "MemoryTaskStore",
    "MemoryNodeRunStore",
    "MemoryProviderTaskStore",
    "MemoryTaskEventStore",
    "MemoryArtifactStore",
    "memory_stores",
    # sqlite impl
    "SqliteTaskStore",
    "SqliteNodeRunStore",
    "SqliteProviderTaskStore",
    "SqliteTaskEventStore",
    "SqliteArtifactStore",
    "sqlite_stores",
    # PR-11 分派工厂
    "create_stores",
]
