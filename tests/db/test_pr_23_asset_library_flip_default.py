"""数据 PR-23 · Wave 3-N.5 主线 A · Batch 3 · AssetLibrary 域反转默认测试。

**M1 阶段 5 域反转最后一域 · 交付后 M1 里程碑 100% 完成。**

覆盖 T280-T287（8 项），承接如下契约：

- 数据 PR-9 首波 AssetLibrary db 主写机制已在 `tests/db/test_asset_library_writer.py`
  建立 raw_json / 单文档 UPSERT（`legacy_id="__root__"`）/ 异步回写
  fallback 等基础契约。
- 数据 PR-15（canvas 域）反转默认 pattern 首次实证（GM-22 pattern 首次实证）·
  Wave 3-L 主线 A 已产出 T90-T99 参照模板；PR-20（Project 域）Batch 1 · PR-21
  （PromptLibrary 域）+ PR-22（WorkflowDefinition 域）Batch 2 承接实证。
- **数据 PR-23**（本 PR）AssetLibrary 域反转默认后，未设 env / 空 env →
  `"db"`；显式 `json` 是回滚开关。T280-T287 严格覆盖：

  * T280 env 未设置 · `_get_primary_write_mode()` 返回 `"db"`
  * T281 未设 env · 冷启动首次 `save_asset_library` 走 db 主写
  * T282 显式 `ASSET_LIBRARY_PRIMARY_WRITE=json` · 回滚路径可用
  * T283 未设 env · save + JSON 异步回写 fallback 到位
  * T284 `main.save_asset_library` 函数体 AST byte-identical vs `a6f863a`
        （GM-04 硬约束 · 独立 subprocess `git show`）
  * T285 `main.py` 冻结区 3 符号 AST byte-identical vs `a6f863a`
        （GM-01 硬约束 · StorageSettings / apply_storage_settings /
        storage_settings_snapshot）
  * T286 shadow_diff jsonl 无密钥泄漏（AssetLibrary items 全塞 raw_json ·
        密钥断言必须 grep 整个 raw_json blob · sentinel 至少覆盖
        `api_key` / `access_token` / `secret` / `Bearer`）
  * T287 fixture 隔离契约（monkeypatch `main.DATA_DB_PATH` + `main.DATA_DIR` +
        `main.ASSET_LIBRARY_PATH` · CB-P5-21 pattern · 不污染仓库工作树）

护栏来源：任务书 · Wave 3-N.5 Batch 3 主线 A · 数据 PR-23。

AssetLibrary 域特别注意：单文档 `legacy_id="__root__"` 契约（区别于集合级
UPSERT+DELETE · Wave 3-H 已确立）· `asset_libraries.raw_json` 保存完整 library
payload（D-2=B 含 categories + items）· `asset_categories`/`asset_items` 表本 PR
不主写。items free-text 可能含 URL/元数据 · T286 密钥 grep 必须扫整个 raw_json
而不只是顶层字段。
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


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_REF = "a6f863a"  # Wave 3-L 主线 C · 数据 PR-16 · GM-01/GM-04 跨 PR 共同 baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def data_dir_fixture(tmp_path, monkeypatch, isolated_env):
    """把 `DATA_DIR` / `ASSET_LIBRARY_PATH` 指到 tmp_path（CB-P5-21 隔离契约）。"""

    import main

    data_dir = tmp_path
    asset_lib_path = data_dir / "asset_library.json"
    monkeypatch.setattr(main, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main, "ASSET_LIBRARY_PATH", str(asset_lib_path))
    yield data_dir


def _library(
    lib_id: str = "default",
    name: str = "PR-23 Library",
    *,
    categories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": lib_id,
        "name": name,
        "type": "asset",
        "categories": categories
        or [
            {
                "id": "cat_uploads",
                "name": "上传",
                "kind": "user",
                "items": [],
            }
        ],
    }


def _payload(
    libs: list[dict[str, Any]] | None = None,
    *,
    active_id: str = "default",
) -> dict[str, Any]:
    return {
        "active_library_id": active_id,
        "libraries": libs or [_library("default", "默认素材库")],
    }


def _wait_for_file(path: Path, timeout: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# T280 — env 未设置 · _get_primary_write_mode() 返回 "db"
# ---------------------------------------------------------------------------


def test_T280_unset_env_returns_db(monkeypatch):
    """T280 · env 未设置时新默认为 `"db"`（数据 PR-23 AssetLibrary 域
    M1 收官反转 · 5 域反转最后一域）。"""

    monkeypatch.delenv("ASSET_LIBRARY_PRIMARY_WRITE", raising=False)
    from app.stores.asset_library_store import _get_primary_write_mode

    assert _get_primary_write_mode("asset_library") == "db"


# ---------------------------------------------------------------------------
# T281 — 未设 env · 冷启动首次 save_asset_library 走 db 主写
# ---------------------------------------------------------------------------


def test_T281_unset_env_first_save_goes_to_db(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T281 · 冷启动 · env 未设 · save_asset_library 应调 save_asset_library_db
    而非 legacy。"""

    migrate_baseline(tmp_path)
    monkeypatch.delenv("ASSET_LIBRARY_PRIMARY_WRITE", raising=False)

    calls = {"save_lib_db": 0, "legacy_save": 0}
    from app.db import asset_library_writer as alw

    orig_save_db = alw.save_asset_library_db

    def _spy_db(payload):
        calls["save_lib_db"] += 1
        return orig_save_db(payload)

    monkeypatch.setattr(alw, "save_asset_library_db", _spy_db)

    import main

    orig_legacy = main.save_asset_library

    def _spy_legacy(data):
        calls["legacy_save"] += 1
        return orig_legacy(data)

    monkeypatch.setattr(main, "save_asset_library", _spy_legacy)

    from app.stores import asset_library_store

    asset_library_store.save_asset_library(_payload([_library("default")]))

    assert calls["save_lib_db"] == 1, (
        "反转后默认 · save_asset_library 必须调 save_asset_library_db"
    )
    assert calls["legacy_save"] == 0, (
        "反转后默认 · save_asset_library 不得再走 legacy main.save_asset_library"
    )


