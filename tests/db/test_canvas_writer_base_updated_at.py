"""CB-P5-10 · `save_canvas_db` `base_updated_at` 序列化时序测试。

数据 PR-15 内嵌承接：`app/db/canvas_writer.py::save_canvas_db` 在序列化
`content_json` 之前，先把 `canvas["base_updated_at"]` 对齐到新基线，
消除 DB `content_json` 与异步 JSON 回写文件之间在 `base_updated_at`
字段上的字节等价漂移（PR-10 T71 观察到的时序问题）。

- 反审强度：STRONG（DB row 与 JSON 文件字节等价对比 · 端到端契约验证）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def canvas_dir_fixture(tmp_path, monkeypatch, isolated_env):
    import main

    canvas_dir = tmp_path / "canvases"
    canvas_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "CANVAS_DIR", str(canvas_dir))
    yield canvas_dir


def _seed_canvas(canvas_id: str, **overrides: Any) -> dict[str, Any]:
    canvas = {
        "id": canvas_id,
        "title": overrides.get("title", "CB-P5-10 Canvas"),
        "kind": overrides.get("kind", "classic"),
        "project": overrides.get("project", "default"),
        "owner": overrides.get("owner", "tester"),
        "pinned": overrides.get("pinned", False),
        "created_at": overrides.get("created_at", 1000),
        "updated_at": overrides.get("updated_at", 2000),
        "deleted_at": overrides.get("deleted_at", None),
        "revision": overrides.get("revision", 0),
        "base_updated_at": overrides.get("base_updated_at", None),
        "nodes": overrides.get("nodes", []),
        "connections": overrides.get("connections", []),
    }
    return canvas


def _wait_for_file(path: Path, timeout: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


def test_save_canvas_db_base_updated_at_serialized_after_alignment(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """CB-P5-10 硬护栏：DB `content_json` 与 JSON 文件的 `base_updated_at`
    字段字节等价（修复前 DB 里是旧基线 · JSON 文件里是新基线）。"""

    from app.data_import import tables as t
    from app.db.canvas_writer import save_canvas_db, _async_write_json_fallback
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)

    canvas = _seed_canvas("c_CB_P5_10")
    save_canvas_db(canvas)
    _async_write_json_fallback(canvas)

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.canvases.c.content_json, t.canvases.c.base_updated_at).where(
                t.canvases.c.legacy_id == "c_CB_P5_10"
            )
        ).fetchone()
    assert row is not None

    json_path = canvas_dir_fixture / "c_CB_P5_10.json"
    assert _wait_for_file(json_path, timeout=2.0), (
        "异步 JSON 回写应在合理窗口内落盘"
    )

    db_parsed = json.loads(row.content_json)
    fs_parsed = json.loads(json_path.read_text(encoding="utf-8"))

    # 关键契约：DB.content_json 与 JSON 文件 base_updated_at 字节等价
    assert db_parsed["base_updated_at"] == fs_parsed["base_updated_at"], (
        "CB-P5-10 · DB.content_json base_updated_at 必须与 JSON 文件字节等价"
    )
    # 且都对齐到 DB 表列 base_updated_at
    assert db_parsed["base_updated_at"] == row.base_updated_at, (
        "CB-P5-10 · content_json 内 base_updated_at 必须与 DB 表列一致"
    )
    # 新基线 == 新 updated_at 字符串
    assert db_parsed["base_updated_at"] == str(canvas["updated_at"]), (
        "CB-P5-10 · base_updated_at 必须等于 str(canvas['updated_at'])"
    )


def test_save_canvas_db_optimistic_lock_still_uses_original_base(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """CB-P5-10 反例护栏：修复不得破坏乐观锁 · `expected_base` 必须仍读
    调用方传入的旧值（不能因为提前 mutate 就把新值当作 expected）。"""

    from app.db.canvas_writer import CanvasConflictError, save_canvas_db

    migrate_baseline(tmp_path)

    # 第一次写入建立基线
    canvas = _seed_canvas("c_CB_P5_10_lock")
    save_canvas_db(canvas)
    # 记录第一次写入后新基线
    base_after_first = canvas["base_updated_at"]
    assert base_after_first is not None

    # 用旧的 None 基线再写一次 · 必须冲突（说明 expected_base 读的是入参而非
    # mutate 后的新值）
    stale_canvas = _seed_canvas("c_CB_P5_10_lock", title="stale")
    stale_canvas["base_updated_at"] = None
    with pytest.raises(CanvasConflictError):
        save_canvas_db(stale_canvas)

    # 用最新基线继续写 · 应成功且推进基线
    fresh_canvas = _seed_canvas("c_CB_P5_10_lock", title="fresh")
    fresh_canvas["base_updated_at"] = base_after_first
    save_canvas_db(fresh_canvas)
    assert fresh_canvas["base_updated_at"] != base_after_first
