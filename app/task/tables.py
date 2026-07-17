"""`app.task.tables` — Task 层 SQLAlchemy `Table` 定义。

**硬约束**：本模块中所有 `Table` 都必须挂到 `from app.db.base import metadata`
单例上（禁自建 `MetaData()`）；否则 Alembic `autogenerate` 与 `env.py`
`target_metadata` 感知不到 schema drift。

设计要点：

- 主键类型（[[50 决策记录/决策 - 主键类型]]）：
  - `tasks / node_runs / provider_tasks / artifacts` 主键 UUID（SQLite
    `CHAR(36)`，PostgreSQL 原生 `uuid`）。
  - **`task_events` 主键破例 `BIGINT AUTOINCREMENT`**（append-only 事件流
    唯一破例；理由见决策 §"允许自增 INTEGER 的破例场景"）。
- 时间戳：`DateTime(timezone=True)`；治理期 SQLite 走 ISO 字符串，
  PostgreSQL 走 `timestamptz`。
- JSON 列：`JSON`；PostgreSQL 侧未来通过 `with_variant(JSONB, "postgresql")`
  升级——本 PR 治理期只用 `JSON` 通用类型（业务无 partial update 需求）。
- 索引：至少覆盖 §PR-0 明确的 4 类：
  - `tasks(status, updated_at)` —— worker 拉取 + 恢复扫描
  - `tasks(idempotency_key)` —— 幂等键唯一性
  - `tasks(canvas_id, node_id)` —— 前端节点视图
  - `provider_tasks(provider_id, upstream_task_id)` —— 上游任务回查

详见 [[40 实施计划/任务模型与后台任务治理实施计划与PR清单]] PR-0、
[[30 治理方案/任务模型与后台任务治理方案]] §"目标对象"。
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
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

# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------

tasks = Table(
    "tasks",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column("task_type", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("priority", Integer, nullable=False, server_default="0"),
    Column("idempotency_key", String(255), nullable=True),
    Column("cancel_requested", Boolean, nullable=False, server_default="0"),
    Column("owner_user_id", Uuid(as_uuid=True), nullable=True),
    Column("workspace_id", Uuid(as_uuid=True), nullable=True),
    Column("project_id", Uuid(as_uuid=True), nullable=True),
    Column("canvas_id", String(255), nullable=True),
    Column("node_id", String(255), nullable=True),
    Column("node_run_id", Uuid(as_uuid=True), nullable=True),
    Column("provider_id", String(128), nullable=True),
    Column("model", String(128), nullable=True),
    Column("workflow_id", String(255), nullable=True),
    Column("input_snapshot", JSON, nullable=False),
    Column("output_refs", JSON, nullable=False),
    Column("attempt", Integer, nullable=False, server_default="0"),
    Column("max_attempts", Integer, nullable=False, server_default="1"),
    Column("retry_after", DateTime(timezone=True), nullable=True),
    Column("lease_owner", String(128), nullable=True),
    Column("lease_until", DateTime(timezone=True), nullable=True),
    Column("heartbeat_at", DateTime(timezone=True), nullable=True),
    Column("deadline_at", DateTime(timezone=True), nullable=True),
    Column("timeout_policy", JSON, nullable=False),
    Column("error_code", String(128), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("error_category", String(64), nullable=True),
    Column("cost_estimate", Float, nullable=True),
    Column("cost_actual", Float, nullable=True),
    Column("quota_bucket", String(128), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("queued_at", DateTime(timezone=True), nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("schema_version", String(32), nullable=False, server_default="v1"),
    # PR-0 §"索引至少覆盖" 前 3 类
    Index("ix_tasks_status_updated_at", "status", "updated_at"),
    Index("ix_tasks_canvas_node", "canvas_id", "node_id"),
    UniqueConstraint("idempotency_key", name="uq_tasks_idempotency_key"),
)


# ---------------------------------------------------------------------------
# node_runs
# ---------------------------------------------------------------------------

node_runs = Table(
    "node_runs",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column("canvas_id", String(255), nullable=False),
    Column("node_id", String(255), nullable=False),
    Column("node_type", String(128), nullable=False),
    Column("source_node_id", String(255), nullable=True),
    Column("run_kind", String(64), nullable=False, server_default="generation"),
    Column("status", String(32), nullable=False),
    Column("trigger_source", String(64), nullable=True),
    Column("input_snapshot", JSON, nullable=False),
    Column("settings_snapshot", JSON, nullable=False),
    Column("dependency_snapshot", JSON, nullable=False),
    Column("task_ids", JSON, nullable=False),
    Column("output_refs", JSON, nullable=False),
    Column("parent_run_id", Uuid(as_uuid=True), nullable=True),
    Column("batch_key", String(255), nullable=True),
    Column("attempt", Integer, nullable=False, server_default="1"),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("elapsed_ms", Integer, nullable=True),
    Column("summary", Text, nullable=True),
    Column("error", JSON, nullable=True),
    Column("workspace_id", Uuid(as_uuid=True), nullable=True),
    Column("project_id", Uuid(as_uuid=True), nullable=True),
    Column("owner_user_id", Uuid(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("schema_version", String(32), nullable=False, server_default="v1"),
    Index("ix_node_runs_canvas_node", "canvas_id", "node_id"),
    Index("ix_node_runs_status_updated_at", "status", "updated_at"),
)


# ---------------------------------------------------------------------------
# provider_tasks
# ---------------------------------------------------------------------------

provider_tasks = Table(
    "provider_tasks",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column(
        "task_id",
        Uuid(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("provider_id", String(128), nullable=False),
    Column("provider_protocol", String(64), nullable=False),
    Column("capability", String(64), nullable=True),
    Column("operation", String(64), nullable=True),
    Column("upstream_task_id", String(255), nullable=True),
    Column("upstream_task_kind", String(64), nullable=True),
    Column("remote_status", String(64), nullable=True),
    Column("status", String(32), nullable=False),
    Column("progress", Float, nullable=True),
    Column("poll_after", DateTime(timezone=True), nullable=True),
    Column("poll_count", Integer, nullable=False, server_default="0"),
    Column("last_poll_at", DateTime(timezone=True), nullable=True),
    Column("outputs", JSON, nullable=False),
    Column("error", JSON, nullable=True),
    Column("raw_excerpt", Text, nullable=True),
    Column("query_params", JSON, nullable=False),
    Column("adapter_kind", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("schema_version", String(32), nullable=False, server_default="v1"),
    Index("ix_provider_tasks_task_id", "task_id"),
    Index(
        "ix_provider_tasks_provider_upstream",
        "provider_id",
        "upstream_task_id",
    ),
)


# ---------------------------------------------------------------------------
# task_events —— 主键破例 BIGINT AUTOINCREMENT
# ---------------------------------------------------------------------------

task_events = Table(
    "task_events",
    metadata,
    # 破例 BIGINT AUTOINCREMENT（决策 - 主键类型 §7）。
    # SQLite 侧通过 `with_variant(Integer, "sqlite")` 让 `INTEGER PRIMARY KEY`
    # 走 ROWID 快路径（SQLite 仅 `INTEGER` 类型支持自增）；PostgreSQL 侧
    # 使用 `BigInteger` 生成 `BIGINT GENERATED ALWAYS AS IDENTITY`。
    Column(
        "id",
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        nullable=False,
    ),
    Column(
        "task_id",
        Uuid(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("seq", BigInteger, nullable=False),  # 应用层单调事件号（同 task 内 1-based）
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("payload_json", JSON, nullable=False),
    Column("schema_version", String(32), nullable=False, server_default="v1"),
    Index("ix_task_events_task_id_seq", "task_id", "seq"),
    UniqueConstraint("task_id", "seq", name="uq_task_events_task_id_seq"),
    CheckConstraint("seq >= 1", name="ck_task_events_seq_positive"),
)


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------

artifacts = Table(
    "artifacts",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
    Column(
        "task_id",
        Uuid(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "node_run_id",
        Uuid(as_uuid=True),
        ForeignKey("node_runs.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "provider_task_id",
        Uuid(as_uuid=True),
        ForeignKey("provider_tasks.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("kind", String(64), nullable=False),
    Column("url", String(1024), nullable=True),
    Column("file_object_id", Uuid(as_uuid=True), nullable=True),
    Column("legacy_url", String(1024), nullable=True),
    Column("mime_type", String(128), nullable=True),
    Column("name", String(255), nullable=True),
    Column("width", Integer, nullable=True),
    Column("height", Integer, nullable=True),
    Column("duration", Float, nullable=True),
    Column("size", BigInteger, nullable=True),
    Column("sha256", String(64), nullable=True),
    Column("node_id", String(255), nullable=True),
    Column("output_key", String(255), nullable=True),
    Column("role", String(64), nullable=True),
    Column("workspace_id", Uuid(as_uuid=True), nullable=True),
    Column("project_id", Uuid(as_uuid=True), nullable=True),
    Column("owner_user_id", Uuid(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("schema_version", String(32), nullable=False, server_default="v1"),
    Index("ix_artifacts_task_id", "task_id"),
    Index("ix_artifacts_node_run_id", "node_run_id"),
)


#: 本 PR 引入的五张表名（供测试断言使用）。
TASK_LAYER_TABLE_NAMES = (
    "tasks",
    "node_runs",
    "provider_tasks",
    "task_events",
    "artifacts",
)


__all__ = [
    "tasks",
    "node_runs",
    "provider_tasks",
    "task_events",
    "artifacts",
    "TASK_LAYER_TABLE_NAMES",
]
