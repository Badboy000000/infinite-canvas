from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import pytest

from app.task.contracts import (
    NodeRunDraft,
    ProviderTaskDraft,
    RecoveryFilter,
    TaskDraft,
)
from app.task.service import (
    InvalidTaskTransition,
    NodeRunService,
    ProviderTaskService,
    TASK_TRANSITIONS,
    TaskService,
    TaskStateError,
)
from app.task.service.state_machine import ensure_transition
from app.task.store import memory_stores


@pytest.fixture
def service_bundle():
    task_store, _, _, event_store, _ = memory_stores()
    return TaskService(task_store, event_store), task_store, event_store


def test_submit_is_idempotent_and_writes_events_once(service_bundle):
    service, _, events = service_bundle
    draft = TaskDraft(
        task_type="image",
        input_snapshot={"prompt": "hello"},
        idempotency_key="canvas:c1:node:n1:input:v1",
    )

    first = service.submit(draft)
    second = service.submit(draft)

    assert second.id == first.id
    assert [event.kind for event in events.list_for_task(first.id)] == [
        "task.created",
        "task.queued",
    ]


def test_concurrent_idempotent_submit_returns_one_task(service_bundle):
    service, _, events = service_bundle
    barrier = threading.Barrier(8)
    task_ids = []

    def submit():
        barrier.wait()
        task_ids.append(
            service.submit(
                TaskDraft(
                    task_type="image",
                    idempotency_key="concurrent-submit",
                )
            ).id
        )

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(task_ids)) == 1
    assert events.count_for_task(task_ids[0]) == 2


def test_transition_matrix_rejects_skips_and_terminal_reentry(service_bundle):
    service, _, _ = service_bundle
    task = service.submit(TaskDraft(task_type="image"))

    with pytest.raises(InvalidTaskTransition):
        service.transition(task.id, "succeeded")

    leased = service.lease(task.id, "worker-a", ttl_sec=30)
    running = service.transition(leased.id, "running", expected="leased")
    succeeded = service.release(
        running.id,
        "worker-a",
        status="succeeded",
        output_refs=("/output/result.png",),
    )
    assert succeeded.status == "succeeded"

    with pytest.raises(InvalidTaskTransition):
        service.transition(succeeded.id, "queued")


def test_state_machine_matrix_is_exhaustive():
    statuses = set(TASK_TRANSITIONS)
    assert statuses == {
        "created",
        "queued",
        "leased",
        "running",
        "waiting_upstream",
        "downloading",
        "retrying",
        "succeeded",
        "failed",
        "timed_out",
        "cancel_requested",
        "cancelled",
        "expired",
        "unknown_recoverable",
    }
    for current in statuses:
        for target in statuses:
            if target in TASK_TRANSITIONS[current]:
                ensure_transition(current, target)
            else:
                with pytest.raises(InvalidTaskTransition):
                    ensure_transition(current, target)


@pytest.mark.parametrize("status", ["running", "succeeded", "unknown"])
def test_submit_rejects_non_entry_statuses(service_bundle, status):
    service, _, _ = service_bundle
    with pytest.raises(TaskStateError, match="must start"):
        service.submit(TaskDraft(task_type="image", status=status))


def test_cancel_is_idempotent_and_preserves_event_order(service_bundle):
    service, _, events = service_bundle
    task = service.submit(TaskDraft(task_type="image"))

    cancelled = service.cancel(task.id)
    again = service.cancel(task.id)

    assert cancelled.status == again.status == "cancelled"
    assert again.cancel_requested is True
    assert [event.kind for event in events.list_for_task(task.id)] == [
        "task.created",
        "task.queued",
        "task.cancel_requested",
        "task.cancelled",
    ]


def test_retry_requires_capacity_and_records_retry_before_new_lease(service_bundle):
    service, _, events = service_bundle
    task = service.submit(TaskDraft(task_type="image", max_attempts=2))
    service.lease(task.id, "worker-a", ttl_sec=30)
    service.transition(task.id, "running", expected="leased")
    failed = service.release(
        task.id,
        "worker-a",
        status="failed",
        error_code="provider_unavailable",
        error_message="temporary outage",
    )

    retrying = service.retry(failed.id)
    assert retrying.status == "retrying"
    assert retrying.error_code is None
    assert events.list_for_task(task.id)[-1].kind == "task.retry_scheduled"

    service.lease(task.id, "worker-b", ttl_sec=30)
    service.transition(task.id, "running", expected="leased")
    exhausted = service.release(task.id, "worker-b", status="failed")
    with pytest.raises(TaskStateError, match="attempts exhausted"):
        service.retry(exhausted.id)


