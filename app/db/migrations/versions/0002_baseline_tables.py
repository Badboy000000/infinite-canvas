"""数据 PR-3：baseline tables — projects / provider_configs / prompt / workflow
/ asset / canvas 元数据 6 类对象 + 4 张子表建表。

Revision ID: 0002_baseline_tables
Revises: 0001_task_layer
Create Date: 2026-07-19

依据：
- [[40 实施计划/数据模型治理实施计划与PR清单]] PR-3。
- [[30 治理方案/数据模型治理方案]] 迁移策略阶段 2。
- [[50 决策记录/决策 - 主键类型]]：UUIDv7 + `legacy_id TEXT UNIQUE`；
  Provider 密钥字段**永不进 DB**。
- [[50 决策记录/决策 - ORM 与迁移工具选型]]：Alembic + `render_as_batch=True`。

**硬约束**：
- 6 类对象主表 + 3 张子表（prompt_items / asset_categories / asset_items），
  共 9 张业务表全部挂到 `app.db.base.metadata`。
- 每张表：主键 UUIDv7、`legacy_id TEXT UNIQUE NOT NULL`、`raw_json TEXT NULL`、
  `schema_version TEXT DEFAULT 'v1_legacy_json'`、`imported_at`+`created_at`
  +`updated_at`（`DateTime(timezone=True)`）。
- 显式命名 Index；`asset_items` 附带 `file_ref TEXT NULL`（文件对象专题接口预留）。
- Canvas 表本 PR **只建表**，不启用 shadow 双读、不切主写。

**明确不做**：
- 不建 Task / NodeRun / ProviderTask / History / Conversation 表（已由任务 PR-0 建 or
  留给 PR-12 / ISSUE-11）。
- 不建 User / Workspace / Membership 表（留给数据 PR-13）。
- 不建 FileObject / FileRef 表本体（留给文件对象专题；只在 AssetItem 内留
  `file_ref` 占位列）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import Uuid


# revision identifiers, used by Alembic.
revision: str = "0002_baseline_tables"
down_revision: Union[str, None] = "0001_task_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建立 9 张 baseline 业务表。"""
    # ------------------------------------------------------------------
    # projects
    # ------------------------------------------------------------------
    op.create_table(
        "projects",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("order_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_projects_legacy_id"),
    )
    op.create_index("ix_projects_legacy_id", "projects", ["legacy_id"])

    # ------------------------------------------------------------------
    # provider_configs
    # ------------------------------------------------------------------
    op.create_table(
        "provider_configs",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("protocol", sa.String(64), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("primary_flag", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("image_request_mode", sa.String(64), nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_provider_configs_legacy_id"),
    )
    op.create_index(
        "ix_provider_configs_legacy_id", "provider_configs", ["legacy_id"]
    )

    # ------------------------------------------------------------------
    # prompt_libraries
    # ------------------------------------------------------------------
    op.create_table(
        "prompt_libraries",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("scope", sa.String(64), nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_prompt_libraries_legacy_id"),
    )
    op.create_index(
        "ix_prompt_libraries_legacy_id", "prompt_libraries", ["legacy_id"]
    )

    # ------------------------------------------------------------------
    # prompt_items
    # ------------------------------------------------------------------
    op.create_table(
        "prompt_items",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column(
            "library_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("prompt_libraries.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("legacy_library_id", sa.Text, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_prompt_items_legacy_id"),
    )
    op.create_index("ix_prompt_items_library_id", "prompt_items", ["library_id"])
    op.create_index(
        "ix_prompt_items_legacy_library_id",
        "prompt_items",
        ["legacy_library_id"],
    )

    # ------------------------------------------------------------------
    # workflow_definitions
    # ------------------------------------------------------------------
    op.create_table(
        "workflow_definitions",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("provider_id", sa.String(128), nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column("legacy_path", sa.Text, nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "legacy_id", name="uq_workflow_definitions_legacy_id"
        ),
    )
    op.create_index(
        "ix_workflow_definitions_provider_id",
        "workflow_definitions",
        ["provider_id"],
    )
    op.create_index(
        "ix_workflow_definitions_legacy_id",
        "workflow_definitions",
        ["legacy_id"],
    )

    # ------------------------------------------------------------------
    # asset_libraries
    # ------------------------------------------------------------------
    op.create_table(
        "asset_libraries",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_asset_libraries_legacy_id"),
    )
    op.create_index(
        "ix_asset_libraries_legacy_id", "asset_libraries", ["legacy_id"]
    )

    # ------------------------------------------------------------------
    # asset_categories
    # ------------------------------------------------------------------
    op.create_table(
        "asset_categories",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column(
            "library_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("asset_libraries.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("legacy_library_id", sa.Text, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_asset_categories_legacy_id"),
    )
    op.create_index(
        "ix_asset_categories_library_id", "asset_categories", ["library_id"]
    )
    op.create_index(
        "ix_asset_categories_legacy_library_id",
        "asset_categories",
        ["legacy_library_id"],
    )

    # ------------------------------------------------------------------
    # asset_items  （附带 file_ref TEXT NULL 占位）
    # ------------------------------------------------------------------
    op.create_table(
        "asset_items",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column(
            "category_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("asset_categories.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("legacy_category_id", sa.Text, nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        # 文件对象专题接口预留占位（本 PR 不启用）
        sa.Column("file_ref", sa.Text, nullable=True),
        sa.Column("legacy_url", sa.Text, nullable=True),
        sa.Column("source_url", sa.Text, nullable=True),
        sa.Column("workspace_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("project_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_asset_items_legacy_id"),
    )
    op.create_index("ix_asset_items_category_id", "asset_items", ["category_id"])
    op.create_index(
        "ix_asset_items_legacy_category_id",
        "asset_items",
        ["legacy_category_id"],
    )
    op.create_index(
        "ix_asset_items_legacy_url", "asset_items", ["legacy_url"]
    )

    # ------------------------------------------------------------------
    # canvases
    # ------------------------------------------------------------------
    op.create_table(
        "canvases",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("legacy_id", sa.Text, nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(64), nullable=True),
        sa.Column("project_legacy_id", sa.Text, nullable=True),
        sa.Column("owner_label", sa.String(255), nullable=True),
        sa.Column("pinned", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("content_json", sa.Text, nullable=True),
        sa.Column("revision", sa.Integer, nullable=False, server_default="0"),
        sa.Column("base_updated_at", sa.Text, nullable=True),
        sa.Column("deleted_at", sa.Text, nullable=True),
        sa.Column("raw_json", sa.Text, nullable=True),
        sa.Column(
            "schema_version",
            sa.Text,
            nullable=False,
            server_default="v1_legacy_json",
        ),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("legacy_id", name="uq_canvases_legacy_id"),
    )
    op.create_index("ix_canvases_legacy_id", "canvases", ["legacy_id"])
    op.create_index(
        "ix_canvases_project_legacy_id", "canvases", ["project_legacy_id"]
    )


def downgrade() -> None:
    """按外键依赖倒序 drop。"""
    op.drop_index("ix_canvases_project_legacy_id", table_name="canvases")
    op.drop_index("ix_canvases_legacy_id", table_name="canvases")
    op.drop_table("canvases")

    op.drop_index("ix_asset_items_legacy_url", table_name="asset_items")
    op.drop_index(
        "ix_asset_items_legacy_category_id", table_name="asset_items"
    )
    op.drop_index("ix_asset_items_category_id", table_name="asset_items")
    op.drop_table("asset_items")

    op.drop_index(
        "ix_asset_categories_legacy_library_id", table_name="asset_categories"
    )
    op.drop_index(
        "ix_asset_categories_library_id", table_name="asset_categories"
    )
    op.drop_table("asset_categories")

    op.drop_index(
        "ix_asset_libraries_legacy_id", table_name="asset_libraries"
    )
    op.drop_table("asset_libraries")

    op.drop_index(
        "ix_workflow_definitions_legacy_id", table_name="workflow_definitions"
    )
    op.drop_index(
        "ix_workflow_definitions_provider_id",
        table_name="workflow_definitions",
    )
    op.drop_table("workflow_definitions")

    op.drop_index(
        "ix_prompt_items_legacy_library_id", table_name="prompt_items"
    )
    op.drop_index("ix_prompt_items_library_id", table_name="prompt_items")
    op.drop_table("prompt_items")

    op.drop_index(
        "ix_prompt_libraries_legacy_id", table_name="prompt_libraries"
    )
    op.drop_table("prompt_libraries")

    op.drop_index(
        "ix_provider_configs_legacy_id", table_name="provider_configs"
    )
    op.drop_table("provider_configs")

    op.drop_index("ix_projects_legacy_id", table_name="projects")
    op.drop_table("projects")