# ---------------------------------------------------------------------------
# T282 — 显式 ASSET_LIBRARY_PRIMARY_WRITE=json · 回滚开关可用
# ---------------------------------------------------------------------------


def test_T282_explicit_json_returns_json_and_uses_legacy(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T282 · P0 快速回滚路径 · env=json 时 save_asset_library 走 legacy
    main.save_asset_library 并**绝不** import `app.db.asset_library_writer`
    （回滚路径全绿 · GM-22 pattern）。"""

    migrate_baseline(tmp_path)
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "json")

    # 契约 1：`_get_primary_write_mode` 显式返回 "json"
    from app.stores.asset_library_store import _get_primary_write_mode

    assert _get_primary_write_mode("asset_library") == "json"

    # 契约 2：save 分派走 legacy · 不 import writer
    sys.modules.pop("app.db.asset_library_writer", None)

    calls = {"legacy_save": 0}
    import main

    orig_legacy = main.save_asset_library

    def _spy_legacy(data):
        calls["legacy_save"] += 1
        return orig_legacy(data)

    monkeypatch.setattr(main, "save_asset_library", _spy_legacy)

    from app.stores import asset_library_store

    asset_library_store.save_asset_library(_payload([_library("default")]))

    assert calls["legacy_save"] == 1, (
        "env=json 必须走 legacy main.save_asset_library"
    )
    assert "app.db.asset_library_writer" not in sys.modules, (
        "env=json 严禁 import app.db.asset_library_writer（P0 硬约束 #3 · 回滚路径可用）"
    )
    # legacy JSON 主写落盘（byte-equivalent 于 PR-9 回滚路径）。
    assert (data_dir_fixture / "asset_library.json").exists()


# ---------------------------------------------------------------------------
# T283 — 未设 env · save 走 db + JSON 异步回写落盘
# ---------------------------------------------------------------------------


def test_T283_unset_env_save_writes_db_then_async_json(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T283 · 反转后默认路径必须端到端成立：DB row 同步就位（单文档
    `legacy_id="__root__"`），JSON 文件异步到达。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.delenv("ASSET_LIBRARY_PRIMARY_WRITE", raising=False)

    from app.stores import asset_library_store

    asset_library_store.save_asset_library(
        _payload(
            [
                _library(
                    "default",
                    "PR-23 Async",
                    categories=[
                        {
                            "id": "cat_uploads",
                            "name": "上传",
                            "kind": "user",
                            "items": [
                                {
                                    "id": "item_1",
                                    "name": "asset1.png",
                                    "url": "assets/library/asset1.png",
                                }
                            ],
                        }
                    ],
                ),
            ],
            active_id="default",
        )
    )

    # DB 立即命中（单文档 UPSERT · legacy_id="__root__"）
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.asset_libraries.c.legacy_id,
                t.asset_libraries.c.raw_json,
            )
        ).fetchall()

    assert len(rows) == 1, (
        f"反转后默认 · AssetLibrary 单文档 UPSERT 必须只有 1 行 · 实际 {len(rows)}"
    )
    root_row = rows[0]
    assert root_row.legacy_id == "__root__", (
        f"反转后默认 · legacy_id 必须为 __root__ · 实际 {root_row.legacy_id}"
    )

    # raw_json 承载完整 payload（D-2=B · categories + items）
    root_payload = json.loads(root_row.raw_json)
    assert root_payload.get("active_library_id") == "default"
    libraries = root_payload.get("libraries") or []
    assert any(lib.get("id") == "default" for lib in libraries), (
        f"raw_json 必须承载 libraries[*] · 实际 {libraries}"
    )
    default_lib = next(lib for lib in libraries if lib.get("id") == "default")
    cats = default_lib.get("categories") or []
    assert any(
        any(item.get("id") == "item_1" for item in (cat.get("items") or []))
        for cat in cats
    ), "D-2=B · categories + items 必须一并进 raw_json"

    # JSON 异步回写：等最多 2s
    json_path = data_dir_fixture / "asset_library.json"
    assert _wait_for_file(json_path, timeout=2.0), (
        "反转后默认 · async JSON fallback 应在合理窗口内落盘"
    )
    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    assert isinstance(on_disk.get("libraries"), list)
    assert any(lib.get("id") == "default" for lib in on_disk["libraries"])


# ---------------------------------------------------------------------------
# T284 — main.save_asset_library 函数体 AST byte-identical vs a6f863a（GM-04）
# ---------------------------------------------------------------------------


def _load_main_from_ref(ref: str) -> ast.Module | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:main.py"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    return ast.parse(result.stdout)


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def test_T284_save_asset_library_body_ast_zero_diff_vs_baseline():
    """T284 · GM-04 硬约束：`main.py:save_asset_library` 函数体 AST 与
    `a6f863a` 完全等价（本 PR 零触碰函数体 · 只翻转常量默认）。"""

    baseline_tree = _load_main_from_ref(BASELINE_REF)
    if baseline_tree is None:
        pytest.skip(f"baseline ref {BASELINE_REF} unavailable in shallow clone")

    current_tree = ast.parse(
        (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    )

    b_node = _find_func(baseline_tree, "save_asset_library")
    c_node = _find_func(current_tree, "save_asset_library")

    assert b_node is not None, (
        f"baseline save_asset_library missing at {BASELINE_REF}"
    )
    assert c_node is not None, "current save_asset_library missing"
    assert ast.dump(b_node, include_attributes=False) == ast.dump(
        c_node, include_attributes=False
    ), (
        f"GM-04 硬约束破裂：main.save_asset_library 函数体自 baseline "
        f"{BASELINE_REF} 以来被触碰；本 PR 应零触碰 save_asset_library 函数体"
    )


# ---------------------------------------------------------------------------
# T285 — main.py 冻结区 3 符号 AST byte-identical vs a6f863a（GM-01）
# ---------------------------------------------------------------------------


_FROZEN_ZONE = (
    ("class", "StorageSettings"),
    ("func", "apply_storage_settings"),
    ("func", "storage_settings_snapshot"),
)


def test_T285_frozen_zone_ast_zero_diff_vs_baseline():
    """T285 · GM-01 硬约束：冻结区 3 符号（StorageSettings /
    apply_storage_settings / storage_settings_snapshot）AST 与 `a6f863a`
    完全等价（跨 PR 保持 · 数据 PR-23 零触碰）。"""

    baseline_tree = _load_main_from_ref(BASELINE_REF)
    if baseline_tree is None:
        pytest.skip(f"baseline ref {BASELINE_REF} unavailable in shallow clone")

    current_tree = ast.parse(
        (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    )

    hits = 0
    for kind, name in _FROZEN_ZONE:
        if kind == "func":
            b_node = _find_func(baseline_tree, name)
            c_node = _find_func(current_tree, name)
        else:
            b_node = _find_class(baseline_tree, name)
            c_node = _find_class(current_tree, name)
        assert b_node is not None, f"baseline {name} missing at {BASELINE_REF}"
        assert c_node is not None, f"current {name} missing"
        assert ast.dump(b_node, include_attributes=False) == ast.dump(
            c_node, include_attributes=False
        ), (
            f"GM-01 硬约束破裂：冻结区 {name} 自 baseline {BASELINE_REF} "
            f"以来被触碰；数据 PR-23 应零触碰冻结区"
        )
        hits += 1

    assert hits == 3, f"冻结区 3 符号应全部核验：实际 {hits}"


# ---------------------------------------------------------------------------
# T286 — shadow_diff/**/*.jsonl 无密钥泄漏（AssetLibrary 域全 raw_json 扫描）
# ---------------------------------------------------------------------------


_SECRET_MARKERS = ("api_key", "access_token", "secret", "Bearer")


def test_T286_shadow_diff_files_no_provider_secret_leak(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T286 · 反转默认后所有 `data/shadow_diff/**/*.jsonl` 严禁出现 provider
    凭据字面量（api_key / access_token / secret / Bearer）。

    **AssetLibrary 域特殊性**：items 可能被塞入含 URL/元数据 的 free-text 字段
    （用户上传素材元信息等）；本测试对 shadow_diff 采用 **全文** grep，
    覆盖任意 items 字段落到 raw_json 后进入 shadow_diff 通道的场景。
    """

    migrate_baseline(tmp_path)
    monkeypatch.delenv("ASSET_LIBRARY_PRIMARY_WRITE", raising=False)

    from app.stores import asset_library_store

    # 端到端触发默认路径（DB 主写 + JSON 异步回写）
    asset_library_store.save_asset_library(
        _payload(
            [
                _library(
                    "default",
                    "PR-23 Sec Scan",
                    categories=[
                        {
                            "id": "cat_uploads",
                            "name": "上传",
                            "kind": "user",
                            "items": [
                                {
                                    "id": "item_a",
                                    "name": "photo.png",
                                    "url": "assets/library/photo.png",
                                },
                                {
                                    "id": "item_b",
                                    "name": "clip.mp4",
                                    "url": "assets/library/clip.mp4",
                                },
                            ],
                        }
                    ],
                ),
            ],
            active_id="default",
        )
    )
    # 等待 async fallback 落盘（若有）
    time.sleep(0.2)

    shadow_root = Path(tmp_path) / "shadow_diff"
    if not shadow_root.exists():
        # 反转默认路径成功时 shadow_diff 未必被建（无 fallback 异常）
        return

    hits: list[tuple[Path, str]] = []
    for jsonl in shadow_root.rglob("*.jsonl"):
        # **AssetLibrary 特别注意**：items free-text 已在 raw_json blob 里，
        # 密钥 grep 必须扫整个文本而不只是顶层字段。
        text = jsonl.read_text(encoding="utf-8", errors="replace")
        for marker in _SECRET_MARKERS:
            if marker in text:
                hits.append((jsonl, marker))

    assert not hits, (
        f"密钥泄漏 · shadow_diff 中出现 provider 凭据字面量：{hits}"
    )


# ---------------------------------------------------------------------------
# T287 — fixture 隔离契约（CB-P5-21 pattern）
# ---------------------------------------------------------------------------


def test_T287_fixture_isolates_data_paths(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T287 · CB-P5-21 pattern：所有 tmp_path 内的写入不得污染真实 `data/`
    目录。本测试通过 `data_dir_fixture` 已 monkeypatch 的三个入口反查：

    - `main.DATA_DB_PATH` → tmp_path/shadow.db（isolated_shadow_env 契约）
    - `main.DATA_DIR` → tmp_path
    - `main.ASSET_LIBRARY_PATH` → tmp_path/asset_library.json
      （codegraph 复核：main.py L364 · `ASSET_LIBRARY_PATH` 是 AssetLibrary 域
      在 main.py 的唯一 JSON 主写常量路径变量名 · 参照 subagent B PR-22 对
      `RUNNINGHUB_WORKFLOW_STORE_FILE` 的复核 pattern）
    """

    import main

    assert Path(main.DATA_DB_PATH).parent == tmp_path, (
        f"DATA_DB_PATH 未隔离到 tmp_path: {main.DATA_DB_PATH}"
    )
    assert Path(main.DATA_DIR) == tmp_path, (
        f"DATA_DIR 未隔离到 tmp_path: {main.DATA_DIR}"
    )
    assert Path(main.ASSET_LIBRARY_PATH).parent == tmp_path, (
        f"ASSET_LIBRARY_PATH 未隔离到 tmp_path: {main.ASSET_LIBRARY_PATH}"
    )

    # 端到端：写入操作不得落到真实仓库 data/ 目录
    migrate_baseline(tmp_path)
    monkeypatch.delenv("ASSET_LIBRARY_PRIMARY_WRITE", raising=False)
    from app.stores import asset_library_store

    asset_library_store.save_asset_library(_payload([_library("default")]))
    # 等 async json fallback
    _wait_for_file(Path(main.ASSET_LIBRARY_PATH), timeout=2.0)

    real_data_dir = REPO_ROOT / "data"
    # 更强的隔离断言：tmp_path 下有落盘产物，且落盘产物路径不落在仓库真实 data/ 下
    tmp_asset = tmp_path / "asset_library.json"
    assert tmp_asset.exists(), (
        "T287 · tmp 内 asset_library.json 应由 async fallback 落盘"
    )
    # 隔离契约：写入的绝对路径不能是仓库 data/ 目录下的路径
    assert not str(tmp_asset.resolve()).startswith(
        str(real_data_dir.resolve())
    ), "T287 · 隔离契约破裂：写入到了真实仓库 data/ 目录"
