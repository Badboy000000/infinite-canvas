"""CB-P5-08b · shadow_read canvas normalizer 单-id 判定测试。

数据 PR-15 内嵌承接：`app/shadow_read/canvas_normalizer.py::scope_db_snapshot_to_json`
把 canvas 域的 DB snapshot 收敛到 JSON snapshot 覆盖的 legacy_id 集合内，
避免 `_compare_snapshots` 把 DB 里其它所有 canvas 全部记到 `missing_in_json`
（O(N) 假 missing 噪声）。

- 反审强度：STRONG（有正例 + 反例 + runner 联动 · 直接闭合 CB-P5-08b）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.shadow_read.canvas_normalizer import (
    normalize_json_canvas,
    scope_db_snapshot_to_json,
)


def _make_canvas(legacy_id: str, **overrides: Any) -> dict[str, Any]:
    canvas = {
        "id": legacy_id,
        "title": overrides.get("title", f"Canvas {legacy_id}"),
        "kind": overrides.get("kind", "classic"),
        "project": overrides.get("project", "default"),
        "owner": overrides.get("owner", "tester"),
        "pinned": overrides.get("pinned", False),
        "created_at": overrides.get("created_at", 1000),
        "updated_at": overrides.get("updated_at", 2000),
        "deleted_at": overrides.get("deleted_at", None),
        "revision": overrides.get("revision", 0),
        "base_updated_at": overrides.get("base_updated_at", None),
    }
    return canvas


def _make_db_snapshot(*legacy_ids: str) -> dict[str, dict[str, Any]]:
    return {
        legacy_id: {
            "id": legacy_id,
            "title": f"Canvas {legacy_id}",
            "kind": "classic",
            "project_legacy_id": "default",
            "owner_label": "tester",
            "pinned": False,
            "created_at": None,
            "updated_at": None,
            "deleted_at": None,
            "revision": 0,
            "base_updated_at": None,
        }
        for legacy_id in legacy_ids
    }


# ---------------------------------------------------------------------------
# scope_db_snapshot_to_json — 核心承接函数
# ---------------------------------------------------------------------------


def test_scope_keeps_only_json_ids():
    """DB 有 3 条记录，JSON 只 load 了 1 条 · 收敛后只保留 1 条。"""

    json_snap = normalize_json_canvas(_make_canvas("c1"))
    db_snap = _make_db_snapshot("c1", "c2", "c3")

    scoped = scope_db_snapshot_to_json(json_snap, db_snap)
    assert set(scoped) == {"c1"}
    assert scoped["c1"]["id"] == "c1"


def test_scope_returns_empty_when_json_snapshot_empty():
    """`load_canvas` 极端场景 · payload 无 id · JSON snapshot 为空 · 收敛为空。"""

    json_snap: dict[str, dict[str, Any]] = {}
    db_snap = _make_db_snapshot("c1", "c2")

    scoped = scope_db_snapshot_to_json(json_snap, db_snap)
    assert scoped == {}


def test_scope_preserves_json_id_when_db_missing():
    """DB 没有 JSON id · 收敛后为空（后续 `missing_in_db` 由 diff 引擎判定）。"""

    json_snap = normalize_json_canvas(_make_canvas("c_new"))
    db_snap = _make_db_snapshot("c1", "c2")

    scoped = scope_db_snapshot_to_json(json_snap, db_snap)
    assert scoped == {}


# ---------------------------------------------------------------------------
# runner 联动：反转前 O(N) 噪声 → 反转后单-id
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_shadow(monkeypatch, tmp_path):
    from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline

    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        migrate_baseline(sandbox)
        yield sandbox


def _insert_canvas_row(sandbox_path, legacy_id: str) -> None:
    import datetime as _dt

    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    engine = get_engine()
    now = _dt.datetime.now(_dt.timezone.utc)
    with engine.begin() as conn:
        row = {
            "legacy_id": legacy_id,
            "title": f"Canvas {legacy_id}",
            "kind": "classic",
            "project_legacy_id": "default",
            "owner_label": "tester",
            "pinned": False,
            "content_json": "{}",
            "content_hash": "0" * 64,
            "revision": 0,
            "base_updated_at": None,
            "deleted_at": None,
            "raw_json": "{}",
            "schema_version": "v1_legacy_json",
            "imported_at": now,
            "created_at": now,
            "updated_at": now,
        }
        stmt = sqlite_insert(t.canvases).values(id=generate_id(), **row)
        conn.execute(stmt)


def test_shadow_read_canvas_single_id_no_o_n_noise(
    monkeypatch, isolated_shadow
):
    """CB-P5-08b 硬护栏：DB 有 3 条记录，`run_shadow_read("canvas", <单-id payload>)`
    应只在这一 id 上判定，`missing_in_json` 必然为空（不再把其它 canvas
    误判为丢失）。"""

    monkeypatch.setenv("SHADOW_READ_CANVAS", "true")
    _insert_canvas_row(isolated_shadow, "c1")
    _insert_canvas_row(isolated_shadow, "c2")
    _insert_canvas_row(isolated_shadow, "c3")

    from app.shadow_read.runner import run_shadow_read

    payload = _make_canvas("c1")
    record = run_shadow_read("canvas", payload)

    # DB 里 c1 是空 content_json，但 stable 字段一致（都是默认值），
    # 因此不产生 diff → record 为 None。CB-P5-08b 关键：不再因为 c2 / c3
    # 出现在 DB 但不在 JSON snapshot 里就误判为 missing。
    if record is not None:
        assert record["missing_in_json"] == [], (
            "CB-P5-08b · 单-id load 路径不得把 DB 其它 canvas 记入 missing_in_json"
        )
