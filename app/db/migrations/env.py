"""Alembic env — 数据 PR-1。

设计要点：

- `target_metadata = app.db.base.metadata`：**所有**未来聚合根 typed ORM 与
  Core `Table` 都必须挂到此 metadata；`autogenerate` 才能感知 schema drift。
- **URL 来源**：`app.db.engine.get_database_url()`（读时求值）；**禁止**从
  `context.config.get_main_option("sqlalchemy.url")` 直接取，除非该值为
  非空且非占位符 `${DB_URL}`（`alembic.ini` 内的默认值为占位符）。
- `render_as_batch=True`：SQLite ALTER 支持有限，需要 Alembic 走 batch。
  详见决策 §4。
- `compare_type=True`：`autogenerate` 感知列类型变更。
- Offline / online 双路径均使用同一 URL 与 metadata。

**本 PR 不做**：

- 不定义任何 Table / Mapped class。
- 不发起任何 `op.create_table` 调用；`0001_baseline` 迁移由后续 PR 追加。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-1。
"""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# 模块级：由 Alembic runner 注入
config = context.config

# Alembic ini 文件里的 logging 配置（如有）
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:  # pragma: no cover
        # 允许 alembic.ini 缺失 [loggers] 段——本项目治理期不强依赖 logging 段
        logging.getLogger(__name__).debug(
            "alembic env: fileConfig skipped (%s)", config.config_file_name
        )

# 目标 metadata：全局唯一。所有后续 PR 的表定义都必须挂到此 metadata。
from app.db.base import metadata as target_metadata  # noqa: E402

# 触发所有业务表模块 import，使其 Table 定义挂到 `metadata` 上。任务 PR-0
# 起，新专题在 `app/<domain>/tables.py` 定义 Table 后需在此追加 import 行。
# 顺序敏感：外键引用者晚于被引用者，本 PR 单一文件无顺序问题。
import app.task.tables  # noqa: E402,F401

# 读时求值 URL；覆盖 alembic.ini 中的 `${DB_URL}` 占位符
from app.db.engine import get_database_url  # noqa: E402


def _resolved_url() -> str:
    """从 `Settings` 现读 DB URL；不接受 alembic.ini 里的占位符。"""
    return get_database_url()


def run_migrations_offline() -> None:
    """离线迁移：生成 SQL 不连库。"""
    url = _resolved_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线迁移：连库执行。"""
    # 把 [alembic] section 复制成 mutable dict，注入解析后的 URL
    section = config.get_section(config.config_ini_section) or {}
    section = dict(section)
    section["sqlalchemy.url"] = _resolved_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
