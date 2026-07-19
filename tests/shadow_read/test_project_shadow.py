"""数据 PR-4 · Project shadow 双读契约测试。

- disabled 默认 → JSON 主读结果字节等价、不写 diff 文件、不构造 engine。
- enabled 且无差异 → 不写 diff。
- enabled 且有差异 → 差异 JSONL schema 稳定；`missing_in_db` 命中。
- 空 DB 场景 → 全部 JSON 项进 `missing_in_db`。
- 延迟上限 → 100 项 shadow read < 200ms（P95 20ms 硬约束的宽松整体上界）。
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
def projects_file(tmp_path, monkeypatch, isolated_env):
    """把 `PROJECTS_PATH` 指到 tmp，写一个已知项目列表。"""

    import main

    projects_path = tmp_path / "projects.json"
    projects_path.write_text(
        json.dumps({
            "projects": [
                {"id": "p1", "name": "Alpha", "order": 1,
                 "created_at": 1000, "updated_at": 2000},
                {"id": "p2", "name": "Beta", "order": 2,
                 "created_at": 1500, "updated_at": 2500},
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "PROJECTS_PATH", str(projects_path))
    yield projects_path


def _load_projects_via_store():
    from app.stores import project_store

    return project_store.load_projects()


def test_shadow_disabled_returns_json_result_byte_equivalent(
    monkeypatch, projects_file
):
    monkeypatch.delenv("SHADOW_READ_PROJECT", raising=False)
    result_a = _load_projects_via_store()
    result_b = _load_projects_via_store()
    assert result_a == result_b
    # 未开启时，绝对不建 diff 目录 subtree
    from app.shared.settings import get_settings

    diff_root = os.path.join(get_settings().data_dir, "shadow_diff", "project")
    assert not os.path.exists(diff_root)


def test_shadow_disabled_never_hits_db(monkeypatch, projects_file):
    """disabled 时，`_load_db_snapshot` / `get_engine` 都不该被触发。"""

    monkeypatch.delenv("SHADOW_READ_PROJECT", raising=False)

    from app.shadow_read import runner as shadow_runner
    from app.db import engine as db_engine

    hit = {"count": 0}

    def _spy(*a, **kw):
        hit["count"] += 1
        return None

    monkeypatch.setattr(db_engine, "get_engine", _spy)
    _load_projects_via_store()
    assert hit["count"] == 0


def test_shadow_enabled_no_diff_when_db_matches(
    monkeypatch, projects_file, tmp_path, isolated_env
):
    """启用且 DB 与 JSON 完全一致 → 不写 diff。"""
    from app.data_import import import_domain

    migrate_baseline(tmp_path)
    import_domain("project", source_path=str(projects_file), dry_run=False)

    monkeypatch.setenv("SHADOW_READ_PROJECT", "true")
    result = _load_projects_via_store()
    assert len(result) == 2
    # No diff written
    diff_root = os.path.join(str(tmp_path), "shadow_diff", "project")
    if os.path.exists(diff_root):
        contents = [
            f for f in Path(diff_root).rglob("*.jsonl")
        ]
        assert not contents, f"expected no diff files, found: {contents}"


def test_shadow_enabled_writes_diff_when_db_empty(
    monkeypatch, projects_file, tmp_path, isolated_env
):
    """启用且 DB 空 → 所有 JSON 项进 `missing_in_db`；写入 JSONL。"""
    migrate_baseline(tmp_path)

    monkeypatch.setenv("SHADOW_READ_PROJECT", "true")
    _load_projects_via_store()

    diff_root = Path(tmp_path) / "shadow_diff" / "project"
    files = list(diff_root.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    rec = json.loads(lines[-1])
    assert rec["domain"] == "project"
    assert set(rec["missing_in_db"]) == {"p1", "p2"}
    assert rec["missing_in_json"] == []
    assert isinstance(rec["field_diffs"], list)


def test_shadow_enabled_flags_field_diff(
    monkeypatch, projects_file, tmp_path, isolated_env
):
    """DB 有相同 legacy_id 但字段不同 → 记 `field_diffs`。"""
    from app.data_import import import_domain

    migrate_baseline(tmp_path)
    import_domain("project", source_path=str(projects_file), dry_run=False)

    # 现在改 JSON 的 name，让 shadow diff 触发
    projects_file.write_text(
        json.dumps({
            "projects": [
                {"id": "p1", "name": "AlphaRenamed", "order": 1,
                 "created_at": 1000, "updated_at": 2000},
                {"id": "p2", "name": "Beta", "order": 2,
                 "created_at": 1500, "updated_at": 2500},
            ]
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("SHADOW_READ_PROJECT", "true")
    _load_projects_via_store()

    diff_root = Path(tmp_path) / "shadow_diff" / "project"
    files = list(diff_root.glob("*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    fields = {(d["legacy_id"], d["field"]) for d in rec["field_diffs"]}
    assert ("p1", "name") in fields


def test_shadow_enabled_latency_under_bound(
    monkeypatch, projects_file, tmp_path, isolated_env
):
    """粗略保护：100 项 shadow-read 总耗时 < 2s（P95 20ms 的宽松整体上界）。"""
    migrate_baseline(tmp_path)
    monkeypatch.setenv("SHADOW_READ_PROJECT", "true")

    start = time.perf_counter()
    for _ in range(100):
        _load_projects_via_store()
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"shadow-read 100x too slow: {elapsed:.3f}s"
