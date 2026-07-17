"""`app.task.store` — Store 端口 + 内存 / SQLite 双实现。

导出：

- 五个 `Protocol` 端口：`TaskStore` / `NodeRunStore` / `ProviderTaskStore`
  / `TaskEventStore` / `ArtifactStore`。
- 两套实现：`MemoryTaskStore`... 与 `SqliteTaskStore`... —— 分别用于契约
  测试与真实 SQLite 后端。
- 便捷工厂：`memory_stores()` 与 `sqlite_stores()` 一次返回五件套元组。

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

__all__ = [
    # ports
    "TaskStore",
    "NodeRunStore",
    "ProviderTaskStore",
    "TaskEventStore",
    "ArtifactStore",
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
]
