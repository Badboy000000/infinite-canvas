"""任务 PR-4 · 派生写幂等契约测试。

同一 `record`（相同 `task_id / request_id / timestamp` 摘要）二次进入
`write_from_task` 必须返回**同一** Task UUID，不产生副本。
"""

from __future__ import annotations

import pytest

from tests.task.history._helpers import isolated_history_db


@pytest.fixture
def enable_history(monkeypatch):
    monkeypatch.setenv("TASK_HISTORY_ENABLE", "true")
    yield


def test_write_from_task_creates_derived_task(monkeypatch, tmp_path, enable_history):
    from app.task.history import get_history_writer

    with isolated_history_db(monkeypatch, tmp_path):
        writer = get_history_writer()
        record = {
            "prompt": "hi",
            "images": ["/output/x.png"],
            "type": "online",
            "provider_id": "comfly",
            "model": "gpt-image-1",
            "task_id": "upstream-1",
            "timestamp": 1234.5,
        }
        task_uuid = writer.write_from_task(source_record=record)
        assert task_uuid is not None
        stored = writer.task_store().get(task_uuid)
        assert stored is not None
        assert stored.status == "succeeded"
        assert stored.task_type == "online-image"
        assert stored.idempotency_key.startswith("history:")


def test_write_from_task_is_idempotent(monkeypatch, tmp_path, enable_history):
    from app.task.history import get_history_writer

    with isolated_history_db(monkeypatch, tmp_path):
        writer = get_history_writer()
        record = {
            "prompt": "hi",
            "images": ["/output/x.png"],
            "type": "online",
            "provider_id": "comfly",
            "task_id": "upstream-dup",
            "timestamp": 5678.0,
        }
        first = writer.write_from_task(source_record=record)
        second = writer.write_from_task(source_record=record)
        assert first == second


def test_second_write_bypasses_cache_via_store(monkeypatch, tmp_path, enable_history):
    """即使 in-memory cache 被清空，store 层 `get_by_idempotency_key`
    仍能查回同一 Task —— 保证进程重启后 History 补写幂等。"""

    from app.task.history import get_history_writer, reset_history_writer

    with isolated_history_db(monkeypatch, tmp_path):
        writer = get_history_writer()
        record = {
            "prompt": "persistent",
            "images": ["/output/y.png"],
            "type": "online",
            "task_id": "upstream-persist",
            "timestamp": 9.0,
        }
        first = writer.write_from_task(source_record=record)
        # 清缓存但保留 SQLite；模拟进程重启
        writer._by_record_key.clear()
        second = writer.write_from_task(source_record=record)
        assert first == second
