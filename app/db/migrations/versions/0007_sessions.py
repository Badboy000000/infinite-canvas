"""权限 PR-3：auth_credentials + sessions 表 DDL。

Revision ID: 0007_sessions
Revises: 0006_identity
Create Date: 2026-07-24

依据：
- [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-3
- [[50 决策记录/决策 - 认证栈选型]] §1 密码存储 argon2id + §2 opaque server session

**硬约束（本 PR）**：
- 2 张新表（auth_credentials / sessions）通过 `op.create_table` 落 DDL；
  不新建 ORM 模型类（走 SQLAlchemy Core Table 定义 · 见 app/services/auth/tables.py）。
- 所有新表**不承载任何明文密钥**（P0 密钥零入库防线）；
  password_hash 是 argon2id 哈希、session_id 是 UUID4 opaque token。
- `username` 作为 auth_credentials 幂等键（UNIQUE）。
- downgrade 时按依赖倒序 drop（sessions 依赖 user；auth_credentials 依赖 user）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0007_sessions"
down_revision: Union[str, None] = "0006_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建立 auth_credentials 与 sessions 两张表。"""

    # ------------------------------------------------------------------
    # auth_credentials 表
    # ------------------------------------------------------------------
    op.create_table(
        "auth_credentials",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("must_change_password", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("username", name="uq_auth_credentials_username"),
    )

    # ------------------------------------------------------------------
    # sessions 表
    # ------------------------------------------------------------------
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    """按依赖倒序 drop 索引与表。"""
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("auth_credentials")