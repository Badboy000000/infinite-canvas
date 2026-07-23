"""数据 PR-12：GenerationHistory DDL（Wave 3-N.6 Batch 2 主线 B）。

Revision ID: 0005_generation_history
Revises: 0004_file_object_ddl
Create Date: 2026-07-23

依据：
- [[30 治理方案/数据模型治理方案]] § GenerationHistory
- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-12
- [[50 决策记录/决策 - 主键类型]]：UUIDv7 主键，SQLAlchemy 2.0 `Uuid(as_uuid=True)`
  屏蔽 SQLite (`CHAR(36)`) 与 PostgreSQL 原生 `uuid` 方言差异。
- [[50 决策记录/决策 - ORM 与迁移工具选型]]：Alembic + `render_as_batch=True`。

**硬约束（本 PR）**：
- 新表 `generation_history` 通过 `op.create_table` 落 DDL；不新建 ORM 模型类。
- `legacy_id TEXT UNIQUE NULL` 幂等键（PG 与 SQLite 均允许多个 NULL 共存 ·
  writer 侧总是提供合成键兜底 · 见 `app/db/history_writer.py`）。
- 保留 `canvas_id` / `node_id` / `task_id` / `user_key` 4 个诊断字段供运维
  查询；不加外键（治理期跨域 FK 谨慎 · 参照 CB-P5-19 教训 · file_refs
  ondelete 语义冻结不到 tasks 表）。
- 索引齐 4 项：`created_at`（倒序查询 · legacy JSON `history[:5000]` 语义
  对齐）· `canvas_id` · `task_id` · `user_key`。

**本 PR 不做**：
- 不切主写默认（`main.HISTORY_PRIMARY_WRITE` 默认 `"json"` · GM-22 反转独立 PR）。
- 不动 `main.save_to_history` / `main.HISTORY_LOCK`（P0 冻结区独立 pin）。
- 不动 `app/task/history/writer.py::HistoryWriter`（task 域独立子系统 ·
  TASK_HISTORY_ENABLE flag · 与本 domain 分离）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import Uuid


# revision identifiers, used by Alembic.
revision: str = "0005_generation_history"
down_revision: Union[str, None] = "0004_file_object_ddl"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建立 generation_history 表 + 4 个索引。"""
    op.create_table(
        "generation_history",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=True),
        sa.Column("user_key", sa.Text, nullable=True),
        sa.Column("canvas_id", sa.Text, nullable=True),
        sa.Column("node_id", sa.Text, nullable=True),
        sa.Column("task_id", sa.Text, nullable=True),
        sa.Column("output_ref", sa.Text, nullable=True),
        sa.Column("legacy_urls", sa.Text, nullable=True),
        sa.Column("prompt_summary", sa.Text, nullable=True),
        sa.Column("provider_id", sa.Text, nullable=True),
        sa.Column("model", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.UniqueConstraint("legacy_id", name="uq_generation_history_legacy_id"),
    )
    op.create_index(
        "ix_generation_history_created_at", "generation_history", ["created_at"]
    )
    op.create_index(
        "ix_generation_history_canvas_id", "generation_history", ["canvas_id"]
    )
    op.create_index(
        "ix_generation_history_task_id", "generation_history", ["task_id"]
    )
    op.create_index(
        "ix_generation_history_user_key", "generation_history", ["user_key"]
    )


def downgrade() -> None:
    """按依赖倒序 drop 索引与表。"""
    op.drop_index(
        "ix_generation_history_user_key", table_name="generation_history"
    )
    op.drop_index(
        "ix_generation_history_task_id", table_name="generation_history"
    )
    op.drop_index(
        "ix_generation_history_canvas_id", table_name="generation_history"
    )
    op.drop_index(
        "ix_generation_history_created_at", table_name="generation_history"
    )
    op.drop_table("generation_history")
