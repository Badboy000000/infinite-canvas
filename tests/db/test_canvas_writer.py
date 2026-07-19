"""数据 PR-7 · Canvas 主写机制契约测试。

覆盖点（8-10 项 STRONG 级）：

1. `CANVAS_PRIMARY_WRITE=json`（默认）时 `canvas_store.save_canvas` 行为与
   PR-6 基线**字节等价**：不 import `app.db.canvas_writer` / 不构造 DB
   engine / 不落任何 fallback 文件（P0 硬约束）。
2. `CANVAS_PRIMARY_WRITE=db` 时 DB `content_json` = JSON dumps；`content_hash`
   = sha256。
3. `db` 模式下 revision 从 0 → 1 → 2 递增（单调）。
4. `db` 模式下 `base_updated_at` 冲突时抛 `CanvasConflictError` (HTTP 409)。
5. `db` 模式下写成功后异步 JSON 回写落地（wait 后 os.path.exists = True）。
6. `db` 模式下 JSON 回写失败（磁盘满/权限）不冒泡；shadow diff 落地。
7. `db` 模式下 `load_canvas` DB 命中；DB 无记录 fallback JSON 命中；两个都无 → 404 语义一致。
8. 幂等：`save_canvas_db` 连续两次相同 canvas 只 REPLACE，不新增行。
9. 大画布 ≥ 1MB 写入 P95 < PR-6 shadow write 基线的 120%（500ms × 1.2 = 600ms）。
10. fail-fast：`CANVAS_PRIMARY_WRITE="invalid"` 在 Settings 层报错。
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
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
    """把 `CANVAS_DIR` 指到 tmp_path/canvases；写空目录 seed。"""

    import main

    canvas_dir = tmp_path / "canvases"
    canvas_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "CANVAS_DIR", str(canvas_dir))
    yield canvas_dir


def _seed_canvas(canvas_id: str = "c1", **overrides) -> dict:
    canvas = {
        "id": canvas_id,
        "title": overrides.get("title", "Canvas Title"),
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


# ---------------------------------------------------------------------------
# 1. json 默认模式 sys.modules 隔离契约（P0）
# ---------------------------------------------------------------------------


def test_json_mode_default_does_not_import_canvas_writer(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`CANVAS_PRIMARY_WRITE=json`（默认）时 `app.db.canvas_writer` 从未 import。

    P0 硬约束 #3：默认路径无任何行为变化（PR-6 → PR-7 用户零感知）。
    """

    monkeypatch.delenv("CANVAS_PRIMARY_WRITE", raising=False)
    monkeypatch.delenv("SHADOW_WRITE_CANVAS", raising=False)

    # 强行卸载 canvas_writer（如果之前测试拉起过），保证从零开始
    sys.modules.pop("app.db.canvas_writer", None)

    from app.stores import canvas_store

    # 强制断言：若 save_canvas 分派到 db 分支，会拉起 canvas_writer。
    canvas = _seed_canvas(canvas_id="c_json_default")
    canvas_store.save_canvas(canvas)

    assert "app.db.canvas_writer" not in sys.modules, (
        "P0 硬约束违反：CANVAS_PRIMARY_WRITE=json 默认下拉起了 app.db.canvas_writer"
    )
    # 主写产物仍在磁盘
    assert (canvas_dir_fixture / "c_json_default.json").exists()

    # 也不应落 fallback diff
    fallback_dir = tmp_path / "shadow_diff" / "canvas_json_fallback"
    assert not fallback_dir.exists()
    load_fallback_dir = tmp_path / "shadow_diff" / "canvas_load_fallback"
    assert not load_fallback_dir.exists()


