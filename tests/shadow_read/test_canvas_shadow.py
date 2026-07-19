"""数据 PR-5 · Canvas shadow 双读契约测试。

- disabled 默认 → JSON 主读结果字节等价、不写 diff 文件、不构造 engine。
- enabled 且 DB 数据已导入 → `missing_in_db` / `missing_in_json` 为空。
- 空 DB 场景 → 全部 JSON 项进 `missing_in_db`。
- 字段级差异 → `field_diffs` 记录。
- 延迟上限 → 100 次 shadow read < 2 秒。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def canvas_dir_fixture(tmp_path, monkeypatch, isolated_env):
    """把 `CANVAS_DIR` 指到 tmp_path/canvases，写一个已知画布文件。"""

    import main

    canvas_dir = tmp_path / "canvases"
    canvas_dir.mkdir(parents=True, exist_ok=True)
    canvas_data = {
        "id": "c1",
        "title": "Test Canvas",
        "kind": "classic",
        "project": "default",
        "owner": "smoke",
        "pinned": False,
        "created_at": 1000,
        "updated_at": 2000,
        "deleted_at": None,
        "revision": 0,
        "base_updated_at": None,
        "nodes": [],
        "connections": [],
    }
    canvas_path = canvas_dir / "c1.json"
    canvas_path.write_text(json.dumps(canvas_data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "CANVAS_DIR", str(canvas_dir))
    yield canvas_dir


def _load_canvas_via_store():
    from app.stores import canvas_store

    return canvas_store.load_canvas("c1")


def test_shadow_disabled_returns_json_result_byte_equivalent(
    monkeypatch, canvas_dir_fixture
):
    monkeypatch.delenv("SHADOW_READ_CANVAS", raising=False)
    result_a = _load_canvas_via_store()
    result_b = _load_canvas_via_store()
    assert result_a == result_b
    # 未开启时，绝对不建 diff 目录 subtree
    from app.shared.settings import get_settings

    diff_root = os.path.join(get_settings().data_dir, "shadow_diff", "canvas")
    assert not os.path.exists(diff_root)


def test_shadow_disabled_never_hits_db(monkeypatch, canvas_dir_fixture):
    """disabled 时，`_load_db_snapshot` / `get_engine` 都不该被触发。"""

    monkeypatch.delenv("SHADOW_READ_CANVAS", raising=False)

    from app.db import engine as db_engine

    hit = {"count": 0}

    def _spy(*a, **kw):
        hit["count"] += 1
        return None

    monkeypatch.setattr(db_engine, "get_engine", _spy)
    _load_canvas_via_store()
    assert hit["count"] == 0


def test_shadow_enabled_no_diff_when_db_matches(
    monkeypatch, canvas_dir_fixture, tmp_path, isolated_env
):
    """启用且 DB 数据已导入 → `missing_in_db` / `missing_in_json` 为空。
    `created_at` / `updated_at` 因 JSON epoch ms vs DB DateTime 类型差异
    始终触发 field_diffs，但 `missing_in_*` 应为空。"""
    from app.data_import import import_domain

    migrate_baseline(tmp_path)
    import_domain("canvas", source_path=str(canvas_dir_fixture), dry_run=False)

    monkeypatch.setenv("SHADOW_READ_CANVAS", "true")
    result = _load_canvas_via_store()
    assert result["id"] == "c1"

    diff_root = Path(tmp_path) / "shadow_diff" / "canvas"
    files = list(diff_root.glob("*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["domain"] == "canvas"
    assert rec["missing_in_db"] == []
    assert rec["missing_in_json"] == []


def test_shadow_enabled_writes_diff_when_db_empty(
    monkeypatch, canvas_dir_fixture, tmp_path, isolated_env
):
    """启用且 DB 空 → JSON 项进 `missing_in_db`；写入 JSONL。"""
    migrate_baseline(tmp_path)

    monkeypatch.setenv("SHADOW_READ_CANVAS", "true")
    _load_canvas_via_store()

    diff_root = Path(tmp_path) / "shadow_diff" / "canvas"
    files = list(diff_root.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    rec = json.loads(lines[-1])
    assert rec["domain"] == "canvas"
    assert set(rec["missing_in_db"]) == {"c1"}
    assert rec["missing_in_json"] == []
    assert isinstance(rec["field_diffs"], list)


def test_shadow_enabled_flags_field_diff(
    monkeypatch, canvas_dir_fixture, tmp_path, isolated_env
):
    """DB 有相同 legacy_id 但字段不同 → 记 `field_diffs`。"""
    from app.data_import import import_domain

    migrate_baseline(tmp_path)
    import_domain("canvas", source_path=str(canvas_dir_fixture), dry_run=False)

    # 改 JSON 的 title 让 shadow diff 触发
    canvas_file = canvas_dir_fixture / "c1.json"
    canvas_data = json.loads(canvas_file.read_text(encoding="utf-8"))
    canvas_data["title"] = "Renamed Canvas"
    canvas_file.write_text(json.dumps(canvas_data, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("SHADOW_READ_CANVAS", "true")
    _load_canvas_via_store()

    diff_root = Path(tmp_path) / "shadow_diff" / "canvas"
    files = list(diff_root.glob("*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    fields = {(d["legacy_id"], d["field"]) for d in rec["field_diffs"]}
    assert ("c1", "title") in fields


def test_shadow_enabled_latency_under_bound(
    monkeypatch, canvas_dir_fixture, tmp_path, isolated_env
):
    """粗略保护：100 次 shadow-read 总耗时 < 2 秒。"""
    migrate_baseline(tmp_path)
    monkeypatch.setenv("SHADOW_READ_CANVAS", "true")

    start = time.perf_counter()
    for _ in range(100):
        _load_canvas_via_store()
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"shadow-read 100x too slow: {elapsed:.3f}s"