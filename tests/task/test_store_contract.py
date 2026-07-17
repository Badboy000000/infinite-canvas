"""任务 PR-0 · Store 端口契约测试（Memory + SQLite 双跑）。

覆盖端口签名冻结的 6 类接口：

1. CRUD（create / get / list / get_by_idempotency_key / find_by_upstream）。
2. 条件更新 / 乐观锁（`update_with_expected` + `CasFailure`）。
3. 租约 / 心跳 / 释放（`acquire_lease` / `heartbeat` / `release_lease`）。
4. TaskEvent append 顺序（同一 task_id 内 `seq` 严格单调 1-based）。
5. 恢复扫描（`RecoveryFilter`：状态、租约过期、workspace / project / owner 过滤）。
6. Artifact / NodeRun / ProviderTask 交叉查询（`list_by_task` /
   `list_by_node_run` / `find_by_upstream`）。

Memory 与 SQLite 参数化同一 fixture，保证两套实现同源行为。
"""

from __future__ import annotations

import uuid
import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Tuple

import pytest

from app.task.contracts import (
    ArtifactDraft,
    CasFailure,
    NodeRunDraft,
    ProviderTaskDraft,
    RecoveryFilter,
    TaskDraft,
    TaskEventDraft,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_bundle():
    from app.task.store import memory_stores

    return memory_stores()


@pytest.fixture
def sqlite_bundle(tmp_path, monkeypatch):
    """临时 sqlite + 建表 + 返回五件套 SQLite Store。

    - 隔离 `main.DATA_DB_PATH` 到 tmp_path。
    - `reset_engine()` + `run_migrations("head")` 建表。
    """
    import main
    from app.db import engine as _engine_mod
    from app.db.session import _SessionLocal  # noqa: F401 触发 lazy reset via reset
    from app.db import session as _session_mod

    db_path = tmp_path / "contract.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(db_path))
    _engine_mod.reset_engine()
    # 重置 session sessionmaker（下一次 SessionLocal() 会重新绑定新 engine）
    _session_mod._SessionLocal = None
    _engine_mod.run_migrations("head")

    from app.task.store import sqlite_stores

    yield sqlite_stores()

    # teardown
    _engine_mod.reset_engine()
    _session_mod._SessionLocal = None


BUNDLE_PARAMS = ("memory", "sqlite")


@pytest.fixture(params=BUNDLE_PARAMS)
def bundle(request, memory_bundle, sqlite_bundle):
    """参数化：memory / sqlite 各跑一遍所有契约测试。"""
    if request.param == "memory":
        return memory_bundle
    return sqlite_bundle


def _stores(bundle) -> Tuple:
    return bundle  # (task, node_run, provider_task, event, artifact)


# ---------------------------------------------------------------------------
# 1. CRUD
# ---------------------------------------------------------------------------


def test_task_create_and_get(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image", input_snapshot={"prompt": "hi"}))
    assert t.task_type == "image"
    assert t.status == "queued"
    assert t.attempt == 0
    assert t.input_snapshot == {"prompt": "hi"}
    assert ts.get(t.id).id == t.id
    assert ts.get(uuid.uuid4()) is None


def test_task_create_with_id_and_idempotency(bundle):
    ts, _, _, _, _ = _stores(bundle)
    idem = "job-abc-123"
    fixed_id = uuid.uuid4()
    t1 = ts.create(
        TaskDraft(task_type="video", id=fixed_id, idempotency_key=idem)
    )
    assert t1.id == fixed_id
    # 重复提交同 idempotency_key —— 返回原 Task（不新建）
    t2 = ts.create(TaskDraft(task_type="video", idempotency_key=idem))
    assert t2.id == t1.id
    assert ts.get_by_idempotency_key(idem).id == t1.id


def test_task_list_by_canvas_node(bundle):
    ts, _, _, _, _ = _stores(bundle)
    a = ts.create(TaskDraft(task_type="image", canvas_id="c1", node_id="n1"))
    b = ts.create(TaskDraft(task_type="image", canvas_id="c1", node_id="n2"))
    _ = ts.create(TaskDraft(task_type="image", canvas_id="c2", node_id="n1"))
    all_c1 = ts.list_by_canvas_node("c1")
    ids = {t.id for t in all_c1}
    assert {a.id, b.id} <= ids
    only_n1 = ts.list_by_canvas_node("c1", "n1")
    assert {t.id for t in only_n1} == {a.id}


# ---------------------------------------------------------------------------
# 2. 条件更新 / 乐观锁
# ---------------------------------------------------------------------------


def test_task_update_with_expected_success(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    updated = ts.update_with_expected(
        t.id,
        {"status": "running", "attempt": 1},
        expected={"status": "queued", "attempt": 0},
    )
    assert updated.status == "running"
    assert updated.attempt == 1


def test_task_update_with_expected_conflict(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    ts.update_with_expected(
        t.id, {"status": "running"}, expected={"status": "queued"}
    )
    with pytest.raises(CasFailure) as ei:
        ts.update_with_expected(
            t.id, {"status": "succeeded"}, expected={"status": "queued"}
        )
    assert ei.value.key == "status"


def test_task_update_forbidden_field(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    with pytest.raises(ValueError):
        ts.update_with_expected(
            t.id, {"id": uuid.uuid4()}, expected={"status": "queued"}
        )


# ---------------------------------------------------------------------------
# 3. 租约 / 心跳 / 释放
# ---------------------------------------------------------------------------


def test_task_lease_acquire_and_heartbeat(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    leased = ts.acquire_lease(t.id, "worker-A", ttl_sec=30)
    assert leased.lease_owner == "worker-A"
    assert leased.lease_until is not None
    assert leased.status == "leased"

    # heartbeat：延长 lease_until
    hb = ts.heartbeat(t.id, "worker-A", ttl_sec=60)
    assert hb.heartbeat_at is not None
    assert hb.lease_until > leased.lease_until


def test_task_lease_double_acquire_conflicts(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    ts.acquire_lease(t.id, "worker-A", ttl_sec=60)
    with pytest.raises(CasFailure):
        ts.acquire_lease(t.id, "worker-B", ttl_sec=60)


def test_task_lease_release_transitions_status(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    ts.acquire_lease(t.id, "worker-A", ttl_sec=60)
    released = ts.release_lease(t.id, "worker-A", new_status="succeeded")
    assert released.lease_owner is None
    assert released.status == "succeeded"
    assert released.finished_at is not None


def test_task_heartbeat_wrong_owner_conflicts(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    ts.acquire_lease(t.id, "worker-A", ttl_sec=60)
    with pytest.raises(CasFailure):
        ts.heartbeat(t.id, "worker-B", ttl_sec=60)


# ---------------------------------------------------------------------------
# 4. TaskEvent append 顺序
# ---------------------------------------------------------------------------


def test_task_event_seq_monotonic_per_task(bundle):
    ts, _, _, es, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    e1 = es.append(TaskEventDraft(task_id=t.id, kind="task.created"))
    e2 = es.append(TaskEventDraft(task_id=t.id, kind="task.queued"))
    e3 = es.append(TaskEventDraft(task_id=t.id, kind="task.started"))
    assert e1.seq == 1
    assert e2.seq == 2
    assert e3.seq == 3
    assert es.count_for_task(t.id) == 3

    listed = es.list_for_task(t.id)
    assert [e.seq for e in listed] == [1, 2, 3]

    since_1 = es.list_for_task(t.id, since_seq=1)
    assert [e.seq for e in since_1] == [2, 3]


def test_task_event_seq_isolated_across_tasks(bundle):
    ts, _, _, es, _ = _stores(bundle)
    t1 = ts.create(TaskDraft(task_type="image"))
    t2 = ts.create(TaskDraft(task_type="image"))
    es.append(TaskEventDraft(task_id=t1.id, kind="task.created"))
    es.append(TaskEventDraft(task_id=t1.id, kind="task.queued"))
    e_first_t2 = es.append(TaskEventDraft(task_id=t2.id, kind="task.created"))
    assert e_first_t2.seq == 1  # 每个 task 独立起点
    assert es.count_for_task(t1.id) == 2
    assert es.count_for_task(t2.id) == 1


def test_sqlite_event_seq_is_atomic_across_independent_stores(sqlite_bundle):
    """多个 Store 实例不共享 Python 锁，须由唯一约束 + 冲突重试定序。"""
    from app.task.store import SqliteTaskEventStore

    task_store, _, _, _, _ = sqlite_bundle
    task = task_store.create(TaskDraft(task_type="image"))
    barrier = threading.Barrier(12)
    events = []
    errors = []

    def append(index):
        try:
            store = SqliteTaskEventStore()
            barrier.wait()
            events.append(
                store.append(
                    TaskEventDraft(task_id=task.id, kind=f"concurrent.{index}")
                )
            )
        except Exception as exc:  # pragma: no cover - 断言会暴露
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(event.seq for event in events) == list(range(1, 13))
    assert SqliteTaskEventStore().count_for_task(task.id) == 12


def test_sqlite_lease_cas_across_independent_services(sqlite_bundle):
    from app.task.service import TaskService, TaskStateError
    from app.task.store import SqliteTaskEventStore, SqliteTaskStore

    creator = TaskService(SqliteTaskStore(), SqliteTaskEventStore())
    task = creator.submit(TaskDraft(task_type="image", max_attempts=2))
    barrier = threading.Barrier(2)
    winners = []
    losers = []

    def lease(owner):
        service = TaskService(SqliteTaskStore(), SqliteTaskEventStore())
        barrier.wait()
        try:
            winners.append(service.lease(task.id, owner, ttl_sec=60))
        except TaskStateError as exc:
            losers.append(exc)

    threads = [
        threading.Thread(target=lease, args=("worker-a",)),
        threading.Thread(target=lease, args=("worker-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(winners) == 1
    assert len(losers) == 1
    stored = SqliteTaskStore().get(task.id)
    assert stored.lease_owner == winners[0].lease_owner
    assert stored.attempt == 1


# ---------------------------------------------------------------------------
# 5. 恢复扫描
# ---------------------------------------------------------------------------


def test_scan_default_filters_terminal_states(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t_run = ts.create(TaskDraft(task_type="image"))
    ts.update_with_expected(
        t_run.id, {"status": "running"}, expected={"status": "queued"}
    )
    t_done = ts.create(TaskDraft(task_type="image"))
    ts.update_with_expected(
        t_done.id, {"status": "succeeded"}, expected={"status": "queued"}
    )
    t_recover = ts.create(TaskDraft(task_type="image"))
    ts.update_with_expected(
        t_recover.id,
        {"status": "unknown_recoverable"},
        expected={"status": "queued"},
    )

    hits = ts.scan(RecoveryFilter())
    hit_ids = {t.id for t in hits}
    assert t_run.id in hit_ids
    assert t_recover.id in hit_ids
    assert t_done.id not in hit_ids  # succeeded 不在默认恢复集合


def test_scan_by_workspace_and_owner(bundle):
    ts, _, _, _, _ = _stores(bundle)
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()
    owner_x = uuid.uuid4()
    t_a = ts.create(TaskDraft(task_type="image", workspace_id=ws_a))
    ts.update_with_expected(
        t_a.id, {"status": "running"}, expected={"status": "queued"}
    )
    t_b = ts.create(TaskDraft(task_type="image", workspace_id=ws_b))
    ts.update_with_expected(
        t_b.id, {"status": "running"}, expected={"status": "queued"}
    )
    t_x = ts.create(
        TaskDraft(task_type="image", workspace_id=ws_a, owner_user_id=owner_x)
    )
    ts.update_with_expected(
        t_x.id, {"status": "running"}, expected={"status": "queued"}
    )

    only_a = ts.scan(RecoveryFilter(workspace_id=ws_a))
    ids_a = {t.id for t in only_a}
    assert {t_a.id, t_x.id} <= ids_a
    assert t_b.id not in ids_a

    only_x = ts.scan(RecoveryFilter(owner_user_id=owner_x))
    ids_x = {t.id for t in only_x}
    assert ids_x == {t_x.id}


def test_scan_lease_expired_filter(bundle):
    ts, _, _, _, _ = _stores(bundle)
    t_leased = ts.create(TaskDraft(task_type="image"))
    ts.acquire_lease(t_leased.id, "worker-A", ttl_sec=60)
    # 抓取一个位于 lease_until 之前的时间点：所有租约都视为过期
    future = datetime.now(tz=timezone.utc) + timedelta(hours=1)
    hits = ts.scan(
        RecoveryFilter(
            statuses=("leased",),
            lease_expired_before=future,
        )
    )
    assert t_leased.id in {t.id for t in hits}


# ---------------------------------------------------------------------------
# 6. NodeRun / ProviderTask / Artifact 关联查询
# ---------------------------------------------------------------------------


def test_node_run_create_and_list(bundle):
    _, nrs, _, _, _ = _stores(bundle)
    r = nrs.create(NodeRunDraft(canvas_id="c1", node_id="n1", node_type="smart-image"))
    assert nrs.get(r.id).id == r.id
    listed = nrs.list_by_canvas("c1")
    assert {run.id for run in listed} == {r.id}


def test_provider_task_find_by_upstream(bundle):
    ts, _, pts, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    pt = pts.create(
        ProviderTaskDraft(
            task_id=t.id,
            provider_id="runninghub",
            provider_protocol="runninghub_v1",
            upstream_task_id="rh_abc123",
        )
    )
    found = pts.find_by_upstream("runninghub", "rh_abc123")
    assert found is not None
    assert found.id == pt.id
    assert pts.find_by_upstream("runninghub", "rh_missing") is None
    listed = pts.list_by_task(t.id)
    assert {p.id for p in listed} == {pt.id}


def test_artifact_relationships(bundle):
    ts, nrs, _, _, arts = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    r = nrs.create(
        NodeRunDraft(canvas_id="c1", node_id="n1", node_type="smart-image")
    )
    a1 = arts.create(
        ArtifactDraft(
            kind="image",
            task_id=t.id,
            node_run_id=r.id,
            url="/output/x.png",
        )
    )
    a2 = arts.create(
        ArtifactDraft(kind="image", task_id=t.id, url="/output/y.png")
    )
    assert arts.get(a1.id).url == "/output/x.png"
    ids_by_task = {a.id for a in arts.list_by_task(t.id)}
    assert ids_by_task == {a1.id, a2.id}
    ids_by_run = {a.id for a in arts.list_by_node_run(r.id)}
    assert ids_by_run == {a1.id}


# ---------------------------------------------------------------------------
# NodeRun / ProviderTask 条件更新
# ---------------------------------------------------------------------------


def test_node_run_update_with_expected(bundle):
    _, nrs, _, _, _ = _stores(bundle)
    r = nrs.create(NodeRunDraft(canvas_id="c1", node_id="n1", node_type="smart-image"))
    updated = nrs.update_with_expected(
        r.id, {"status": "running"}, expected={"status": "created"}
    )
    assert updated.status == "running"
    with pytest.raises(CasFailure):
        nrs.update_with_expected(
            r.id, {"status": "succeeded"}, expected={"status": "created"}
        )


def test_provider_task_update_with_expected(bundle):
    ts, _, pts, _, _ = _stores(bundle)
    t = ts.create(TaskDraft(task_type="image"))
    pt = pts.create(
        ProviderTaskDraft(
            task_id=t.id,
            provider_id="apimart",
            provider_protocol="apimart_v1",
        )
    )
    updated = pts.update_with_expected(
        pt.id, {"status": "submitted"}, expected={"status": "queued"}
    )
    assert updated.status == "submitted"
    with pytest.raises(CasFailure):
        pts.update_with_expected(
            pt.id, {"status": "succeeded"}, expected={"status": "queued"}
        )
