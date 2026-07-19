"""数据 PR-6 · Canvas 内容 shadow 短窗双写契约测试。

覆盖点：

1. `SHADOW_WRITE_CANVAS=false` 默认关闭 → `save_canvas` 磁盘产物字节等价、
   不 hit DB engine、不落 diff 文件。
2. `SHADOW_WRITE_CANVAS=true` → `canvases.content_hash` = `sha256(content_json)`
   字节精确；`content_json` = 磁盘 `json.dump(..., indent=2)` 输出字节等价。
3. `revision` / `base_updated_at` 从 canvas dict 抽取正确进 DB。
4. shadow write 内部异常 → warning + JSON 主写仍成功；主写路径永不感知。
5. 大画布（≥ 1MB）hash 计算 + 写入 P95 < 500ms。
6. 幂等：同一 canvas 连续两次 save，`canvases` 表行数不新增（upsert on legacy_id）。
7. `main.py:save_canvas` 函数体 AST byte-equivalent 未被本 PR 触碰。
8. `is_shadow_write_enabled` 门禁语义（truthy 值枚举）。
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def canvas_dir_fixture(tmp_path, monkeypatch, isolated_env):
    """把 `CANVAS_DIR` 指到 tmp_path/canvases；写 seed canvas 文件为空目录。"""

    import main

    canvas_dir = tmp_path / "canvases"
    canvas_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(main, "CANVAS_DIR", str(canvas_dir))
    yield canvas_dir


def _seed_canvas(canvas_dir: Path, canvas_id: str = "c1", **overrides) -> dict:
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
        "revision": overrides.get("revision", 3),
        "base_updated_at": overrides.get("base_updated_at", "2026-07-19T00:00:00Z"),
        "nodes": overrides.get("nodes", []),
        "connections": overrides.get("connections", []),
    }
    return canvas


def test_shadow_write_disabled_default_is_zero_effect(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`SHADOW_WRITE_CANVAS=false` 时 save_canvas 主写 + 不 hit DB + 不落 diff。"""

    from app.stores import canvas_store

    monkeypatch.delenv("SHADOW_WRITE_CANVAS", raising=False)

    from app.db import engine as db_engine

    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when disabled")

    monkeypatch.setattr(db_engine, "get_engine", _fail)

    canvas = _seed_canvas(canvas_dir_fixture)
    canvas_store.save_canvas(canvas)

    # 主写落盘存在，且是有效 JSON
    saved_path = canvas_dir_fixture / "c1.json"
    assert saved_path.exists()
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    assert loaded["id"] == "c1"

    # 没有 hit engine
    assert hits["count"] == 0
    # 没有落 diff 目录
    diff_root = tmp_path / "shadow_diff" / "canvas_write"
    assert not diff_root.exists()


def test_shadow_write_enabled_upserts_with_content_hash(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """`SHADOW_WRITE_CANVAS=true` → canvases.content_hash = sha256(content_json)。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import canvas_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("SHADOW_WRITE_CANVAS", "true")

    canvas = _seed_canvas(canvas_dir_fixture)
    canvas_store.save_canvas(canvas)

    saved_path = canvas_dir_fixture / "c1.json"
    disk_bytes = saved_path.read_bytes()
    disk_hash = hashlib.sha256(disk_bytes).hexdigest()

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(
                t.canvases.c.legacy_id,
                t.canvases.c.content_json,
                t.canvases.c.content_hash,
                t.canvases.c.revision,
                t.canvases.c.base_updated_at,
                t.canvases.c.title,
            ).where(t.canvases.c.legacy_id == "c1")
        ).fetchone()

    assert row is not None
    assert row.legacy_id == "c1"
    assert row.title == "Canvas Title"
    assert row.revision == 3
    assert row.base_updated_at == "2026-07-19T00:00:00Z"
    # content_hash 精确等于 sha256(content_json)
    assert row.content_hash == hashlib.sha256(
        row.content_json.encode("utf-8")
    ).hexdigest()
    # 且等于 sha256(disk_bytes) —— main.save_canvas 落盘字节等价
    assert row.content_hash == disk_hash


def test_shadow_write_failure_does_not_block_json_primary_write(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """shadow write 内部 raise → warning + JSON 主写仍成功。"""

    from app.stores import canvas_store

    monkeypatch.setenv("SHADOW_WRITE_CANVAS", "true")

    # 强制 shadow write 内部 raise
    def _boom(*a, **kw):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr("app.shadow_write.runner._upsert_canvas", _boom)

    canvas = _seed_canvas(canvas_dir_fixture, canvas_id="c2")
    canvas_store.save_canvas(canvas)

    saved_path = canvas_dir_fixture / "c2.json"
    assert saved_path.exists()
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    assert loaded["id"] == "c2"

    # 失败落 diff jsonl
    diff_dir = tmp_path / "shadow_diff" / "canvas_write"
    files = list(diff_dir.glob("*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["domain"] == "canvas"
    assert rec["legacy_id"] == "c2"
    assert "simulated db failure" in rec["error"]


def test_shadow_write_upsert_idempotent(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """同一 canvas 连续两次 save → canvases 行数 = 1。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import canvas_store
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("SHADOW_WRITE_CANVAS", "true")

    canvas = _seed_canvas(canvas_dir_fixture, canvas_id="c3")
    canvas_store.save_canvas(canvas)
    # 二次写：修改 title → 应该 update 同一行，不新增
    canvas["title"] = "Renamed"
    canvas_store.save_canvas(canvas)

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(t.canvases).where(
                t.canvases.c.legacy_id == "c3"
            )
        ).scalar_one()
        row = conn.execute(
            select(t.canvases.c.title, t.canvases.c.content_hash).where(
                t.canvases.c.legacy_id == "c3"
            )
        ).fetchone()

    assert count == 1
    assert row.title == "Renamed"
    # content_hash 已同步更新（走磁盘字节等价）
    saved_path = canvas_dir_fixture / "c3.json"
    disk_hash = hashlib.sha256(saved_path.read_bytes()).hexdigest()
    assert row.content_hash == disk_hash


