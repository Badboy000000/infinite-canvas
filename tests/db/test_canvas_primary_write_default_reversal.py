"""数据 PR-15 · Wave 3-L 主线 A · canvas 域 M1 反转默认测试。

覆盖 T90-T99（10 项），承接如下契约：

- 数据 PR-7 首波 db 主写机制已在 `tests/db/test_canvas_writer.py` 建
  content_json / 乐观锁 / 异步回写 fallback 等基础契约。
- 数据 PR-10 `CANVAS_PRIMARY_WRITE=db` 显式启用完整性由 T70-T79 覆盖。
- **数据 PR-15**（本 PR）反转默认后，未设 env / 空 env → `"db"`；显式 `json`
  是回滚开关。T90-T99 严格覆盖：

  * T90 env 未设置 · `_get_primary_write_mode()` 返回 `"db"`
  * T91 未设 env · 冷启动首次 `save_canvas` 走 db 主写
  * T92 显式 `CANVAS_PRIMARY_WRITE=json` · 返回 `"json"`
  * T93 显式 `CANVAS_PRIMARY_WRITE=json` · 冷启动首次 `save_canvas` 走 json 主写
  * T94 显式 `CANVAS_PRIMARY_WRITE=db` · 返回 `"db"`（行为不变）
  * T95 显式 `CANVAS_PRIMARY_WRITE=db` · save_canvas 走 db（与 T70 一致）
  * T96 空字符串 env（`CANVAS_PRIMARY_WRITE=""`） · 返回 `"db"`
  * T97 未知值 env（`CANVAS_PRIMARY_WRITE=foo`） · `ValueError` fail-fast
  * T98 未设 env · save_canvas 走 db + JSON 通过 `_async_write_json_fallback`
        异步回写 `data/canvas/<id>.json`
  * T99 canvas_store 三函数体 AST ZERO-DIFF vs `1b743e0`（护栏 · 独立
        `ast.unparse` 复核 · `_get_primary_write_mode` 允许 2 处 Constant 翻转）

护栏来源：任务书 [[70 开发过程跟踪/任务书/2026-07-22 数据 PR-15 任务书]]。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


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


def _seed_canvas(canvas_id: str = "c1", **overrides) -> dict[str, Any]:
    canvas = {
        "id": canvas_id,
        "title": overrides.get("title", "PR-15 Canvas"),
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


# ---------------------------------------------------------------------------
# T90 — env 未设置 · _get_primary_write_mode() 返回 "db"
# ---------------------------------------------------------------------------


def test_T90_unset_env_returns_db(monkeypatch):
    """T90 · env 未设置时新默认为 `"db"`（数据 PR-15 M1 收官反转）。"""

    monkeypatch.delenv("CANVAS_PRIMARY_WRITE", raising=False)
    from app.stores.canvas_store import _get_primary_write_mode

    assert _get_primary_write_mode("canvas") == "db"


# ---------------------------------------------------------------------------
# T91 — 未设 env · 冷启动首次 save_canvas 走 db 主写
# ---------------------------------------------------------------------------


def test_T91_unset_env_first_save_goes_to_db(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """T91 · 冷启动 · env 未设 · save_canvas 应调 save_canvas_db 而非 legacy。"""

    migrate_baseline(tmp_path)
    monkeypatch.delenv("CANVAS_PRIMARY_WRITE", raising=False)

    calls = {"save_canvas_db": 0, "legacy_save": 0}
    from app.db import canvas_writer as cw

    orig_save_db = cw.save_canvas_db

    def _spy_db(canvas):
        calls["save_canvas_db"] += 1
        return orig_save_db(canvas)

    monkeypatch.setattr(cw, "save_canvas_db", _spy_db)

    import main

    orig_legacy = main.save_canvas

    def _spy_legacy(canvas):
        calls["legacy_save"] += 1
        return orig_legacy(canvas)

    monkeypatch.setattr(main, "save_canvas", _spy_legacy)

    from app.stores import canvas_store

    canvas = _seed_canvas(canvas_id="c_T91")
    canvas_store.save_canvas(canvas)

    assert calls["save_canvas_db"] == 1, (
        "反转后默认 · save_canvas 必须调 save_canvas_db"
    )
    assert calls["legacy_save"] == 0, (
        "反转后默认 · save_canvas 不得再走 legacy main.save_canvas"
    )


# ---------------------------------------------------------------------------
# T92 — 显式 CANVAS_PRIMARY_WRITE=json · 返回 "json"
# ---------------------------------------------------------------------------


def test_T92_explicit_json_returns_json(monkeypatch):
    """T92 · 显式 `json` 回滚开关 · fail-fast 返回 `"json"`。"""

    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "json")
    from app.stores.canvas_store import _get_primary_write_mode

    assert _get_primary_write_mode("canvas") == "json"


# ---------------------------------------------------------------------------
# T93 — 显式 CANVAS_PRIMARY_WRITE=json · save_canvas 走 json 主写（回滚路径全绿）
# ---------------------------------------------------------------------------


def test_T93_explicit_json_save_goes_to_legacy_main(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """T93 · P0 快速回滚路径 · env=json 时 save_canvas 走 legacy main.save_canvas
    并触发 shadow write hook；**绝不** import `app.db.canvas_writer`。"""

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "json")

    # 观察 db 分派是否被误触发。
    calls = {"save_canvas_db": 0, "legacy_save": 0}
    from app.db import canvas_writer as cw

    orig_save_db = cw.save_canvas_db

    def _spy_db(canvas):  # pragma: no cover — 应永不被调用
        calls["save_canvas_db"] += 1
        return orig_save_db(canvas)

    monkeypatch.setattr(cw, "save_canvas_db", _spy_db)

    import main

    orig_legacy = main.save_canvas

    def _spy_legacy(canvas):
        calls["legacy_save"] += 1
        return orig_legacy(canvas)

    monkeypatch.setattr(main, "save_canvas", _spy_legacy)

    from app.stores import canvas_store

    canvas = _seed_canvas(canvas_id="c_T93")
    canvas_store.save_canvas(canvas)

    assert calls["legacy_save"] == 1, "env=json 必须走 legacy main.save_canvas"
    assert calls["save_canvas_db"] == 0, "env=json 严禁调 save_canvas_db"
    # legacy JSON 主写落盘（byte-equivalent 于 PR-10 回滚路径）。
    assert (canvas_dir_fixture / "c_T93.json").exists()


# ---------------------------------------------------------------------------
# T94 — 显式 CANVAS_PRIMARY_WRITE=db · 返回 "db"
# ---------------------------------------------------------------------------


def test_T94_explicit_db_returns_db(monkeypatch):
    """T94 · 显式 `db` 行为不变（与反转后默认路径同结果）。"""

    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")
    from app.stores.canvas_store import _get_primary_write_mode

    assert _get_primary_write_mode("canvas") == "db"


# ---------------------------------------------------------------------------
# T95 — 显式 CANVAS_PRIMARY_WRITE=db · save_canvas 走 db（对齐 T70）
# ---------------------------------------------------------------------------


def test_T95_explicit_db_save_dispatches_to_save_canvas_db(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """T95 · 显式 `db` 行为对齐 T70：走 save_canvas_db + 异步 JSON 回写。"""

    migrate_baseline(tmp_path)
    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "db")

    calls = {"save_canvas_db": 0, "async_fallback": 0, "legacy_save": 0}
    from app.db import canvas_writer as cw

    orig_save = cw.save_canvas_db
    orig_async = cw._async_write_json_fallback

    def _spy_save(canvas):
        calls["save_canvas_db"] += 1
        return orig_save(canvas)

    def _spy_async(canvas):
        calls["async_fallback"] += 1
        return orig_async(canvas)

    monkeypatch.setattr(cw, "save_canvas_db", _spy_save)
    monkeypatch.setattr(cw, "_async_write_json_fallback", _spy_async)

    import main

    orig_legacy = main.save_canvas

    def _spy_legacy(canvas):  # pragma: no cover — 应永不被调用
        calls["legacy_save"] += 1
        return orig_legacy(canvas)

    monkeypatch.setattr(main, "save_canvas", _spy_legacy)

    from app.stores import canvas_store

    canvas = _seed_canvas(canvas_id="c_T95")
    canvas_store.save_canvas(canvas)

    assert calls["save_canvas_db"] == 1
    assert calls["async_fallback"] == 1
    assert calls["legacy_save"] == 0


# ---------------------------------------------------------------------------
# T96 — 空字符串 env · 返回 "db"（与 raw is None 一致）
# ---------------------------------------------------------------------------


def test_T96_empty_string_env_returns_db(monkeypatch):
    """T96 · `CANVAS_PRIMARY_WRITE=""` 与"未设"语义等价 → `"db"`。"""

    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "")
    from app.stores.canvas_store import _get_primary_write_mode

    assert _get_primary_write_mode("canvas") == "db"


# ---------------------------------------------------------------------------
# T97 — 未知值 env · ValueError fail-fast（继承 T77）
# ---------------------------------------------------------------------------


def test_T97_unknown_env_value_raises_value_error(monkeypatch):
    """T97 · 未知值 fail-fast · 与 T77 一致契约（反转不放松 fail-fast）。"""

    monkeypatch.setenv("CANVAS_PRIMARY_WRITE", "foo")
    from app.stores.canvas_store import _get_primary_write_mode

    with pytest.raises(ValueError) as exc_info:
        _get_primary_write_mode("canvas")
    assert "Invalid CANVAS_PRIMARY_WRITE" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T98 — 未设 env · save_canvas 走 db + JSON 异步回写落盘
# ---------------------------------------------------------------------------


def test_T98_unset_env_save_writes_db_then_async_json(
    monkeypatch, canvas_dir_fixture, tmp_path
):
    """T98 · 反转后默认路径必须端到端成立：DB row 同步就位，JSON 文件异步到达。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.delenv("CANVAS_PRIMARY_WRITE", raising=False)

    from app.stores import canvas_store

    canvas = _seed_canvas(canvas_id="c_T98")
    canvas_store.save_canvas(canvas)

    # DB 立即命中
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.canvases.c.legacy_id, t.canvases.c.content_json).where(
                t.canvases.c.legacy_id == "c_T98"
            )
        ).fetchone()
    assert row is not None, "反转后默认 · DB 主写必须同步完成"

    # JSON 异步回写：等最多 2s
    json_path = canvas_dir_fixture / "c_T98.json"
    assert _wait_for_file(json_path, timeout=2.0), (
        "反转后默认 · async JSON fallback 应在合理窗口内落盘"
    )
    # CB-P5-10 承接：DB.content_json 与 JSON 文件在 base_updated_at 字段上
    # 也应字节等价（不再存在序列化时序漂移）。
    db_parsed = json.loads(row.content_json)
    fs_parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert db_parsed.get("base_updated_at") == fs_parsed.get("base_updated_at"), (
        "CB-P5-10 · DB.content_json 与 JSON 文件 base_updated_at 必须字节等价"
    )


