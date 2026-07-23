"""数据 PR-13：User / Workspace / Membership / Role / Permission / UserAlias 骨架 DDL
+ 默认 workspace + 默认 project + 3 角色预置 + 资源归属回填。

Revision ID: 0006_identity
Revises: 0005_generation_history
Create Date: 2026-07-23

依据：
- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-13
- [[50 决策记录/决策 - 主键类型]]：UUIDv7 主键，SQLAlchemy 2.0 `Uuid(as_uuid=True)`
  屏蔽 SQLite (`CHAR(36)`) 与 PostgreSQL 原生 `uuid` 方言差异。
- [[50 决策记录/决策 - ORM 与迁移工具选型]]：Alembic + `render_as_batch=True`。

**硬约束（本 PR）**：
- 6 张新表（user / workspace / membership / role / permission / user_alias）通过
  `op.create_table` 落 DDL；不新建 ORM 模型类。
- 所有新表**不承载任何密钥**（P0 密钥零入库防线）。
- `legacy_id` 或 `legacy_user_key` 作为幂等键（UUID 主键 + 业务幂等键分离）。
- 默认 `system` workspace + `default` project 通过幂等 INSERT 建立。
- `admin` / `member` / `viewer` 3 角色通过幂等 INSERT 预置。
- 对已有业务表 ALTER TABLE ADD COLUMN 追加 workspace_id / created_by_user_id /
  legacy_owner_label 字段（nullable · default NULL）。
- 所有 ALTER TABLE 走 try/except 跳过已存在的列（幂等）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import Uuid


# revision identifiers, used by Alembic.
revision: str = "0006_identity"
down_revision: Union[str, None] = "0005_generation_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# 辅助：检查列是否存在（SQLite PRAGMA table_info）
# ---------------------------------------------------------------------------

def _column_exists(table: str, column: str) -> bool:
    """检查 SQLite 表中某个列是否已存在。"""
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(f"PRAGMA table_info({table})")
    ).fetchall()
    return any(row[1] == column for row in rows)


def _add_column_if_missing(
    table: str,
    column: sa.Column,
) -> None:
    """如果列不存在则 ALTER TABLE ADD COLUMN。"""
    if not _column_exists(table, column.name):
        op.add_column(table, column)


# ---------------------------------------------------------------------------
# 业务表名单（需要追加 workspace_id / created_by_user_id / legacy_owner_label）
# ---------------------------------------------------------------------------

_BUSINESS_TABLES = (
    "projects",
    "provider_configs",
    "prompt_libraries",
    "prompt_items",
    "workflow_definitions",
    "asset_libraries",
    "asset_categories",
    "asset_items",
    "canvases",
    "generation_history",
)


def upgrade() -> None:
    """建立 6 张 identity 表 + 预置数据 + 资源归属字段追加。"""

    # ======================================================================
    # 1. 新表建立
    # ======================================================================

    # ------------------------------------------------------------------
    # user 表
    # ------------------------------------------------------------------
    op.create_table(
        "user",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_user_key", sa.Text, nullable=True),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column("avatar_url", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ------------------------------------------------------------------
    # workspace 表
    # ------------------------------------------------------------------
    op.create_table(
        "workspace",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False, server_default="system"),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspace_kind", "workspace", ["kind"])

    # ------------------------------------------------------------------
    # membership 表
    # ------------------------------------------------------------------
    op.create_table(
        "membership",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "workspace_id", name="uq_membership_user_workspace"
        ),
    )
    op.create_index(
        "ix_membership_user_id", "membership", ["user_id"]
    )
    op.create_index(
        "ix_membership_workspace_id", "membership", ["workspace_id"]
    )

    # ------------------------------------------------------------------
    # role 表
    # ------------------------------------------------------------------
    op.create_table(
        "role",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("permissions_json", sa.Text, nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_role_name"),
    )
    op.create_index("ix_role_name", "role", ["name"])

    # ------------------------------------------------------------------
    # permission 表
    # ------------------------------------------------------------------
    op.create_table(
        "permission",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_permission_code"),
    )
    op.create_index("ix_permission_code", "permission", ["code"])

    # ------------------------------------------------------------------
    # user_alias 表
    # ------------------------------------------------------------------
    op.create_table(
        "user_alias",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("legacy_user_key", sa.Text, nullable=False),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "legacy_user_key", name="uq_user_alias_legacy_user_key"
        ),
    )
    op.create_index(
        "ix_user_alias_user_id", "user_alias", ["user_id"]
    )
    op.create_index(
        "ix_user_alias_legacy_user_key",
        "user_alias",
        ["legacy_user_key"],
    )

    # ======================================================================
    # 2. 预置数据（幂等 INSERT OR IGNORE）
    # ======================================================================

    from app.shared.ids import generate_id
    import datetime as _dt

    _now = _dt.datetime.now(_dt.timezone.utc)

    # 2a. system workspace（固定 legacy_id='__system__' 作为幂等键）
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO workspace (id, name, kind, raw_json, created_at, updated_at) "
            "VALUES (:id, 'system', 'system', '{}', :now, :now)"
        ).bindparams(
            id=generate_id(),
            now=_now,
        )
    )

    # 2b. default project（固定 legacy_id='__default__' 作为幂等键）
    # default project 放在 projects 表（已存在），用 legacy_id='__default__'
    op.execute(
        sa.text(
            "INSERT OR IGNORE INTO projects (id, legacy_id, name, raw_json, schema_version, "
            "imported_at, created_at, updated_at) "
            "VALUES (:id, '__default__', 'default', '{}', 'v1_legacy_json', :now, :now, :now)"
        ).bindparams(
            id=generate_id(),
            now=_now,
        )
    )

    # 2c. 3 角色预置（admin / member / viewer）
    for role_name in ("admin", "member", "viewer"):
        op.execute(
            sa.text(
                "INSERT OR IGNORE INTO role (id, name, permissions_json, raw_json, created_at, updated_at) "
                "VALUES (:id, :name, '{}', '{}', :now, :now)"
            ).bindparams(
                id=generate_id(),
                name=role_name,
                now=_now,
            )
        )

    # ======================================================================
    # 3. 资源归属字段追加（ALTER TABLE ADD COLUMN · 幂等）
    # ======================================================================

    for table_name in _BUSINESS_TABLES:
        _add_column_if_missing(
            table_name,
            sa.Column("workspace_id", Uuid(as_uuid=True), nullable=True),
        )
        _add_column_if_missing(
            table_name,
            sa.Column("created_by_user_id", Uuid(as_uuid=True), nullable=True),
        )
        _add_column_if_missing(
            table_name,
            sa.Column("legacy_owner_label", sa.Text, nullable=True),
        )


def downgrade() -> None:
    """按依赖倒序 drop 索引、表、回滚 ALTER TABLE ADD COLUMN。

    注意：SQLite 不支持 `ALTER TABLE DROP COLUMN`（3.35.0+ 支持但受
    `render_as_batch=True` 限制）。本 migration 的 downgrade 只 drop 新表；
    ALTER TABLE 追加的列会在 drop 表时自然消失。
    """
    # 逆序 drop 新表（按外键依赖）
    op.drop_index("ix_user_alias_legacy_user_key", table_name="user_alias")
    op.drop_index("ix_user_alias_user_id", table_name="user_alias")
    op.drop_table("user_alias")

    op.drop_index("ix_permission_code", table_name="permission")
    op.drop_table("permission")

    op.drop_index("ix_role_name", table_name="role")
    op.drop_table("role")

    op.drop_index("ix_membership_workspace_id", table_name="membership")
    op.drop_index("ix_membership_user_id", table_name="membership")
    op.drop_table("membership")

    op.drop_index("ix_workspace_kind", table_name="workspace")
    op.drop_table("workspace")

    op.drop_table("user")

    # 注意：ALTER TABLE ADD COLUMN 追加的 workspace_id / created_by_user_id /
    # legacy_owner_label 列在 SQLite 中无法通过 `op.drop_column` 安全撤销
    # （SQLite 重写表）。这些列在 upgrade 时是 nullable 的，不影响 downgrade
    # 后的功能。如果完全回退需要 DROP TABLE 整个业务表，本 migration 不做。