def test_shadow_write_large_canvas_latency_under_bound(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """≥ 1MB canvas hash + upsert P95 < 500ms（治理方案 §PR-6 P1）。"""

    from app.stores import canvas_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("SHADOW_WRITE_CANVAS", "true")

    # 构造 ~1.5MB 的 nodes 数组
    big_nodes = [{"id": f"n{i}", "data": "x" * 128} for i in range(10000)]
    canvas = _seed_canvas(canvas_dir_fixture, canvas_id="c_big", nodes=big_nodes)

    start = time.perf_counter()
    canvas_store.save_canvas(canvas)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"shadow_write for 1MB canvas too slow: {elapsed:.3f}s"


def test_is_shadow_write_enabled_defaults_false_and_truthy_toggle(monkeypatch):
    from app.shadow_write.runner import is_shadow_write_enabled

    monkeypatch.delenv("SHADOW_WRITE_CANVAS", raising=False)
    assert is_shadow_write_enabled("canvas") is False
    assert is_shadow_write_enabled("unknown_domain") is False

    for value in ("1", "true", "TRUE", "yes", "on", "Enabled"):
        monkeypatch.setenv("SHADOW_WRITE_CANVAS", value)
        assert is_shadow_write_enabled("canvas") is True, value
    for value in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv("SHADOW_WRITE_CANVAS", value)
        assert is_shadow_write_enabled("canvas") is False, value


def test_save_canvas_frozen_zone_byte_equivalent():
    """`main.py:save_canvas` 函数体自 baseline `ae50b28` 以来 AST byte-equivalent。

    数据 PR-6 P0 硬约束：不许触碰 `main.save_canvas` 函数体。这里用
    `ast.dump(include_attributes=False)` 对比当前 tree 与 baseline tree。
    """

    import subprocess

    baseline_ref = "ae50b28"
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:main.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"baseline ref {baseline_ref} unavailable")

    baseline_tree = ast.parse(result.stdout)
    current_tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

    def _find(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    b_node = _find(baseline_tree, "save_canvas")
    c_node = _find(current_tree, "save_canvas")
    assert b_node is not None, "baseline save_canvas missing"
    assert c_node is not None, "current save_canvas missing"
    assert ast.dump(b_node, include_attributes=False) == ast.dump(
        c_node, include_attributes=False
    ), "数据 PR-6 触碰了 main.py:save_canvas 函数体（P0 硬约束）"


def test_frozen_zone_ast_still_byte_equivalent():
    """跨 PR-6 冻结区 AST 3/3（StorageSettings / apply_storage_settings /
    storage_settings_snapshot）byte-equivalent。"""

    import subprocess

    baseline_ref = "ba4b87e"
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:main.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"baseline ref {baseline_ref} unavailable")

    baseline_tree = ast.parse(result.stdout)
    current_tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

    def _func(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return ast.dump(node, include_attributes=False)
        return None

    def _cls(tree, name):
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return ast.dump(node, include_attributes=False)
        return None

    assert _func(baseline_tree, "apply_storage_settings") == _func(
        current_tree, "apply_storage_settings"
    )
    assert _func(baseline_tree, "storage_settings_snapshot") == _func(
        current_tree, "storage_settings_snapshot"
    )
    assert _cls(baseline_tree, "StorageSettings") == _cls(
        current_tree, "StorageSettings"
    )
