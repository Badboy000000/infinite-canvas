"""数据 PR-18：FileObject / FileRef / LegacyUrlRef 首版 DDL。

Revision ID: 0004_file_object_ddl
Revises: 0003_canvas_content_hash
Create Date: 2026-07-23

**编号订正(Lead 拍板候选 B · 2026-07-23)**:
- 原分配 revision id = `0003_file_object_ddl` / down_revision = `0002_baseline_tables`;
  发现仓库已存在 `0003_canvas_content_hash`(数据 PR-6 · `5a215ce`)占用同一
  parent → Alembic 多头。Lead 拍板订正为 `0004_file_object_ddl` +
  down_revision = `0003_canvas_content_hash`;3 张表 DDL / T135-T144 断言全部
  逐字保留,零实质变更。承接 CB-P5-19 治理机制补丁(Wave 3-N.2)。

依据：
- [[30 治理方案/数据模型治理方案]] § FileObject / FileRef / LegacyUrlRef（L339-363）。
- [[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-3 字段清单（L221）。
- [[50 决策记录/决策 - 主键类型]]：UUIDv7 主键，SQLAlchemy 2.0 `Uuid(as_uuid=True)`
  屏蔽 SQLite (`CHAR(36)`) 与 PostgreSQL 原生 `uuid` 方言差异。
- [[50 决策记录/决策 - ORM 与迁移工具选型]]：Alembic + `render_as_batch=True`。

**硬约束（本 PR）**：
- 3 张新表全部通过 `op.create_table` 落 DDL；**不新建 ORM 模型类**，
  ORM 归后续 PR。
- **不显式**在 `app/db/base.py` 定义 `Table` 对象，与 `0002_baseline_tables`
  保持一致的"迁移即事实"设计。
- FK 语义（file_refs → file_objects `ON DELETE RESTRICT` /
  legacy_url_refs → file_objects `ON DELETE CASCADE`）**冻结**为本 PR 契约，
  后续 PR 不许在无治理决策的情况下反转方向。
- 不动 `asset_items.file_ref TEXT NULL` 占位列（数据 PR-3 baseline，
  留给文件专题后续 PR-10 迁引用；T144 零触碰断言）。

**本 PR 不做**：
- 不改 `FileService`、`data/file_index.json`、21 处 durable 挂钩点
  （文件 PR-2 `fed6963` 冻结）。
- 不切主写路径；FileService 继续走 shadow_register。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import Uuid


# revision identifiers, used by Alembic.
revision: str = "0004_file_object_ddl"
down_revision: Union[str, None] = "0003_canvas_content_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建立 file_objects / file_refs / legacy_url_refs 3 张表。"""
    # ------------------------------------------------------------------
    # file_objects
    # ------------------------------------------------------------------
    op.create_table(
        "file_objects",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("sha256", sa.LargeBinary(32), nullable=False),
        sa.Column("xxh64", sa.LargeBinary(8), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("mime_type", sa.Text, nullable=True),
        sa.Column(
            "storage_backend",
            sa.Text,
            nullable=False,
            server_default="local",
        ),
        sa.Column("bucket", sa.Text, nullable=True),
        sa.Column("object_key", sa.Text, nullable=False),
        sa.Column("etag", sa.Text, nullable=True),
        # origin_kind ∈ {upload, ai_output, library, preview,
        #                external_download, sidecar_txt, sidecar_class}
        # 治理期字面枚举由应用层校验；本 PR 不落 CHECK 约束以保持 SQLite/PG
        # 移植简单，未来若增补 origin_kind 由数据模型专题决议。
        sa.Column("origin_kind", sa.Text, nullable=False),
        sa.Column("owner_user_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("workspace_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("project_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reference_count",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_referenced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("legacy_path", sa.Text, nullable=True),
        sa.Column("legacy_url", sa.Text, nullable=True),
        sa.Column("import_batch_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("raw_meta", sa.Text, nullable=True),
        sa.Column("origin_metadata_sha", sa.LargeBinary(32), nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.UniqueConstraint("sha256", name="uq_file_objects_sha256"),
        sa.UniqueConstraint("legacy_path", name="uq_file_objects_legacy_path"),
    )
    # 显式命名的辅助索引（字段清单要求）。
    op.create_index(
        "idx_file_objects_sha256", "file_objects", ["sha256"]
    )
    op.create_index(
        "idx_file_objects_legacy_path", "file_objects", ["legacy_path"]
    )
    op.create_index(
        "idx_file_objects_workspace_project",
        "file_objects",
        ["workspace_id", "project_id"],
    )
    op.create_index(
        "idx_file_objects_origin_kind", "file_objects", ["origin_kind"]
    )
    op.create_index(
        "idx_file_objects_created_at", "file_objects", ["created_at"]
    )

    # ------------------------------------------------------------------
    # file_refs —— 业务对象引用 FileObject
    # ------------------------------------------------------------------
    op.create_table(
        "file_refs",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "file_id",
            Uuid(as_uuid=True),
            sa.ForeignKey(
                "file_objects.id",
                ondelete="RESTRICT",
                name="fk_file_refs_file_id_file_objects",
            ),
            nullable=False,
        ),
        # subject_table ∈ {canvas_nodes, asset_items, history, messages,
        #                  workflows, tasks}
        sa.Column("subject_table", sa.Text, nullable=False),
        sa.Column("subject_id", Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.Text,
            nullable=False,
            server_default="primary",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "subject_table",
            "subject_id",
            "role",
            "file_id",
            name="uq_file_refs_subject_role",
        ),
    )
    op.create_index("idx_file_refs_file_id", "file_refs", ["file_id"])
    op.create_index(
        "idx_file_refs_subject", "file_refs", ["subject_table", "subject_id"]
    )

    # ------------------------------------------------------------------
    # legacy_url_refs —— 旧 URL / 本地路径兼容层
    # ------------------------------------------------------------------
    op.create_table(
        "legacy_url_refs",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "file_id",
            Uuid(as_uuid=True),
            sa.ForeignKey(
                "file_objects.id",
                ondelete="CASCADE",
                name="fk_legacy_url_refs_file_id_file_objects",
            ),
            nullable=False,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("migrated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.LargeBinary(32), nullable=False),
        sa.UniqueConstraint("url", name="uq_legacy_url_refs_url"),
    )
    op.create_index(
        "idx_legacy_url_refs_file_id", "legacy_url_refs", ["file_id"]
    )
    op.create_index(
        "idx_legacy_url_refs_sha256", "legacy_url_refs", ["sha256"]
    )


def downgrade() -> None:
    """按外键依赖倒序 drop。"""
    op.drop_index(
        "idx_legacy_url_refs_sha256", table_name="legacy_url_refs"
    )
    op.drop_index(
        "idx_legacy_url_refs_file_id", table_name="legacy_url_refs"
    )
    op.drop_table("legacy_url_refs")

    op.drop_index("idx_file_refs_subject", table_name="file_refs")
    op.drop_index("idx_file_refs_file_id", table_name="file_refs")
    op.drop_table("file_refs")

    op.drop_index(
        "idx_file_objects_created_at", table_name="file_objects"
    )
    op.drop_index(
        "idx_file_objects_origin_kind", table_name="file_objects"
    )
    op.drop_index(
        "idx_file_objects_workspace_project", table_name="file_objects"
    )
    op.drop_index(
        "idx_file_objects_legacy_path", table_name="file_objects"
    )
    op.drop_index("idx_file_objects_sha256", table_name="file_objects")
    op.drop_table("file_objects")
