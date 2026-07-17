"""`app.task.store.sqlite_impl` — SQLite (via SQLAlchemy Core) Store 实现。

设计原则：

- 通过 `from app.db.session import get_session` 消费 Session；每个方法一次
  事务边界（`with get_session() as s: ...`）。
- 数据落 SQLAlchemy Core `Table` 定义（`app.task.tables`）；不使用 ORM
  声明式 typed class（决策 §7）。
- 与 Memory 实现共享同一份端口签名与语义。
- **本 PR 硬约束**：不引入 asyncio session；不消费 FastAPI DI；不接入现有
  生成路径。

调用前置：调用方须保证已 `run_migrations("head")`，即业务表已存在。测试
用 `sqlite:///:memory:` 或 tmpdir 时可用 `run_migrations` 或直接
`metadata.create_all(engine)` 建表。
"""

from __future__ import annotations

import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.task.contracts import (
    Artifact,
    ArtifactDraft,
    CasFailure,
    NodeRun,
    NodeRunDraft,
    ProviderTask,
    ProviderTaskDraft,
    RecoveryFilter,
    Task,
    TaskDraft,
    TaskEvent,
    TaskEventDraft,
)
from app.task.contracts.task import RECOVERABLE_TASK_STATUSES
from app.task.tables import (
    artifacts,
    node_runs,
    provider_tasks,
    task_events,
    tasks,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


class _SessionBoundStore:
    """可选绑定外部 Session，供组合 UnitOfWork 共享一个事务。"""

    def __init__(self, session: Optional[Session] = None) -> None:
        self._session = session

    def _session_scope(self):
        return nullcontext(self._session) if self._session is not None else get_session()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _to_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """把 SQLite 读回的 naive datetime 归一为 tz-aware UTC。

    - `DateTime(timezone=True)` 在 SQLite 上以 ISO 字符串存储（不带时区），
      读取时返回 naive datetime。此帮助函数在 Row → Snapshot 映射与
      内部业务比较前统一附加 UTC。
    - PostgreSQL 侧原生 `timestamptz` 无需转换，`dt.tzinfo is not None` 时
      直接返回原对象。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _row_to_task(row: Mapping[str, Any]) -> Task:
    return Task(
        id=row["id"],
        task_type=row["task_type"],
        status=row["status"],
        priority=row["priority"],
        idempotency_key=row["idempotency_key"],
        cancel_requested=bool(row["cancel_requested"]),
        owner_user_id=row["owner_user_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        canvas_id=row["canvas_id"],
        node_id=row["node_id"],
        node_run_id=row["node_run_id"],
        provider_id=row["provider_id"],
        model=row["model"],
        workflow_id=row["workflow_id"],
        input_snapshot=row["input_snapshot"] or {},
        output_refs=row["output_refs"] or [],
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        retry_after=_to_aware(row["retry_after"]),
        lease_owner=row["lease_owner"],
        lease_until=_to_aware(row["lease_until"]),
        heartbeat_at=_to_aware(row["heartbeat_at"]),
        deadline_at=_to_aware(row["deadline_at"]),
        timeout_policy=row["timeout_policy"] or {},
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_category=row["error_category"],
        cost_estimate=row["cost_estimate"],
        cost_actual=row["cost_actual"],
        quota_bucket=row["quota_bucket"],
        created_at=_to_aware(row["created_at"]),
        queued_at=_to_aware(row["queued_at"]),
        started_at=_to_aware(row["started_at"]),
        updated_at=_to_aware(row["updated_at"]),
        finished_at=_to_aware(row["finished_at"]),
        schema_version=row["schema_version"],
    )


def _row_to_node_run(row: Mapping[str, Any]) -> NodeRun:
    return NodeRun(
        id=row["id"],
        canvas_id=row["canvas_id"],
        node_id=row["node_id"],
        node_type=row["node_type"],
        source_node_id=row["source_node_id"],
        run_kind=row["run_kind"],
        status=row["status"],
        trigger_source=row["trigger_source"],
        input_snapshot=row["input_snapshot"] or {},
        settings_snapshot=row["settings_snapshot"] or {},
        dependency_snapshot=row["dependency_snapshot"] or {},
        task_ids=[UUID(s) if isinstance(s, str) else s for s in (row["task_ids"] or [])],
        output_refs=row["output_refs"] or [],
        parent_run_id=row["parent_run_id"],
        batch_key=row["batch_key"],
        attempt=row["attempt"],
        started_at=_to_aware(row["started_at"]),
        finished_at=_to_aware(row["finished_at"]),
        elapsed_ms=row["elapsed_ms"],
        summary=row["summary"],
        error=row["error"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        created_at=_to_aware(row["created_at"]),
        updated_at=_to_aware(row["updated_at"]),
        schema_version=row["schema_version"],
    )


def _row_to_provider_task(row: Mapping[str, Any]) -> ProviderTask:
    return ProviderTask(
        id=row["id"],
        task_id=row["task_id"],
        provider_id=row["provider_id"],
        provider_protocol=row["provider_protocol"],
        capability=row["capability"],
        operation=row["operation"],
        upstream_task_id=row["upstream_task_id"],
        upstream_task_kind=row["upstream_task_kind"],
        remote_status=row["remote_status"],
        status=row["status"],
        progress=row["progress"],
        poll_after=_to_aware(row["poll_after"]),
        poll_count=row["poll_count"],
        last_poll_at=_to_aware(row["last_poll_at"]),
        outputs=row["outputs"] or {},
        error=row["error"],
        raw_excerpt=row["raw_excerpt"],
        query_params=row["query_params"] or {},
        adapter_kind=row["adapter_kind"],
        created_at=_to_aware(row["created_at"]),
        submitted_at=_to_aware(row["submitted_at"]),
        updated_at=_to_aware(row["updated_at"]),
        completed_at=_to_aware(row["completed_at"]),
        schema_version=row["schema_version"],
    )


def _row_to_task_event(row: Mapping[str, Any]) -> TaskEvent:
    return TaskEvent(
        id=row["id"],
        task_id=row["task_id"],
        seq=row["seq"],
        kind=row["kind"],
        ts=_to_aware(row["ts"]),
        payload_json=row["payload_json"] or {},
        schema_version=row["schema_version"],
    )


def _row_to_artifact(row: Mapping[str, Any]) -> Artifact:
    return Artifact(
        id=row["id"],
        task_id=row["task_id"],
        node_run_id=row["node_run_id"],
        provider_task_id=row["provider_task_id"],
        kind=row["kind"],
        url=row["url"],
        file_object_id=row["file_object_id"],
        legacy_url=row["legacy_url"],
        mime_type=row["mime_type"],
        name=row["name"],
        width=row["width"],
        height=row["height"],
        duration=row["duration"],
        size=row["size"],
        sha256=row["sha256"],
        node_id=row["node_id"],
        output_key=row["output_key"],
        role=row["role"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        created_at=_to_aware(row["created_at"]),
        schema_version=row["schema_version"],
    )


def _uuid_list_to_json(ids) -> List[str]:
    return [str(u) for u in ids]


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------


class SqliteTaskStore(_SessionBoundStore):
    """`TaskStore` 端口的 SQLite 实现（走 SQLAlchemy Core）。"""

    def create(self, draft: TaskDraft) -> Task:
        with self._session_scope() as s:
            if draft.idempotency_key:
                existing = s.execute(
                    select(tasks).where(
                        tasks.c.idempotency_key == draft.idempotency_key
                    )
                ).mappings().first()
                if existing:
                    return _row_to_task(existing)
            now = _utcnow()
            task_id = draft.id or uuid.uuid4()
            values = {
                "id": task_id,
                "task_type": draft.task_type,
                "status": draft.status,
                "priority": draft.priority,
                "idempotency_key": draft.idempotency_key,
                "cancel_requested": False,
                "owner_user_id": draft.owner_user_id,
                "workspace_id": draft.workspace_id,
                "project_id": draft.project_id,
                "canvas_id": draft.canvas_id,
                "node_id": draft.node_id,
                "node_run_id": draft.node_run_id,
                "provider_id": draft.provider_id,
                "model": draft.model,
                "workflow_id": draft.workflow_id,
                "input_snapshot": dict(draft.input_snapshot),
                "output_refs": list(draft.output_refs),
                "attempt": 0,
                "max_attempts": draft.max_attempts,
                "retry_after": None,
                "lease_owner": None,
                "lease_until": None,
                "heartbeat_at": None,
                "deadline_at": draft.deadline_at,
                "timeout_policy": dict(draft.timeout_policy),
                "error_code": None,
                "error_message": None,
                "error_category": None,
                "cost_estimate": draft.cost_estimate,
                "cost_actual": None,
                "quota_bucket": draft.quota_bucket,
                "created_at": now,
                "queued_at": now if draft.status == "queued" else None,
                "started_at": None,
                "updated_at": now,
                "finished_at": None,
                "schema_version": draft.schema_version,
            }
            s.execute(tasks.insert().values(**values))
            return _row_to_task(values)

    def get(self, task_id: UUID) -> Optional[Task]:
        with self._session_scope() as s:
            row = s.execute(
                select(tasks).where(tasks.c.id == task_id)
            ).mappings().first()
            return _row_to_task(row) if row else None

    def get_by_idempotency_key(self, key: str) -> Optional[Task]:
        with self._session_scope() as s:
            row = s.execute(
                select(tasks).where(tasks.c.idempotency_key == key)
            ).mappings().first()
            return _row_to_task(row) if row else None

    def list_by_canvas_node(
        self, canvas_id: str, node_id: Optional[str] = None, *, limit: int = 100
    ) -> List[Task]:
        with self._session_scope() as s:
            stmt = select(tasks).where(tasks.c.canvas_id == canvas_id)
            if node_id is not None:
                stmt = stmt.where(tasks.c.node_id == node_id)
            stmt = stmt.order_by(tasks.c.created_at.asc()).limit(limit)
            rows = s.execute(stmt).mappings().all()
            return [_row_to_task(r) for r in rows]

    def update_with_expected(
        self,
        task_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> Task:
        forbidden = {"id", "created_at"}
        for key in updates.keys():
            if key in forbidden:
                raise ValueError(f"禁止通过 update 修改字段 {key!r}")
        with self._session_scope() as s:
            _cas_check_and_update(s, tasks, task_id, updates, expected=expected)
            row = s.execute(
                select(tasks).where(tasks.c.id == task_id)
            ).mappings().first()
            return _row_to_task(row)

    def acquire_lease(
        self, task_id: UUID, owner: str, ttl_sec: int
    ) -> Task:
        with self._session_scope() as s:
            now = _utcnow()
            new_lease_until = now + timedelta(seconds=ttl_sec)
            # 租约判定必须在数据库 WHERE 中完成。独立 Store/Service
            # 实例的 Python 锁彼此不可见，只有这个条件 UPDATE 能做 CAS。
            leaseable = or_(
                tasks.c.status.in_(("queued", "retrying", "unknown_recoverable")),
                and_(
                    tasks.c.lease_owner.is_not(None),
                    tasks.c.lease_until.is_not(None),
                    tasks.c.lease_until <= now,
                ),
            )
            result = s.execute(
                tasks.update()
                .where(and_(tasks.c.id == task_id, leaseable))
                .values(
                    status="leased",
                    lease_owner=owner,
                    lease_until=new_lease_until,
                    heartbeat_at=now,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                row = s.execute(
                    select(tasks.c.lease_owner).where(tasks.c.id == task_id)
                ).first()
                raise CasFailure(
                    f"Task {task_id} 租约抢占失败",
                    key="lease_owner" if row is not None else "id",
                    actual=row[0] if row is not None else None,
                )
            row = s.execute(
                select(tasks).where(tasks.c.id == task_id)
            ).mappings().first()
            return _row_to_task(row)

    def heartbeat(self, task_id: UUID, owner: str, *, ttl_sec: int) -> Task:
        with self._session_scope() as s:
            now = _utcnow()
            result = s.execute(
                tasks.update()
                .where(
                    and_(tasks.c.id == task_id, tasks.c.lease_owner == owner)
                )
                .values(
                    heartbeat_at=now,
                    lease_until=now + timedelta(seconds=ttl_sec),
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise CasFailure(
                    f"Task {task_id} 心跳失败：租约不属于 {owner}",
                    key="lease_owner",
                    expected=owner,
                )
            row = s.execute(
                select(tasks).where(tasks.c.id == task_id)
            ).mappings().first()
            return _row_to_task(row)

    def release_lease(
        self,
        task_id: UUID,
        owner: str,
        *,
        new_status: Optional[str] = None,
    ) -> Task:
        with self._session_scope() as s:
            now = _utcnow()
            payload: Dict[str, Any] = {
                "lease_owner": None,
                "lease_until": None,
                "updated_at": now,
            }
            if new_status is not None:
                payload["status"] = new_status
                if new_status in {"succeeded", "failed", "cancelled", "expired"}:
                    payload["finished_at"] = now
            result = s.execute(
                tasks.update()
                .where(
                    and_(tasks.c.id == task_id, tasks.c.lease_owner == owner)
                )
                .values(**payload)
            )
            if result.rowcount != 1:
                raise CasFailure(
                    f"Task {task_id} 释放租约失败：租约不属于 {owner}",
                    key="lease_owner",
                    expected=owner,
                )
            row = s.execute(
                select(tasks).where(tasks.c.id == task_id)
            ).mappings().first()
            return _row_to_task(row)

    def scan(self, filter: RecoveryFilter) -> List[Task]:
        statuses = list(filter.statuses or RECOVERABLE_TASK_STATUSES)
        with self._session_scope() as s:
            stmt = select(tasks).where(tasks.c.status.in_(statuses))
            if filter.lease_expired_before is not None:
                stmt = stmt.where(
                    or_(
                        tasks.c.lease_until.is_(None),
                        tasks.c.lease_until < filter.lease_expired_before,
                    )
                )
            if filter.workspace_id is not None:
                stmt = stmt.where(tasks.c.workspace_id == filter.workspace_id)
            if filter.project_id is not None:
                stmt = stmt.where(tasks.c.project_id == filter.project_id)
            if filter.owner_user_id is not None:
                stmt = stmt.where(tasks.c.owner_user_id == filter.owner_user_id)
            stmt = (
                stmt.order_by(tasks.c.created_at.asc())
                .offset(filter.offset)
                .limit(filter.limit)
            )
            rows = s.execute(stmt).mappings().all()
            return [_row_to_task(r) for r in rows]


def _cas_check_and_update(
    s: Session,
    table,
    row_id: UUID,
    updates: Mapping[str, object],
    *,
    expected: Mapping[str, object],
) -> None:
    """共享的条件更新实现：`SELECT` 校验 expected，然后按 `id + expected` 条件更新。

    - 校验先行：便于产生细粒度的 `CasFailure(key=..., expected=..., actual=...)`。
    - 更新使用 `expected` 全字段拼 WHERE，保证并发场景下也不会误更。
    """
    row = s.execute(select(table).where(table.c.id == row_id)).mappings().first()
    if row is None:
        raise CasFailure(f"记录 {row_id} 不存在于 {table.name}", key="id")
    for key, expected_value in expected.items():
        actual = row.get(key)
        if actual != expected_value:
            raise CasFailure(
                f"{table.name} 字段 {key!r} 期望 {expected_value!r} 实际 {actual!r}",
                key=key,
                expected=expected_value,
                actual=actual,
            )
    payload = dict(updates)
    payload.setdefault("updated_at", _utcnow())
    where_clauses = [table.c.id == row_id]
    for key, expected_value in expected.items():
        col = getattr(table.c, key)
        if expected_value is None:
            where_clauses.append(col.is_(None))
        else:
            where_clauses.append(col == expected_value)
    result = s.execute(table.update().where(and_(*where_clauses)).values(**payload))
    if result.rowcount != 1:
        raise CasFailure(
            f"{table.name} 并发更新失败（预期匹配已被抢占）", key="__cas__"
        )


# ---------------------------------------------------------------------------
# NodeRun
# ---------------------------------------------------------------------------


class SqliteNodeRunStore(_SessionBoundStore):
    def create(self, draft: NodeRunDraft) -> NodeRun:
        with self._session_scope() as s:
            now = _utcnow()
            run_id = draft.id or uuid.uuid4()
            values = {
                "id": run_id,
                "canvas_id": draft.canvas_id,
                "node_id": draft.node_id,
                "node_type": draft.node_type,
                "source_node_id": draft.source_node_id,
                "run_kind": draft.run_kind,
                "status": draft.status,
                "trigger_source": draft.trigger_source,
                "input_snapshot": dict(draft.input_snapshot),
                "settings_snapshot": dict(draft.settings_snapshot),
                "dependency_snapshot": dict(draft.dependency_snapshot),
                "task_ids": _uuid_list_to_json(draft.task_ids),
                "output_refs": list(draft.output_refs),
                "parent_run_id": draft.parent_run_id,
                "batch_key": draft.batch_key,
                "attempt": draft.attempt,
                "started_at": None,
                "finished_at": None,
                "elapsed_ms": None,
                "summary": None,
                "error": None,
                "workspace_id": draft.workspace_id,
                "project_id": draft.project_id,
                "owner_user_id": draft.owner_user_id,
                "created_at": now,
                "updated_at": now,
                "schema_version": draft.schema_version,
            }
            s.execute(node_runs.insert().values(**values))
            row = s.execute(
                select(node_runs).where(node_runs.c.id == run_id)
            ).mappings().first()
            return _row_to_node_run(row)

    def get(self, node_run_id: UUID) -> Optional[NodeRun]:
        with self._session_scope() as s:
            row = s.execute(
                select(node_runs).where(node_runs.c.id == node_run_id)
            ).mappings().first()
            return _row_to_node_run(row) if row else None

    def list_by_canvas(
        self, canvas_id: str, *, limit: int = 100
    ) -> List[NodeRun]:
        with self._session_scope() as s:
            rows = s.execute(
                select(node_runs)
                .where(node_runs.c.canvas_id == canvas_id)
                .order_by(node_runs.c.created_at.asc())
                .limit(limit)
            ).mappings().all()
            return [_row_to_node_run(r) for r in rows]

    def update_with_expected(
        self,
        node_run_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> NodeRun:
        payload = dict(updates)
        if "task_ids" in payload:
            payload["task_ids"] = _uuid_list_to_json(payload["task_ids"])
        if "output_refs" in payload:
            payload["output_refs"] = list(payload["output_refs"])
        with self._session_scope() as s:
            _cas_check_and_update(
                s, node_runs, node_run_id, payload, expected=expected
            )
            row = s.execute(
                select(node_runs).where(node_runs.c.id == node_run_id)
            ).mappings().first()
            return _row_to_node_run(row)


# ---------------------------------------------------------------------------
# ProviderTask
# ---------------------------------------------------------------------------


class SqliteProviderTaskStore(_SessionBoundStore):
    def create(self, draft: ProviderTaskDraft) -> ProviderTask:
        with self._session_scope() as s:
            now = _utcnow()
            pt_id = draft.id or uuid.uuid4()
            values = {
                "id": pt_id,
                "task_id": draft.task_id,
                "provider_id": draft.provider_id,
                "provider_protocol": draft.provider_protocol,
                "capability": draft.capability,
                "operation": draft.operation,
                "upstream_task_id": draft.upstream_task_id,
                "upstream_task_kind": draft.upstream_task_kind,
                "remote_status": draft.remote_status,
                "status": draft.status,
                "progress": None,
                "poll_after": None,
                "poll_count": 0,
                "last_poll_at": None,
                "outputs": dict(draft.outputs),
                "error": None,
                "raw_excerpt": None,
                "query_params": dict(draft.query_params),
                "adapter_kind": draft.adapter_kind,
                "created_at": now,
                "submitted_at": None,
                "updated_at": now,
                "completed_at": None,
                "schema_version": draft.schema_version,
            }
            s.execute(provider_tasks.insert().values(**values))
            row = s.execute(
                select(provider_tasks).where(provider_tasks.c.id == pt_id)
            ).mappings().first()
            return _row_to_provider_task(row)

    def get(self, provider_task_id: UUID) -> Optional[ProviderTask]:
        with self._session_scope() as s:
            row = s.execute(
                select(provider_tasks).where(
                    provider_tasks.c.id == provider_task_id
                )
            ).mappings().first()
            return _row_to_provider_task(row) if row else None

    def find_by_upstream(
        self, provider_id: str, upstream_task_id: str
    ) -> Optional[ProviderTask]:
        with self._session_scope() as s:
            row = s.execute(
                select(provider_tasks).where(
                    and_(
                        provider_tasks.c.provider_id == provider_id,
                        provider_tasks.c.upstream_task_id == upstream_task_id,
                    )
                )
            ).mappings().first()
            return _row_to_provider_task(row) if row else None

    def list_by_task(self, task_id: UUID) -> List[ProviderTask]:
        with self._session_scope() as s:
            rows = s.execute(
                select(provider_tasks)
                .where(provider_tasks.c.task_id == task_id)
                .order_by(provider_tasks.c.created_at.asc())
            ).mappings().all()
            return [_row_to_provider_task(r) for r in rows]

    def update_with_expected(
        self,
        provider_task_id: UUID,
        updates: Mapping[str, object],
        *,
        expected: Mapping[str, object],
    ) -> ProviderTask:
        with self._session_scope() as s:
            _cas_check_and_update(
                s, provider_tasks, provider_task_id, updates, expected=expected
            )
            row = s.execute(
                select(provider_tasks).where(
                    provider_tasks.c.id == provider_task_id
                )
            ).mappings().first()
            return _row_to_provider_task(row)


# ---------------------------------------------------------------------------
# TaskEvent —— seq 严格单调（同一 task_id 内 1-based）
# ---------------------------------------------------------------------------


class SqliteTaskEventStore(_SessionBoundStore):
    def append(self, draft: TaskEventDraft) -> TaskEvent:
        if self._session is not None:
            return self._append_in_session(self._session, draft)

        # `(task_id, seq)` 唯一约束是最终仲裁。独立 Store 并发
        # 读到同一 max(seq) 时，输家回滚并在新事务重试。
        last_error: Optional[IntegrityError] = None
        for attempt in range(16):
            try:
                with get_session() as s:
                    return self._append_in_session(s, draft)
            except IntegrityError as exc:
                last_error = exc
                time.sleep(min(0.001 * (2**attempt), 0.05))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _append_in_session(s: Session, draft: TaskEventDraft) -> TaskEvent:
        current_max = s.execute(
            select(func.coalesce(func.max(task_events.c.seq), 0)).where(
                task_events.c.task_id == draft.task_id
            )
        ).scalar()
        next_seq = int(current_max or 0) + 1
        ts = draft.ts or _utcnow()
        values = {
            "task_id": draft.task_id,
            "seq": next_seq,
            "ts": ts,
            "kind": draft.kind,
            "payload_json": dict(draft.payload_json),
            "schema_version": draft.schema_version,
        }
        s.execute(task_events.insert().values(**values))
        row = s.execute(
            select(task_events).where(
                and_(
                    task_events.c.task_id == draft.task_id,
                    task_events.c.seq == next_seq,
                )
            )
        ).mappings().first()
        return _row_to_task_event(row)

    def list_for_task(
        self,
        task_id: UUID,
        *,
        since_seq: Optional[int] = None,
        limit: int = 500,
    ) -> List[TaskEvent]:
        with self._session_scope() as s:
            stmt = select(task_events).where(task_events.c.task_id == task_id)
            if since_seq is not None:
                stmt = stmt.where(task_events.c.seq > since_seq)
            stmt = stmt.order_by(task_events.c.seq.asc()).limit(limit)
            rows = s.execute(stmt).mappings().all()
            return [_row_to_task_event(r) for r in rows]

    def count_for_task(self, task_id: UUID) -> int:
        with self._session_scope() as s:
            return int(
                s.execute(
                    select(func.count()).where(task_events.c.task_id == task_id)
                ).scalar()
                or 0
            )


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class SqliteArtifactStore(_SessionBoundStore):
    def create(self, draft: ArtifactDraft) -> Artifact:
        with self._session_scope() as s:
            now = _utcnow()
            aid = draft.id or uuid.uuid4()
            values = {
                "id": aid,
                "task_id": draft.task_id,
                "node_run_id": draft.node_run_id,
                "provider_task_id": draft.provider_task_id,
                "kind": draft.kind,
                "url": draft.url,
                "file_object_id": draft.file_object_id,
                "legacy_url": draft.legacy_url,
                "mime_type": draft.mime_type,
                "name": draft.name,
                "width": draft.width,
                "height": draft.height,
                "duration": draft.duration,
                "size": draft.size,
                "sha256": draft.sha256,
                "node_id": draft.node_id,
                "output_key": draft.output_key,
                "role": draft.role,
                "workspace_id": draft.workspace_id,
                "project_id": draft.project_id,
                "owner_user_id": draft.owner_user_id,
                "created_at": now,
                "schema_version": draft.schema_version,
            }
            s.execute(artifacts.insert().values(**values))
            row = s.execute(
                select(artifacts).where(artifacts.c.id == aid)
            ).mappings().first()
            return _row_to_artifact(row)

    def get(self, artifact_id: UUID) -> Optional[Artifact]:
        with self._session_scope() as s:
            row = s.execute(
                select(artifacts).where(artifacts.c.id == artifact_id)
            ).mappings().first()
            return _row_to_artifact(row) if row else None

    def list_by_task(self, task_id: UUID) -> List[Artifact]:
        with self._session_scope() as s:
            rows = s.execute(
                select(artifacts)
                .where(artifacts.c.task_id == task_id)
                .order_by(artifacts.c.created_at.asc())
            ).mappings().all()
            return [_row_to_artifact(r) for r in rows]

    def list_by_node_run(self, node_run_id: UUID) -> List[Artifact]:
        with self._session_scope() as s:
            rows = s.execute(
                select(artifacts)
                .where(artifacts.c.node_run_id == node_run_id)
                .order_by(artifacts.c.created_at.asc())
            ).mappings().all()
            return [_row_to_artifact(r) for r in rows]


# ---------------------------------------------------------------------------
# 便捷工厂
# ---------------------------------------------------------------------------


def sqlite_stores() -> "tuple":
    """一次返回五件套 SQLite Store。调用方须保证 `run_migrations("head")` 已执行。"""
    return (
        SqliteTaskStore(),
        SqliteNodeRunStore(),
        SqliteProviderTaskStore(),
        SqliteTaskEventStore(),
        SqliteArtifactStore(),
    )


__all__ = [
    "SqliteTaskStore",
    "SqliteNodeRunStore",
    "SqliteProviderTaskStore",
    "SqliteTaskEventStore",
    "SqliteArtifactStore",
    "sqlite_stores",
]
