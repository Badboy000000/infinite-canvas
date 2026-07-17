"""`app.task` — 任务事实层根包（任务 PR-0）。

本包承载 Task / NodeRun / ProviderTask / TaskEvent / Artifact 五个对象的
**schema、契约与 Store 端口**；不接入任何生成路径、不启动 worker loop。

子模块划分：

- `app.task.tables` — SQLAlchemy `Table` 定义，全部挂到
  `app.db.base.metadata` 单例上（禁自建 `MetaData()`）。首个真 Alembic
  revision `0001_task_layer` 通过 `metadata.create_all(...)` 建表。
- `app.task.contracts` — 端口契约 + Snapshot dataclass。不引入 FastAPI DI
  耦合，不 import SQLAlchemy。
- `app.task.store` — Store 端口 `Protocol` + 内存实现 + SQLite 实现。

设计原则（承接 [[50 决策记录/决策 - ORM 与迁移工具选型]] §7 三层结构）：

- Store 层对外只暴露 Snapshot（`@dataclass(frozen=True)`），不返回
  SQLAlchemy `Row` / `Session`。
- Session 生命周期由 Store 内部通过 `from app.db.session import get_session`
  管理；调用方不感知。
- 契约签名冻结（本 PR 起）：`TaskStore / NodeRunStore / ProviderTaskStore
  / TaskEventStore / ArtifactStore` 六类接口（CRUD / 条件更新 / 乐观锁 /
  lease / 事件追加 / 恢复扫描）。

详见 [[40 实施计划/任务模型与后台任务治理实施计划与PR清单]] PR-0/PR-1。
"""