def test_retry_is_declared_in_the_state_machine():
    assert "retrying" in TASK_TRANSITIONS["failed"]
    assert "retrying" in TASK_TRANSITIONS["timed_out"]
    assert "retrying" in TASK_TRANSITIONS["cancelled"]


def test_recover_compensates_expired_lease_once(service_bundle):
    service, store, events = service_bundle
    task = service.submit(TaskDraft(task_type="image"))
    service.lease(task.id, "dead-worker", ttl_sec=30)
    service.transition(task.id, "running", expected="leased")
    stale = datetime.now(timezone.utc) - timedelta(seconds=1)
    store.update_with_expected(
        task.id,
        {"lease_until": stale},
        expected={"lease_owner": "dead-worker"},
    )

    recovered = service.recover(
        RecoveryFilter(
            statuses=("running",),
            lease_expired_before=datetime.now(timezone.utc),
        )
    )
    assert [item.id for item in recovered] == [task.id]
    snapshot = service.query(task.id)
    assert snapshot.status == "unknown_recoverable"
    assert snapshot.lease_owner is None
    assert events.list_for_task(task.id)[-1].kind == "task.recovered"

    assert service.recover(
        RecoveryFilter(
            statuses=("running",),
            lease_expired_before=datetime.now(timezone.utc),
        )
    ) == []


def test_heartbeat_requires_current_lease_owner(service_bundle):
    service, _, _ = service_bundle
    task = service.submit(TaskDraft(task_type="image"))
    service.lease(task.id, "worker-a", ttl_sec=30)
    refreshed = service.heartbeat(task.id, "worker-a", ttl_sec=60)
    assert refreshed.heartbeat_at is not None

    with pytest.raises(TaskStateError, match="lease owner"):
        service.heartbeat(task.id, "worker-b", ttl_sec=60)


