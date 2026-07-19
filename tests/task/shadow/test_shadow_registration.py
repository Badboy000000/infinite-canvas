"""任务 PR-3 · 提交路径影子登记契约测试。

`TASK_SHADOW_ENABLE=true` 时，`_shadow_register("submit", ...)` 应该在
SQLite 事实层建 Task 副本；`GET /api/canvas-image-tasks/{id}` 返回 shape
不变（读路径不切）。
"""

from __future__ import annotations

import pytest

from tests.task.shadow._helpers import isolated_shadow_db


@pytest.fixture
def enable_shadow(monkeypatch):
    monkeypatch.setenv("TASK_SHADOW_ENABLE", "true")
    yield


def test_shadow_submit_creates_task_row(monkeypatch, tmp_path, enable_shadow):
    import main
    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        task_uuid = registry.register_submit(
            "canvas_img_test1",
            task_type="online-image",
            provider_id="comfly",
            model="gpt-image-1",
        )
        assert task_uuid is not None
        stored = registry.task_store().get(task_uuid)
        assert stored is not None
        assert stored.task_type == "online-image"
        assert stored.status == "queued"
        assert stored.idempotency_key == "canvas_task:canvas_img_test1"


def test_shadow_submit_is_idempotent(monkeypatch, tmp_path, enable_shadow):
    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        first = registry.register_submit(
            "canvas_img_dup", task_type="online-image"
        )
        second = registry.register_submit(
            "canvas_img_dup", task_type="online-image"
        )
        assert first == second


def test_shadow_read_endpoint_shape_unchanged(monkeypatch, tmp_path, enable_shadow):
    """`GET /api/canvas-image-tasks/{id}` 返回 shape 与影子层无耦合。"""
    import main

    with isolated_shadow_db(monkeypatch, tmp_path):
        with main.CANVAS_TASK_LOCK:
            main.CANVAS_TASKS["canvas_img_shape"] = {
                "id": "canvas_img_shape",
                "type": "online-image",
                "status": "queued",
                "created_at": 1.0,
                "updated_at": 1.0,
                "result": None,
                "error": "",
                "provider_id": "comfly",
                "model": "gpt-image-1",
            }
        # register a shadow copy
        from app.task.shadow import get_shadow_registry

        get_shadow_registry().register_submit(
            "canvas_img_shape",
            task_type="online-image",
            provider_id="comfly",
        )
        # 读路径直接读 CANVAS_TASKS，与影子层无关联
        with main.CANVAS_TASK_LOCK:
            task = dict(main.CANVAS_TASKS["canvas_img_shape"])
        assert "id" in task
        assert task["status"] == "queued"
        assert "provider_id" in task
        assert "shadow_task_uuid" not in task  # 严禁泄漏到读路径
        # cleanup
        with main.CANVAS_TASK_LOCK:
            main.CANVAS_TASKS.pop("canvas_img_shape", None)
