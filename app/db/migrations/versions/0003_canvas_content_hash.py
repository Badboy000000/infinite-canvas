"""数据 PR-6：Canvas `content_hash` 列。

Revision ID: 0003_canvas_content_hash
Revises: 0002_baseline_tables
Create Date: 2026-07-19

依据：
- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-6。
- [[60 讨论记录/2026-07-19 Wave 3-E-数据 PR-6 开工/2026-07-19 Wave 3-E-数据 PR-6
   开工协调纲要]] §改动范围 1（关键事实校正：`content_json` 语义已在数据 PR-3
   落地为"raw JSON 完整字符串"；本 PR 采用方案 B —— 保 raw JSON 语义不变、
   新增独立 `content_hash TEXT` 列存 `sha256(content_json)`，短窗双写与对账
   工具据此比较字节等价性）。
- [[50 决策记录/决策 - ORM 与迁移工具选型]]：Alembic + `render_as_batch=True`；
   SQLite `ADD COLUMN` / `DROP COLUMN` 需通过 `op.batch_alter_table` 实现
   downgrade。

**硬约束**：
- 仅追加 `content_hash TEXT NULL` 一列，不改任何既有列。
- 保持 `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head`
  三次干净往返（SQLite 场景走 `batch_alter_table`）。
- 数据 PR-3 的 `content_json` 语义不变。
- 不涉及 Provider 凭据；`content_hash` 仅为 `sha256(content_json)` 摘要。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_canvas_content_hash"
down_revision: Union[str, None] = "0002_baseline_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Append `content_hash TEXT NULL` to `canvases`。

    SQLite 原生 `ALTER TABLE ... ADD COLUMN` 已支持 NULL 列；使用
    `op.batch_alter_table` 是为了 downgrade 走同一 recreate 路径保持对称。
    """
    with op.batch_alter_table("canvases", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("content_hash", sa.Text, nullable=True))


def downgrade() -> None:
    """Drop `content_hash` column from `canvases`。

    SQLite 原生不支持 `DROP COLUMN`；`op.batch_alter_table` 会通过 create
    new table + copy data + rename 的方式安全回滚。
    """
    with op.batch_alter_table("canvases", recreate="auto") as batch_op:
        batch_op.drop_column("content_hash")
