"""`app.db` — SQLAlchemy 2.x Core + Alembic 脚手架（数据 PR-1）。

本包只承载"承载层"骨架：

- `engine`：SQLAlchemy `Engine` 工厂 + Alembic migrate CLI dispatch。
- `session`：`SessionLocal` sessionmaker 惰性绑定 + `get_session()` context manager
  （**不引入 FastAPI 依赖注入耦合**，Service / Store 层显式调用即可）。
- `base`：`metadata: MetaData` 单例 + 命名约定 4 条 key。**不定义任何 Table /
  Mapped 类**——聚合根 typed ORM 与 Core Table 定义留给后续 PR
  （权限 PR-1、任务 PR-0、数据 PR-3 等）。
- `migrations/`：Alembic 迁移目录，`env.py` 指向 `app.db.base.metadata`。

签名冻结（本 PR 起）：

- `engine.create_engine(url=None) -> Engine`：URL 缺省时通过
  `get_settings().data_db_path` 现读构造 `sqlite:///<abs-path>`。
- `engine.get_engine() -> Engine`：进程内单例，`reset_engine()` 供测试拆除。
- `engine.get_database_url() -> str`：只读、每次现读，供 Alembic env.py 与
  CLI 复用同一入口。
- `session.SessionLocal() -> Session`：返回**新**会话，`autoflush=False,
  expire_on_commit=False`。
- `session.get_session() -> ContextManager[Session]`：try/commit/except/rollback
  /finally close 模板。

**不做**：

- 不定义任何 Table / Mapped class / ORM 模型。
- 不接入任何 Store facade（PR-BE-04 与后续数据 PR 承接）。
- 不改路由，不改 OpenAPI baseline（`openapi_diff.py --baseline` exit=0）。
- 不动 `main.py:302-388`（`StorageSettings` / `apply_storage_settings` 冻结区）。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-1、
[[50 决策记录/决策 - ORM 与迁移工具选型]] 使用规范 §3 / §4。
"""

from app.db import base, engine, session  # noqa: F401  facade re-export

__all__ = ["base", "engine", "session"]
