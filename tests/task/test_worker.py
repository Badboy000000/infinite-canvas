from __future__ import annotations

import asyncio

from app.task.contracts import TaskDraft
from app.task.service import TaskOutcome, TaskService
from app.task.store import memory_stores
from app.task.worker import InProcessDispatcher, InProcessExecutor, InProcessWorker


def test_dispatcher_and_executor_satisfy_frozen_ports():
    from app.task.service import TaskDispatcher, TaskExecutor

    service, dispatcher, executor, _ = _runtime()
    assert isinstance(dispatcher, TaskDispatcher)
    assert isinstance(executor, TaskExecutor)
    assert service is not None


def test_worker_is_stopped_by_default():
    async def scenario():
        service, dispatcher, executor, events = _runtime()
        calls = []

        async def handler(task):
            calls.append(task.id)
            return TaskOutcome(status="succeeded", output_refs=("done",))

        worker = InProcessWorker(
            executor,
            pool="image",
            worker_id="worker-a",
            handler=handler,
            poll_interval_sec=0.01,
        )
        task = await dispatcher.submit(TaskDraft(task_type="image"))
        await asyncio.sleep(0.03)

        assert worker.running is False
        assert calls == []
        assert service.query(task.id).status == "queued"
        assert [event.kind for event in events.list_for_task(task.id)] == [
            "task.created",
            "task.queued",
        ]

    asyncio.run(scenario())


def test_worker_executes_after_explicit_start_with_heartbeat_and_ordered_events():
    async def scenario():
        service, dispatcher, executor, events = _runtime()
        heartbeat_extended = []

        async def handler(task):
            await asyncio.sleep(0.03)
            heartbeat_extended.append(
                service.query(task.id).lease_until > task.lease_until
            )
            return TaskOutcome(status="succeeded", output_refs=("done",))

        worker = InProcessWorker(
            executor,
            pool="image",
            worker_id="worker-a",
            handler=handler,
            lease_ttl_sec=1,
            heartbeat_interval_sec=0.01,
            poll_interval_sec=0.01,
        )
        task = await dispatcher.submit(TaskDraft(task_type="image"))
        worker.start()
        try:
            for _ in range(100):
                if service.query(task.id).status == "succeeded":
                    break
                await asyncio.sleep(0.01)
        finally:
            await worker.stop()

        snapshot = service.query(task.id)
        assert snapshot.status == "succeeded"
        assert snapshot.heartbeat_at is not None
        assert heartbeat_extended == [True]
        assert snapshot.output_refs == ["done"] or snapshot.output_refs == ("done",)
        assert [event.kind for event in events.list_for_task(task.id)] == [
            "task.created",
            "task.queued",
            "task.leased",
            "task.started",
            "task.succeeded",
        ]

    asyncio.run(scenario())


def test_worker_failure_releases_lease_and_records_failure():
    async def scenario():
        service, dispatcher, executor, events = _runtime()

        async def handler(task):
            raise RuntimeError("handler failed")

        worker = InProcessWorker(
            executor,
            pool="image",
            worker_id="worker-a",
            handler=handler,
        )
        task = await dispatcher.submit(TaskDraft(task_type="image"))
        assert await worker.run_once() is True

        snapshot = service.query(task.id)
        assert snapshot.status == "failed"
        assert snapshot.lease_owner is None
        assert snapshot.error_code == "worker_error"
        assert events.list_for_task(task.id)[-1].kind == "task.failed"

    asyncio.run(scenario())


def _runtime():
    task_store, _, _, event_store, _ = memory_stores()
    service = TaskService(task_store, event_store)
    wake_event = asyncio.Event()
    dispatcher = InProcessDispatcher(service, wake_event=wake_event)
    executor = InProcessExecutor(service)
    return service, dispatcher, executor, event_store
