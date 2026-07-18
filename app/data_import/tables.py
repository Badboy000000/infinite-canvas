"""`app.data_import.tables` — 数据 PR-3 baseline tables 定义。

6 类对象（6 张主表 + 4 张子表）：

- `projects`
- `provider_configs`  （**不含密钥** —— 白名单字段 + `raw_json`）
- `prompt_libraries` / `prompt_items`
- `workflow_definitions`
- `asset_libraries` / `asset_categories` / `asset_items`
  - `asset_items` 附带 `file_ref TEXT NULL`（文件对象专题接口预留占位，
    本 PR 不启用；参见 [[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]]）
- `canvases`（元数据 + `content_json` + `revision` + `base_updated_at` + `deleted_at`）

**硬约束**：
- 全部 `Table` 挂到 `from app.db.base import metadata` 单例；禁自建 `MetaData()`。
- 主键统一 `Uuid(as_uuid=True) + default=app.shared.ids.generate_id`（决策 - 主键类型）。
- `legacy_id TEXT UNIQUE NOT NULL` 是幂等键。
- `raw_json TEXT NULL` 保留原始 JSON 字节（本 PR 允许空）。
- 显式命名 Index（复用 `app/db/base.py` naming convention）。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-3。
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import Uuid

from app.db.base import metadata
from app.shared.ids import generate_id


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

projects = Table(
    "projects",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column("name", String(255), nullable=True),
    Column("order_index", Integer, nullable=False, server_default="0"),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_projects_legacy_id"),
    Index("ix_projects_legacy_id", "legacy_id"),
)


# ---------------------------------------------------------------------------
# provider_configs  （不含密钥；仅白名单字段 + raw_json）
# ---------------------------------------------------------------------------

provider_configs = Table(
    "provider_configs",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column("name", String(255), nullable=True),
    Column("protocol", String(64), nullable=True),
    Column("base_url", String(512), nullable=True),
    Column("enabled", Boolean, nullable=False, server_default="1"),
    Column("primary_flag", Boolean, nullable=False, server_default="0"),
    Column("image_request_mode", String(64), nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_provider_configs_legacy_id"),
    Index("ix_provider_configs_legacy_id", "legacy_id"),
)


# ---------------------------------------------------------------------------
# prompt_libraries / prompt_items
# ---------------------------------------------------------------------------

prompt_libraries = Table(
    "prompt_libraries",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column("name", String(255), nullable=True),
    Column("scope", String(64), nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_prompt_libraries_legacy_id"),
    Index("ix_prompt_libraries_legacy_id", "legacy_id"),
)

prompt_items = Table(
    "prompt_items",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column(
        "library_id",
        Uuid(as_uuid=True),
        ForeignKey("prompt_libraries.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("legacy_library_id", Text, nullable=True),
    Column("name", String(255), nullable=True),
    Column("kind", String(64), nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_prompt_items_legacy_id"),
    Index("ix_prompt_items_library_id", "library_id"),
    Index("ix_prompt_items_legacy_library_id", "legacy_library_id"),
)


# ---------------------------------------------------------------------------
# workflow_definitions （只承接元数据；图本体仍在 `workflows/*.json`）
# ---------------------------------------------------------------------------

workflow_definitions = Table(
    "workflow_definitions",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column("name", String(255), nullable=True),
    Column("provider_id", String(128), nullable=True),
    Column("kind", String(64), nullable=True),
    Column("legacy_path", Text, nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_workflow_definitions_legacy_id"),
    Index("ix_workflow_definitions_provider_id", "provider_id"),
    Index("ix_workflow_definitions_legacy_id", "legacy_id"),
)


# ---------------------------------------------------------------------------
# asset_libraries / asset_categories / asset_items
# ---------------------------------------------------------------------------

asset_libraries = Table(
    "asset_libraries",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column("name", String(255), nullable=True),
    Column("kind", String(64), nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_asset_libraries_legacy_id"),
    Index("ix_asset_libraries_legacy_id", "legacy_id"),
)

asset_categories = Table(
    "asset_categories",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column(
        "library_id",
        Uuid(as_uuid=True),
        ForeignKey("asset_libraries.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("legacy_library_id", Text, nullable=True),
    Column("name", String(255), nullable=True),
    Column("kind", String(64), nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_asset_categories_legacy_id"),
    Index("ix_asset_categories_library_id", "library_id"),
    Index("ix_asset_categories_legacy_library_id", "legacy_library_id"),
)

asset_items = Table(
    "asset_items",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column(
        "category_id",
        Uuid(as_uuid=True),
        ForeignKey("asset_categories.id", ondelete="CASCADE"),
        nullable=True,
    ),
    Column("legacy_category_id", Text, nullable=True),
    Column("name", String(255), nullable=True),
    Column("kind", String(64), nullable=True),
    # 文件对象专题接口预留占位（本 PR 不启用；只留列）
    Column("file_ref", Text, nullable=True),
    Column("legacy_url", Text, nullable=True),
    Column("source_url", Text, nullable=True),
    Column("workspace_id", Uuid(as_uuid=True), nullable=True),
    Column("project_id", Uuid(as_uuid=True), nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_asset_items_legacy_id"),
    Index("ix_asset_items_category_id", "category_id"),
    Index("ix_asset_items_legacy_category_id", "legacy_category_id"),
    Index("ix_asset_items_legacy_url", "legacy_url"),
)


# ---------------------------------------------------------------------------
# canvases  （元数据 + content_json；本 PR 只建表，不启用 shadow 双读）
# ---------------------------------------------------------------------------

canvases = Table(
    "canvases",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, default=generate_id),
    Column("legacy_id", Text, nullable=False),
    Column("title", String(255), nullable=True),
    Column("kind", String(64), nullable=True),
    Column("project_legacy_id", Text, nullable=True),
    Column("owner_label", String(255), nullable=True),
    Column("pinned", Boolean, nullable=False, server_default="0"),
    Column("content_json", Text, nullable=True),
    Column("revision", Integer, nullable=False, server_default="0"),
    Column("base_updated_at", Text, nullable=True),
    Column("deleted_at", Text, nullable=True),
    Column("raw_json", Text, nullable=True),
    Column("schema_version", Text, nullable=False, server_default="v1_legacy_json"),
    Column("imported_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("legacy_id", name="uq_canvases_legacy_id"),
    Index("ix_canvases_legacy_id", "legacy_id"),
    Index("ix_canvases_project_legacy_id", "project_legacy_id"),
)


BASELINE_TABLE_NAMES = (
    "projects",
    "provider_configs",
    "prompt_libraries",
    "prompt_items",
    "workflow_definitions",
    "asset_libraries",
    "asset_categories",
    "asset_items",
    "canvases",
)


__all__ = [
    "projects",
    "provider_configs",
    "prompt_libraries",
    "prompt_items",
    "workflow_definitions",
    "asset_libraries",
    "asset_categories",
    "asset_items",
    "canvases",
    "BASELINE_TABLE_NAMES",
]
