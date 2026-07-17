"""`app.db.base` — SQLAlchemy `MetaData` + 命名约定单例（数据 PR-1）。

本模块只暴露 `metadata: MetaData`，携带 4 条 SQLAlchemy 官方推荐的命名约定：

- 索引：`ix_%(column_0_label)s`
- 唯一约束：`uq_%(table_name)s_%(column_0_name)s`
- 检查约束：`ck_%(table_name)s_%(constraint_name)s`
- 外键：`fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`
- 主键：`pk_%(table_name)s`

**本 PR 起硬约束**：任何后续 PR（权限 PR-1、任务 PR-0、数据 PR-3 等）在此
`metadata` 上定义 `Table` 或 `Mapped` 类；`env.py` 的 `target_metadata` 直接
`import` 本模块的 `metadata`，保证所有迁移看到同一 metadata 事实源。

**本 PR 不做**：

- 不在此定义任何 `Table` / 聚合根 ORM。
- 不 import 任何具体表模块（避免 `env.py --> base --> tables --> ...` 循环）。
- 不做任何模块级 I/O（不连库，不读文件）。

详见 [[50 决策记录/决策 - ORM 与迁移工具选型]] 使用规范 §4（迁移文件命名与目录）
与 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-1。
"""

from __future__ import annotations

from sqlalchemy import MetaData

# SQLAlchemy 官方推荐的命名约定（key 名严格与 SQLAlchemy 版本一致）；
# 覆盖 index / unique / check / foreignkey / primarykey 五类。
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# 全局 MetaData 单例。后续 PR 的 Table / DeclarativeBase 必须挂到此实例上。
metadata: MetaData = MetaData(naming_convention=NAMING_CONVENTION)


__all__ = ["metadata", "NAMING_CONVENTION"]