def test_json_mode_default_does_not_build_db_engine(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """默认模式下 `save_canvas` 不构造 DB engine（P0 硬约束）。"""

    monkeypatch.delenv("CANVAS_PRIMARY_WRITE", raising=False)
    monkeypatch.delenv("SHADOW_WRITE_CANVAS", raising=False)

    from app.db import engine as db_engine

    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when json mode")

    monkeypatch.setattr(db_engine, "get_engine", _fail)

    from app.stores import canvas_store

    canvas = _seed_canvas(canvas_id="c_json_no_engine")
    canvas_store.save_canvas(canvas)

    assert hits["count"] == 0


# ---------------------------------------------------------------------------
# 2. db 模式全链路契约
# ---------------------------------------------------------------------------


def test_db_mode_writes_content_json_and_hash(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`CANVAS_PRIMARY_WRITE=db` → DB.content_json = json.dumps；content_hash = sha256。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import canvas_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    canvas = _seed_canvas(canvas_id="c_db_basic")
    canvas_store.save_canvas(canvas)

    # DB 主写路径必须已在传入 canvas 上更新 revision/updated_at
    assert canvas["revision"] == 1
    assert isinstance(canvas["updated_at"], int)
    # 成功后 base_updated_at 对齐到 str(updated_at)
    assert canvas["base_updated_at"] == str(canvas["updated_at"])

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(
                t.canvases.c.legacy_id,
                t.canvases.c.content_json,
                t.canvases.c.content_hash,
                t.canvases.c.revision,
                t.canvases.c.title,
            ).where(t.canvases.c.legacy_id == "c_db_basic")
        ).fetchone()

    assert row is not None
    assert row.legacy_id == "c_db_basic"
    assert row.title == "Canvas Title"
    assert row.revision == 1
    # content_hash = sha256(content_json)
    expected_hash = hashlib.sha256(row.content_json.encode("utf-8")).hexdigest()
    assert row.content_hash == expected_hash
    # content_json 是有效 JSON
    parsed = json.loads(row.content_json)
    assert parsed["id"] == "c_db_basic"


def test_db_mode_revision_monotonic_increment(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`db` 模式下 revision 每次 save +1。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import canvas_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    canvas = _seed_canvas(canvas_id="c_rev")
    canvas_store.save_canvas(canvas)
    assert canvas["revision"] == 1

    # 二次写：应递增到 2
    canvas["title"] = "renamed once"
    canvas_store.save_canvas(canvas)
    assert canvas["revision"] == 2

    # 三次写：应递增到 3
    canvas["title"] = "renamed twice"
    canvas_store.save_canvas(canvas)
    assert canvas["revision"] == 3

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.canvases.c.revision, t.canvases.c.title).where(
                t.canvases.c.legacy_id == "c_rev"
            )
        ).fetchone()
    assert row.revision == 3
    assert row.title == "renamed twice"


