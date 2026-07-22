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


# ---------------------------------------------------------------------------
# CB-P5-13 承接（数据 PR-17 · Wave 3-M 主线 A）· Store 层 3 边界补齐
# ---------------------------------------------------------------------------


def test_save_canvas_db_base_updated_at_equal_boundary_succeeds(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """T120 · CB-P5-13 承接 · equal 边界。

    首写建立基线后 · 第二次写入的 `base_updated_at` **等于** DB 现值
    (client base == DB base) → 应成功 · 不抛 `CanvasConflictError` ·
    row 被更新且新基线严格 > 旧基线。
    """

    from app.db.canvas_writer import save_canvas_db
    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)

    # 首写建立基线（base_updated_at 从 None → 新基线）
    canvas = _seed_canvas("c_CB_P5_13_equal")
    save_canvas_db(canvas)
    baseline = canvas["base_updated_at"]
    assert baseline is not None

    engine = get_engine()
    with engine.connect() as conn:
        db_base_before = conn.execute(
            select(t.canvases.c.base_updated_at).where(
                t.canvases.c.legacy_id == "c_CB_P5_13_equal"
            )
        ).scalar_one()
    assert db_base_before == baseline, "首写后 DB 表列 base_updated_at == canvas 新基线"

    # 第二次写入：client 传入的 base_updated_at 严格等于 DB 现值 → equal 边界
    second = _seed_canvas("c_CB_P5_13_equal", title="equal-second")
    second["base_updated_at"] = baseline  # 关键 · equal 边界
    save_canvas_db(second)  # 不应抛 CanvasConflictError

    # 断言：DB 表列 base_updated_at 已推进（新基线严格 > 旧基线）
    with engine.connect() as conn:
        db_base_after = conn.execute(
            select(t.canvases.c.base_updated_at).where(
                t.canvases.c.legacy_id == "c_CB_P5_13_equal"
            )
        ).scalar_one()
    assert db_base_after is not None
    assert db_base_after != baseline, (
        "equal 边界 save 成功后 DB 表列 base_updated_at 必须推进"
    )
    # canvas dict 也应同步到新基线
    assert second["base_updated_at"] == db_base_after


def test_save_canvas_db_base_updated_at_newer_boundary_returns_409(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """T121 · CB-P5-13 承接 · newer 边界（反向漂移防护）。

    首写建立基线后 · 第二次写入的 `base_updated_at` **大于** DB 现值
    (client base > DB base) → 必须 409（`CanvasConflictError`）·
    这是反向漂移防护：客户端不可能拿到比 DB 更新的基线。
    """

    from app.db.canvas_writer import CanvasConflictError, save_canvas_db

    migrate_baseline(tmp_path)

    # 首写建立基线
    canvas = _seed_canvas("c_CB_P5_13_newer")
    save_canvas_db(canvas)
    baseline = canvas["base_updated_at"]
    assert baseline is not None
    # 构造严格大于 DB 现值的基线（DB 是 str(毫秒时间戳)· 直接 +1 秒转 str）
    newer_base = str(int(baseline) + 10_000)  # 十秒漂移 · 严格大于

    # 反向漂移：client 传 newer_base · DB 现值为 baseline · 必须 409
    stale_newer = _seed_canvas("c_CB_P5_13_newer", title="newer-drift")
    stale_newer["base_updated_at"] = newer_base
    with pytest.raises(CanvasConflictError) as exc_info:
        save_canvas_db(stale_newer)
    # 409 契约字节等价（与 CB-P5-10 老测试统一 detail shape）
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert "message" in detail


def test_save_canvas_db_revision_monotonic_after_success(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """T122 · CB-P5-13 承接 · revision 单调递增确认。

    每次 `save_canvas_db` 成功 · canvas["revision"] 严格 +1（不跳跃 · 不倒退）。
    连续三次写入 → 0 → 1 → 2 → 3。
    """

    from app.db.canvas_writer import save_canvas_db
    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)

    canvas = _seed_canvas("c_CB_P5_13_rev", revision=0)
    save_canvas_db(canvas)
    assert canvas["revision"] == 1

    # 第二次：用刚刚的新基线做 base
    canvas2 = _seed_canvas("c_CB_P5_13_rev", title="rev-2", revision=1)
    canvas2["base_updated_at"] = canvas["base_updated_at"]
    save_canvas_db(canvas2)
    assert canvas2["revision"] == 2

    # 第三次
    canvas3 = _seed_canvas("c_CB_P5_13_rev", title="rev-3", revision=2)
    canvas3["base_updated_at"] = canvas2["base_updated_at"]
    save_canvas_db(canvas3)
    assert canvas3["revision"] == 3

    # DB 表列 revision 与 canvas dict 一致
    engine = get_engine()
    with engine.connect() as conn:
        db_rev = conn.execute(
            select(t.canvases.c.revision).where(
                t.canvases.c.legacy_id == "c_CB_P5_13_rev"
            )
        ).scalar_one()
    assert db_rev == 3, "DB 表列 revision 应与 canvas dict 严格一致"
