"""任务 PR-4 · Task/Artifact → History 派生字段完整性契约测试。

Task 副本必须挂 provider_id / model / task_type / input_snapshot；
Artifact 副本必须按 record["images"] 逐条创建并把 URL 落到 `legacy_url`；
`ProviderTask` 副本在 record 提供 upstream `task_id` 时也应创建。
"""

from __future__ import annotations

import pytest

from tests.task.history._helpers import isolated_history_db


@pytest.fixture
def enable_history(monkeypatch):
    monkeypatch.setenv("TASK_HISTORY_ENABLE", "true")
    yield


def test_derived_task_fields_populated(monkeypatch, tmp_path, enable_history):
    from app.task.history import get_history_writer

    with isolated_history_db(monkeypatch, tmp_path):
        writer = get_history_writer()
        record = {
            "prompt": "the-prompt",
            "images": ["/output/a.png"],
            "type": "online",
            "provider_id": "comfly",
            "model": "gpt-image-1",
            "params": {"size": "1024x1024", "n": 1},
            "task_id": "upstream-abc",
            "request_id": "req-1",
            "timestamp": 100.0,
        }
        task_uuid = writer.write_from_task(source_record=record)
        stored = writer.task_store().get(task_uuid)
        assert stored is not None
        assert stored.provider_id == "comfly"
        assert stored.model == "gpt-image-1"
        assert stored.status == "succeeded"
        assert stored.task_type == "online-image"
        # input_snapshot 承载 prompt + params
        assert stored.input_snapshot.get("prompt") == "the-prompt"
        assert stored.input_snapshot.get("params", {}).get("size") == "1024x1024"


def test_derived_artifacts_created_per_image(monkeypatch, tmp_path, enable_history):
    from app.task.history import get_history_writer

    with isolated_history_db(monkeypatch, tmp_path):
        writer = get_history_writer()
        record = {
            "prompt": "multi",
            "images": ["/output/a.png", "/output/b.png", "/output/c.png"],
            "type": "online",
            "provider_id": "comfly",
            "task_id": "upstream-multi",
            "timestamp": 42.0,
        }
        task_uuid = writer.write_from_task(source_record=record)
        artifacts = writer.artifact_store().list_by_task(task_uuid)
        urls = sorted(a.url for a in artifacts)
        assert urls == ["/output/a.png", "/output/b.png", "/output/c.png"]
        # legacy_url 承载迁移锚点
        assert all(a.legacy_url == a.url for a in artifacts)
        assert all(a.kind == "image" for a in artifacts)


def test_derived_provider_task_when_upstream_id_present(
    monkeypatch, tmp_path, enable_history
):
    from app.task.history import get_history_writer

    with isolated_history_db(monkeypatch, tmp_path):
        writer = get_history_writer()
        record = {
            "prompt": "with_upstream",
            "images": ["/output/a.png"],
            "type": "online",
            "provider_id": "runninghub",
            "task_id": "rh-upstream-42",
            "timestamp": 7.0,
        }
        task_uuid = writer.write_from_task(source_record=record)
        # ProviderTask 副本按 (provider_id, upstream_task_id) 复用
        existing = writer._provider_task_store.find_by_upstream(
            "runninghub", "rh-upstream-42"
        )
        assert existing is not None
        assert existing.task_id == task_uuid
        assert existing.status == "succeeded"


def test_task_type_derived_from_record_type(monkeypatch, tmp_path, enable_history):
    from app.task.history import get_history_writer

    with isolated_history_db(monkeypatch, tmp_path):
        writer = get_history_writer()
        for record_type, expected_task_type in (
            ("online", "online-image"),
            ("angle", "online-image"),
            ("zimage", "comfy-workflow"),
            ("video", "online-video"),
            ("weird_unknown_kind", "weird_unknown_kind"),  # fallback
        ):
            record = {
                "prompt": f"p-{record_type}",
                "images": [f"/output/{record_type}.png"],
                "type": record_type,
                "task_id": f"u-{record_type}",
                "timestamp": hash(record_type) % 1000000,
            }
            task_uuid = writer.write_from_task(source_record=record)
            assert task_uuid is not None, record_type
            stored = writer.task_store().get(task_uuid)
            assert stored.task_type == expected_task_type, (
                f"record type {record_type} → {stored.task_type}, "
                f"expected {expected_task_type}"
            )
