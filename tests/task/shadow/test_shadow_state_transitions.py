"""任务 PR-3 · 状态跃迁副本测试。

轮询驱动的 `queued → running → succeeded / failed` 序列在影子层
`TaskEventStore` 侧应有对应事件副本。
"""

from __future__ import annotations

import pytest

from tests.task.shadow._helpers import isolated_shadow_db


@pytest.fixture
def enable_shadow(monkeypatch):
    monkeypatch.setenv("TASK_SHADOW_ENABLE", "true")
    yield


def test_transition_flow_appends_events(monkeypatch, tmp_path, enable_shadow):
    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        registry.register_submit("canvas_img_flow", task_type="online-image")
        registry.register_transition("canvas_img_flow", status="running")
        registry.register_release("canvas_img_flow", status="succeeded")
        # verify events
        task_uuid = registry.snapshot_canvas_task_map()["canvas_img_flow"]
        events = registry._event_store.list_for_task(task_uuid)
        kinds = [event.kind for event in events]
        assert "task.created" in kinds
        assert "task.queued" in kinds
        assert "task.started" in kinds  # running mapped
        assert "task.succeeded" in kinds


def test_transition_failure_path(monkeypatch, tmp_path, enable_shadow):
    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        registry.register_submit("canvas_img_bad", task_type="online-image")
        registry.register_transition("canvas_img_bad", status="running")
        registry.register_release(
            "canvas_img_bad", status="failed", error_message="upstream 500"
        )
        task_uuid = registry.snapshot_canvas_task_map()["canvas_img_bad"]
        task = registry.task_store().get(task_uuid)
        assert task.status == "failed"
        assert task.error_message == "upstream 500"


def test_unknown_status_string_is_skipped(monkeypatch, tmp_path, enable_shadow):
    """`jimeng_pending` 等未映射字面量当前不驱动影子状态跃迁。"""

    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        registry.register_submit("canvas_img_pending", task_type="online-image")
        # 未映射字面量 → 静默 skip，不抛
        registry.register_transition("canvas_img_pending", status="jimeng_pending")
        task_uuid = registry.snapshot_canvas_task_map()["canvas_img_pending"]
        task = registry.task_store().get(task_uuid)
        assert task.status == "queued"  # 未变