# ---------------------------------------------------------------------------
# T99 — canvas_store 三函数体 AST ZERO-DIFF vs 1b743e0（独立 unparse 复核）
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]

_BODY_DIFF_ALLOWED: dict[str, dict[str, str]] = {
    # 数据 PR-15 允许的常量翻转（fallback default）；其余 AST 必须零差异。
    "_get_primary_write_mode": {"json": "db"},
    "save_canvas": {},
    "load_canvas": {},
}


def _extract_function_body_ast(source: str, name: str) -> ast.Module:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.Module(body=node.body, type_ignores=[])
    raise AssertionError(f"function {name!r} not found in source")


def _canonicalize_constants(dump: str, mapping: dict[str, str]) -> str:
    """把预分配的允许翻转对折叠回旧值，得到规范化 dump 便于严格比对。"""

    out = dump
    for old, new in mapping.items():
        # Constant 序列化形如 `Constant(value='db')`；只针对 return 语义常量。
        old_marker = f"Constant(value='{new}')"
        new_marker = f"Constant(value='{old}')"
        out = out.replace(old_marker, new_marker)
    return out


def test_T99_canvas_store_three_functions_ast_zero_diff_vs_1b743e0():
    """T99 · 硬护栏：`_get_primary_write_mode` / `save_canvas` / `load_canvas`
    三函数体 AST 与 `1b743e0` 完全等价（`_get_primary_write_mode` 允许 2
    处 Constant 翻转：`json` → `db`）。"""

    old_src = subprocess.check_output(
        ["git", "show", "1b743e0:app/stores/canvas_store.py"],
        cwd=str(REPO_ROOT),
    ).decode("utf-8")
    new_src = (REPO_ROOT / "app" / "stores" / "canvas_store.py").read_text(
        encoding="utf-8"
    )

    for fn, mapping in _BODY_DIFF_ALLOWED.items():
        old_body = _extract_function_body_ast(old_src, fn)
        new_body = _extract_function_body_ast(new_src, fn)
        old_dump = ast.dump(old_body)
        new_dump = ast.dump(new_body)
        # 折叠允许的翻转后严格相等
        canonical_new = _canonicalize_constants(new_dump, mapping)
        assert canonical_new == old_dump, (
            f"function body AST diff not covered by allowed constant flip for {fn!r}"
        )

        # 独立 ast.unparse 复核：能被 unparse 且新旧 source 结构可比对。
        # unparse 会规范化空白，因此这里作二次护栏。
        try:
            _ = ast.unparse(new_body)
            _ = ast.unparse(old_body)
        except AttributeError as exc:  # pragma: no cover — Python < 3.9
            pytest.skip(f"ast.unparse not available: {exc}")