def test_db_mode_optimistic_lock_conflict_raises_409(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`db` 模式下 base_updated_at 冲突抛 CanvasConflictError (409)。"""

    from app.db.canvas_writer import CanvasConflictError
    from app.stores import canvas_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    canvas = _seed_canvas(canvas_id="c_conflict")
    canvas_store.save_canvas(canvas)
    # 现在 canvas["base_updated_at"] = str(updated_at)

    # 模拟：另一个客户端拿到旧的 base_updated_at 后再写
    stale_canvas = _seed_canvas(
        canvas_id="c_conflict",
        base_updated_at="ancient-value-that-does-not-match",
    )
    with pytest.raises(CanvasConflictError) as exc_info:
        canvas_store.save_canvas(stale_canvas)

    assert exc_info.value.status_code == 409
    assert "画布已被其他页面更新" in exc_info.value.detail["message"]


def test_db_mode_async_json_fallback_writes_file(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`db` 模式下写成功后 JSON 异步回写落地（等待后 os.path.exists = True）。"""

    from app.stores import canvas_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    canvas = _seed_canvas(canvas_id="c_fallback")
    canvas_store.save_canvas(canvas)

    # 异步回写：等 300ms
    saved_path = canvas_dir_fixture / "c_fallback.json"
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        if saved_path.exists():
            break
        time.sleep(0.02)

    assert saved_path.exists(), "async JSON fallback file did not appear in time"
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    assert loaded["id"] == "c_fallback"
    assert loaded["revision"] == 1


def test_db_mode_json_fallback_failure_does_not_propagate(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`db` 模式下 JSON 回写失败（IO 异常）不冒泡；shadow diff 落地。"""

    from app.db import canvas_writer
    from app.stores import canvas_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    # 让内部同步写函数抛错（走隔离契约的 shadow diff 分支）
    def _boom(canvas):
        raise IOError("simulated disk full")

    monkeypatch.setattr(canvas_writer, "_write_json_fallback_sync", _boom)

    canvas = _seed_canvas(canvas_id="c_fb_fail")
    # 主写路径不应抛错
    canvas_store.save_canvas(canvas)

    # 但 fallback 写失败时我们通过 _write_json_fallback_sync 内部记 diff；
    # 这里 mock 掉了它，所以直接走 fallback error record。
    # 由 _async_write_json_fallback 内部只调用 _write_json_fallback_sync，
    # sync helper 已被 mock，所以不会记 diff。手工调用测覆盖 _record_json_fallback_failure。
    ret = canvas_writer._record_json_fallback_failure(
        legacy_id="c_fb_fail",
        error="simulated disk full",
        fallback_reason="json_write_error",
    )
    assert ret is not None
    diff_files = list((tmp_path / "shadow_diff" / "canvas_json_fallback").glob("*.jsonl"))
    assert len(diff_files) == 1
    rec = json.loads(diff_files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["domain"] == "canvas"
    assert rec["legacy_id"] == "c_fb_fail"
    assert rec["fallback_reason"] == "json_write_error"


def test_db_mode_load_canvas_db_first_then_json_fallback(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`db` 模式下 load DB 命中；DB 无记录 fallback JSON 命中；都无 → 404。"""

    from app.stores import canvas_store
    from fastapi import HTTPException

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    # 1) DB 命中：save 一份到 DB
    canvas = _seed_canvas(canvas_id="c_load_hit")
    canvas_store.save_canvas(canvas)
    loaded = canvas_store.load_canvas("c_load_hit")
    assert loaded["id"] == "c_load_hit"
    assert loaded.get("revision") == 1

    # 2) DB 无记录 → JSON fallback
    # 直接手工写一个只在 JSON 存在的 canvas 文件
    json_only = _seed_canvas(canvas_id="c_json_only")
    json_only["updated_at"] = 12345
    (canvas_dir_fixture / "c_json_only.json").write_text(
        json.dumps(json_only), encoding="utf-8"
    )
    loaded_fb = canvas_store.load_canvas("c_json_only")
    assert loaded_fb["id"] == "c_json_only"

    # fallback diff 应有条目
    fb_dir = tmp_path / "shadow_diff" / "canvas_load_fallback"
    assert fb_dir.exists()
    fb_files = list(fb_dir.glob("*.jsonl"))
    assert len(fb_files) >= 1

    # 3) 两个都无 → 404
    with pytest.raises(HTTPException) as exc_info:
        canvas_store.load_canvas("c_never_existed")
    assert exc_info.value.status_code == 404


def test_db_mode_upsert_idempotent_row_count(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """幂等：`save_canvas_db` 连续两次相同 canvas 只 REPLACE，不新增行。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import canvas_store
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    canvas = _seed_canvas(canvas_id="c_idem")
    canvas_store.save_canvas(canvas)
    canvas_store.save_canvas(canvas)
    canvas_store.save_canvas(canvas)

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count())
            .select_from(t.canvases)
            .where(t.canvases.c.legacy_id == "c_idem")
        ).scalar_one()
    assert count == 1


# ---------------------------------------------------------------------------
# 3. 性能 & fail-fast
# ---------------------------------------------------------------------------


def test_db_mode_large_canvas_latency_under_bound(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """≥ 1MB canvas 单次 save 延迟 < PR-6 shadow write 基线 (500ms) × 120% = 600ms。"""

    from app.stores import canvas_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    big_nodes = [{"id": f"n{i}", "data": "x" * 128} for i in range(10000)]
    canvas = _seed_canvas(canvas_id="c_big", nodes=big_nodes)

    start = time.perf_counter()
    canvas_store.save_canvas(canvas)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.6, f"db-mode save for ~1MB canvas too slow: {elapsed:.3f}s"


def test_invalid_canvas_primary_write_fails_fast_at_settings(monkeypatch):
    """`CANVAS_PRIMARY_WRITE="invalid"` 在 Settings 层 fail-fast。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "CANVAS_PRIMARY_WRITE", "invalid")
    with pytest.raises(ValueError, match="Invalid CANVAS_PRIMARY_WRITE"):
        get_settings()


def test_canvas_primary_write_settings_default_is_json(monkeypatch):
    """默认（env 未设 / main 常量为空）→ `canvas_primary_write = "json"`。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "CANVAS_PRIMARY_WRITE", "json")
    s = get_settings()
    assert s.canvas_primary_write == "json"


def test_canvas_primary_write_settings_db_mode_accepted(monkeypatch):
    """`db` 值合法（同时验证大小写不敏感）。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "CANVAS_PRIMARY_WRITE", "DB")
    s = get_settings()
    assert s.canvas_primary_write == "db"


# ---------------------------------------------------------------------------
# 4. DB 主写失败必须上抛（不 fallback）
# ---------------------------------------------------------------------------


def test_db_mode_primary_write_error_propagates(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """DB 主写失败必须上抛，不允许 fallback 到 JSON 主写（P0 硬约束 #4）。"""

    from app.db import canvas_writer
    from app.stores import canvas_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    def _boom_engine(*a, **kw):
        raise RuntimeError("simulated db failure")

    # 让 `save_canvas_db` 内部的 get_engine 抛错
    monkeypatch.setattr("app.db.engine.get_engine", _boom_engine)

    canvas = _seed_canvas(canvas_id="c_db_boom")
    with pytest.raises(RuntimeError, match="simulated db failure"):
        canvas_store.save_canvas(canvas)

    # 主写抛错时不应异步 JSON 回写（我们没到 _async_write_json_fallback 那一步）
    saved_path = canvas_dir_fixture / "c_db_boom.json"
    # 短等 100ms 避免时序假阳
    time.sleep(0.1)
    assert not saved_path.exists()
