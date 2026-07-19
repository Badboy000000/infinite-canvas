"""任务 PR-4 · History reader 兼容层契约测试。

`TASK_HISTORY_ENABLE=false`（默认）时 `read_history_compat()` 返回的 shape
应与 `main.get_history_api()` byte-equivalent（key 集完全一致，不追加派生
字段）；启用后追加派生字段（`derived_task_id / derived_artifact_ids`）
但旧字段全部保留。
"""

from __future__ import annotations

import json

import pytest

from tests.task.history._helpers import isolated_history_db


@pytest.fixture
def sample_history_file(monkeypatch, tmp_path):
    """写一个稳定 fixture history.json 供两条读路径消费。"""

    import main

    history_path = tmp_path / "history.json"
    records = [
        {
            "prompt": "one",
            "images": ["/output/one.png"],
            "type": "online",
            "provider_id": "comfly",
            "task_id": "upstream-one",
            "timestamp": 100.0,
        },
        {
            "prompt": "two",
            "images": ["/output/two.png"],
            "type": "online",
            "provider_id": "comfly",
            "task_id": "upstream-two",
            "timestamp": 200.0,
        },
        # 无 images 条目——两条读路径都应过滤掉
        {
            "prompt": "no-images",
            "type": "online",
            "timestamp": 300.0,
        },
    ]
    history_path.write_text(json.dumps(records), encoding="utf-8")
    monkeypatch.setattr(main, "HISTORY_FILE", str(history_path))
    yield records


def test_read_compat_shape_matches_api_when_disabled(
    monkeypatch, sample_history_file
):
    """`TASK_HISTORY_ENABLE=false` 时 read_history_compat 每个 record 的 key
    集与 get_history_api 完全一致（byte-equivalent shape）。"""

    monkeypatch.delenv("TASK_HISTORY_ENABLE", raising=False)
    import asyncio

    import main
    from app.task.history.reader import read_history_compat

    api_records = asyncio.run(main.get_history_api())
    compat_records = read_history_compat()
    assert len(api_records) == len(compat_records) == 2
    for api_rec, compat_rec in zip(api_records, compat_records):
        assert set(api_rec.keys()) == set(compat_rec.keys()), (
            f"key set drift: api={set(api_rec.keys())} vs "
            f"compat={set(compat_rec.keys())}"
        )
        for key in api_rec:
            assert api_rec[key] == compat_rec[key]


def test_read_compat_sorted_by_timestamp_desc(monkeypatch, sample_history_file):
    monkeypatch.delenv("TASK_HISTORY_ENABLE", raising=False)
    from app.task.history.reader import read_history_compat

    records = read_history_compat()
    timestamps = [r["timestamp"] for r in records]
    assert timestamps == sorted(timestamps, reverse=True)


def test_read_compat_augments_when_enabled(
    monkeypatch, tmp_path, sample_history_file
):
    """启用后追加派生字段；旧字段一个不能少。"""

    monkeypatch.setenv("TASK_HISTORY_ENABLE", "true")

    with isolated_history_db(monkeypatch, tmp_path):
        from app.task.history import get_history_writer
        from app.task.history.reader import read_history_compat

        writer = get_history_writer()
        # 预先写派生副本 —— 与 read 路径共用同一进程 sqlite
        for record in sample_history_file:
            if record.get("images"):
                writer.write_from_task(source_record=dict(record))

        augmented = read_history_compat(writer=writer)
        assert len(augmented) == 2
        # 每条都有派生 task id
        for record in augmented:
            assert "derived_task_id" in record
            assert isinstance(record["derived_task_id"], str)
            assert "derived_artifact_ids" in record
            assert isinstance(record["derived_artifact_ids"], list)
            assert len(record["derived_artifact_ids"]) >= 1
            # 原字段全保留
            assert "prompt" in record
            assert "images" in record
            assert "timestamp" in record