def test_sqlite_service_preserves_idempotency_and_event_order(
    tmp_path, monkeypatch
):
    import main
    from app.db import engine as engine_module
    from app.db import session as session_module
    from app.task.store import sqlite_stores

    monkeypatch.setattr(main, "DATA_DB_PATH", str(tmp_path / "service.db"))
    engine_module.reset_engine()
    session_module._SessionLocal = None
    engine_module.run_migrations("head")
    try:
        task_store, node_store, provider_store, event_store, _ = sqlite_stores()
        service = TaskService(task_store, event_store)
        draft = TaskDraft(
            task_type="image", idempotency_key="sqlite-idempotent"
        )
        task = service.submit(draft)
        assert service.submit(draft).id == task.id
        service.lease(task.id, "worker-a", ttl_sec=30)
        service.transition(task.id, "running", expected="leased")
        service.release(task.id, "worker-a", status="succeeded")

        assert [event.kind for event in event_store.list_for_task(task.id)] == [
            "task.created",
            "task.queued",
            "task.leased",
            "task.started",
            "task.succeeded",
        ]

        provider_service = ProviderTaskService(
            task_store, provider_store, event_store
        )
        provider_task = provider_service.submit(
            ProviderTaskDraft(
                task_id=task.id,
                provider_id="runninghub",
                provider_protocol="runninghub_v1",
                upstream_task_id="sqlite-upstream",
            )
        )
        assert provider_service.recover(
            "runninghub", "sqlite-upstream"
        ).id == provider_task.id

        node_service = NodeRunService(task_store, node_store, event_store)
        node_run = node_service.create(
            NodeRunDraft(canvas_id="c1", node_id="n1", node_type="image")
        )
        node_service.attach(node_run.id, [task.id])
        assert node_service.finalize(
            node_run.id, status="succeeded", output_refs=("done",)
        ).status == "succeeded"
    finally:
        engine_module.reset_engine()
        session_module._SessionLocal = None


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_unit_of_work_rolls_back_task_when_event_append_fails(
    backend, tmp_path, monkeypatch
):
    cleanup = lambda: None
    if backend == "memory":
        task_store, _, _, event_store, _ = memory_stores()
        monkeypatch.setattr(
            event_store, "append", lambda draft: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    else:
        import main
        from app.db import engine as engine_module
        from app.db import session as session_module
        from app.task.store import SqliteTaskEventStore, sqlite_stores

        monkeypatch.setattr(main, "DATA_DB_PATH", str(tmp_path / "rollback.db"))
        engine_module.reset_engine()
        session_module._SessionLocal = None
        engine_module.run_migrations("head")
        task_store, _, _, event_store, _ = sqlite_stores()
        monkeypatch.setattr(
            SqliteTaskEventStore,
            "append",
            lambda self, draft: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        def cleanup():
            engine_module.reset_engine()
            session_module._SessionLocal = None

    task_id = __import__("uuid").uuid4()
    service = TaskService(task_store, event_store)
    try:
        with pytest.raises(RuntimeError, match="boom"):
            service.submit(TaskDraft(id=task_id, task_type="image"))
        assert task_store.get(task_id) is None
        assert event_store.count_for_task(task_id) == 0
    finally:
        cleanup()


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_unit_of_work_rolls_back_status_and_result_when_terminal_event_fails(
    backend, tmp_path, monkeypatch
):
    cleanup = lambda: None
    if backend == "memory":
        task_store, _, _, event_store, _ = memory_stores()
    else:
        import main
        from app.db import engine as engine_module
        from app.db import session as session_module
        from app.task.store import sqlite_stores

        monkeypatch.setattr(main, "DATA_DB_PATH", str(tmp_path / "release-rollback.db"))
        engine_module.reset_engine()
        session_module._SessionLocal = None
        engine_module.run_migrations("head")
        task_store, _, _, event_store, _ = sqlite_stores()

        def cleanup():
            engine_module.reset_engine()
            session_module._SessionLocal = None

    service = TaskService(task_store, event_store)
    task = service.submit(TaskDraft(task_type="image"))
    service.lease(task.id, "worker-a", ttl_sec=30)
    service.transition(task.id, "running", expected="leased")
    baseline_events = event_store.count_for_task(task.id)

    if backend == "memory":
        monkeypatch.setattr(
            event_store, "append", lambda draft: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    else:
        from app.task.store import SqliteTaskEventStore

        monkeypatch.setattr(
            SqliteTaskEventStore,
            "append",
            lambda self, draft: (_ for _ in ()).throw(RuntimeError("boom")),
        )

    try:
        with pytest.raises(RuntimeError, match="boom"):
            service.release(
                task.id,
                "worker-a",
                status="succeeded",
                output_refs=("/output/result.png",),
            )
        stored = task_store.get(task.id)
        assert stored.status == "running"
        assert stored.lease_owner == "worker-a"
        assert list(stored.output_refs) == []
        assert event_store.count_for_task(task.id) == baseline_events
    finally:
        cleanup()


def test_provider_task_service_submit_query_and_recover_are_persisted_atomically():
    task_store, _, provider_store, event_store, _ = memory_stores()
    task = TaskService(task_store, event_store).submit(TaskDraft(task_type="image"))
    service = ProviderTaskService(task_store, provider_store, event_store)
    provider_task = service.submit(
        ProviderTaskDraft(
            task_id=task.id,
            provider_id="runninghub",
            provider_protocol="runninghub_v1",
            upstream_task_id="up-1",
        )
    )

    assert service.query(provider_task.id) == provider_task
    assert service.recover("runninghub", "up-1") == provider_task
    assert event_store.list_for_task(task.id)[-1].kind == "provider.submitted"


def test_node_run_service_create_attach_and_finalize():
    task_store, node_store, _, event_store, _ = memory_stores()
    task = TaskService(task_store, event_store).submit(TaskDraft(task_type="image"))
    service = NodeRunService(task_store, node_store, event_store)
    node_run = service.create(
        NodeRunDraft(canvas_id="c1", node_id="n1", node_type="image")
    )
    attached = service.attach(node_run.id, [task.id])
    finalized = service.finalize(
        node_run.id,
        status="succeeded",
        output_refs=("/output/result.png",),
        summary="done",
    )

    assert attached.status == "running"
    assert attached.task_ids == [task.id]
    assert finalized.status == "succeeded"
    assert finalized.output_refs == ("/output/result.png",)
    assert [event.kind for event in event_store.list_for_task(task.id)][-2:] == [
        "node_run.attached",
        "node_run.finalized",
    ]
