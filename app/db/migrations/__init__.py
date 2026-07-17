"""Alembic 迁移目录（数据 PR-1）。

本包只承担 Alembic runtime 载入所需的 `__init__.py`；具体迁移脚本放在
`versions/` 目录，`env.py` 与 `script.py.mako` 位于本目录。

- `env.py`：Alembic 环境入口，`target_metadata` 指向 `app.db.base.metadata`；
  offline / online 双路径均从 `app.db.engine.get_database_url()` 现读 URL。
- `script.py.mako`：标准 Alembic 迁移模板。
- `versions/`：迁移脚本存放地（本 PR 空目录 + `.gitkeep`，供后续 PR 追加
  `0001_baseline.py` 或类似）。
- `0001_baseline.sql`：**空 baseline** SQL 参考（不由 Alembic 直接消费；
  仅作为"此时点数据库无任何表"事实的可读记录，供 review / 溯源）。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-1、
[[50 决策记录/决策 - ORM 与迁移工具选型]] 使用规范 §4（迁移文件命名与目录）。
"""
