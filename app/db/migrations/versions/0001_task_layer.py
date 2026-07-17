"""任务 PR-0：Task / NodeRun / ProviderTask / TaskEvent / Artifact 表结构。

Revision ID: 0001_task_layer
Revises: (无前置迁移，首个真 Alembic revision)
Create Date: 2026-07-17

依据：
- [[40 实施计划/任务模型与后台任务治理实施计划与PR清单]] PR-0。
- [[30 治理方案/任务模型与后台任务治理方案]] §"目标对象"。
- [[50 决策记录/决策 - 主键类型]]：Task/NodeRun/ProviderTask/Artifact 主键
  `UUID`；TaskEvent 破例 `BIGINT AUTOINCREMENT`。
- [[50 决策记录/决策 - ORM 与迁移工具选型]]：Alembic + `render_as_batch=True`。

**硬约束**：本迁移**不引入** worker loop、影子登记、生成路径接入；只落 5 张
业务表 + 4 类索引；下游 PR 才会消费这些表。

索引至少覆盖（§PR-0 契约）：
- `tasks(status, updated_at)` —— worker 拉取 + 恢复扫描。
- `tasks(idempotency_key)` UNIQUE —— 幂等键唯一性。
- `tasks(canvas_id, node_id)` —— 前端节点视图。
- `provider_tasks(provider_id, upstream_task_id)` —— 上游任务回查。

以及若干辅助索引（`node_runs / task_events / artifacts` 上）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.types import Uuid

# revision identifiers, used by Alembic.
revision: str = "0001_task_layer"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """建立 5 张业务表。所有 Column 类型与 `app/task/tables.py` 定义等价。"""
    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    op.create_table(
        "tasks",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("owner_user_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("workspace_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("project_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("canvas_id", sa.String(255), nullable=True),
        sa.Column("node_id", sa.String(255), nullable=True),
        sa.Column("node_run_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("provider_id", sa.String(128), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("workflow_id", sa.String(255), nullable=True),
        sa.Column("input_snapshot", sa.JSON, nullable=False),
        sa.Column("output_refs", sa.JSON, nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_policy", sa.JSON, nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("error_category", sa.String(64), nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("cost_actual", sa.Float, nullable=True),
        sa.Column("quota_bucket", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="v1"),
        sa.UniqueConstraint("idempotency_key", name="uq_tasks_idempotency_key"),
    )
    op.create_index(
        "ix_tasks_status_updated_at", "tasks", ["status", "updated_at"]
    )
    op.create_index(
        "ix_tasks_canvas_node", "tasks", ["canvas_id", "node_id"]
    )

    # ------------------------------------------------------------------
    # node_runs
    # ------------------------------------------------------------------
    op.create_table(
        "node_runs",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("canvas_id", sa.String(255), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(128), nullable=False),
        sa.Column("source_node_id", sa.String(255), nullable=True),
        sa.Column("run_kind", sa.String(64), nullable=False, server_default="generation"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger_source", sa.String(64), nullable=True),
        sa.Column("input_snapshot", sa.JSON, nullable=False),
        sa.Column("settings_snapshot", sa.JSON, nullable=False),
        sa.Column("dependency_snapshot", sa.JSON, nullable=False),
        sa.Column("task_ids", sa.JSON, nullable=False),
        sa.Column("output_refs", sa.JSON, nullable=False),
        sa.Column("parent_run_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("batch_key", sa.String(255), nullable=True),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_ms", sa.Integer, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("error", sa.JSON, nullable=True),
        sa.Column("workspace_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("project_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("owner_user_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="v1"),
    )
    op.create_index(
        "ix_node_runs_canvas_node", "node_runs", ["canvas_id", "node_id"]
    )
    op.create_index(
        "ix_node_runs_status_updated_at", "node_runs", ["status", "updated_at"]
    )

    # ------------------------------------------------------------------
    # provider_tasks
    # ------------------------------------------------------------------
    op.create_table(
        "provider_tasks",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "task_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("provider_protocol", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(64), nullable=True),
        sa.Column("operation", sa.String(64), nullable=True),
        sa.Column("upstream_task_id", sa.String(255), nullable=True),
        sa.Column("upstream_task_kind", sa.String(64), nullable=True),
        sa.Column("remote_status", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("progress", sa.Float, nullable=True),
        sa.Column("poll_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("poll_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outputs", sa.JSON, nullable=False),
        sa.Column("error", sa.JSON, nullable=True),
        sa.Column("raw_excerpt", sa.Text, nullable=True),
        sa.Column("query_params", sa.JSON, nullable=False),
        sa.Column("adapter_kind", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="v1"),
    )
    op.create_index(
        "ix_provider_tasks_task_id", "provider_tasks", ["task_id"]
    )
    op.create_index(
        "ix_provider_tasks_provider_upstream",
        "provider_tasks",
        ["provider_id", "upstream_task_id"],
    )

    # ------------------------------------------------------------------
    # task_events —— 主键破例 BIGINT AUTOINCREMENT
    # ------------------------------------------------------------------
    op.create_table(
        "task_events",
        sa.Column(
            "id",
            # 破例 BIGINT AUTOINCREMENT（决策 - 主键类型 §7）；
            # SQLite 通过 `with_variant(Integer, "sqlite")` 走 ROWID 快路径
            # （SQLite 仅 INTEGER 支持自增）。
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column(
            "task_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON, nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="v1"),
        sa.UniqueConstraint("task_id", "seq", name="uq_task_events_task_id_seq"),
        sa.CheckConstraint("seq >= 1", name="ck_task_events_seq_positive"),
    )
    op.create_index(
        "ix_task_events_task_id_seq", "task_events", ["task_id", "seq"]
    )

    # ------------------------------------------------------------------
    # artifacts
    # ------------------------------------------------------------------
    op.create_table(
        "artifacts",
        sa.Column("id", Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "task_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "node_run_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("node_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "provider_task_id",
            Uuid(as_uuid=True),
            sa.ForeignKey("provider_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("file_object_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("legacy_url", sa.String(1024), nullable=True),
        sa.Column("mime_type", sa.String(128), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("duration", sa.Float, nullable=True),
        sa.Column("size", sa.BigInteger, nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("node_id", sa.String(255), nullable=True),
        sa.Column("output_key", sa.String(255), nullable=True),
        sa.Column("role", sa.String(64), nullable=True),
        sa.Column("workspace_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("project_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("owner_user_id", Uuid(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False, server_default="v1"),
    )
    op.create_index("ix_artifacts_task_id", "artifacts", ["task_id"])
    op.create_index("ix_artifacts_node_run_id", "artifacts", ["node_run_id"])


def downgrade() -> None:
    """按外键依赖倒序 drop。"""
    op.drop_index("ix_artifacts_node_run_id", table_name="artifacts")
    op.drop_index("ix_artifacts_task_id", table_name="artifacts")
    op.drop_table("artifacts")

    op.drop_index("ix_task_events_task_id_seq", table_name="task_events")
    op.drop_table("task_events")

    op.drop_index(
        "ix_provider_tasks_provider_upstream", table_name="provider_tasks"
    )
    op.drop_index("ix_provider_tasks_task_id", table_name="provider_tasks")
    op.drop_table("provider_tasks")

    op.drop_index(
        "ix_node_runs_status_updated_at", table_name="node_runs"
    )
    op.drop_index("ix_node_runs_canvas_node", table_name="node_runs")
    op.drop_table("node_runs")

    op.drop_index("ix_tasks_canvas_node", table_name="tasks")
    op.drop_index("ix_tasks_status_updated_at", table_name="tasks")
    op.drop_table("tasks")
