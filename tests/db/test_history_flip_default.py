"""数据 PR-12 · GenerationHistory 主写机制 flip 抗回归防线（P0）。

**本 PR 不切默认**（GM-22 硬约束 · 默认 `HISTORY_PRIMARY_WRITE=json`）。
本文件的角色：

- 建立 `save_to_history` AST byte-identical pin（**独立于 `test_save_functions_frozen.py`
  的 5 项 save 保护列表** · 任务书明确要求 · 便于未来 flip 默认独立 PR
  承接时可直接更新 pin 而不打散 5 项保护）。
- pin baseline `97cd7a0`（worktree 分支起点 · PR-12 landing 前 · 与 shallow
  clone 契约一致）。
- 冻结区 3 项断言与 `test_frozen_zone_untouched.py` 已覆盖 · 本 PR 零触碰。

任务书护栏来源：任务书 · Wave 3-N.6 Batch 2 主线 B · 数据 PR-12 P0 硬约束 #2
"5 save AST 5/5 vs 31e0d3d · save_to_history 独立 pin"。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"

# `save_to_history` 独立 pin baseline · Wave 3-N.6 Batch 2 主线 B PR-12 开工前
# worktree 分支的最后一个 landing commit。GM-22 反转独立 PR 承接时更新此值。
BASELINE_REF = "97cd7a0"


def _load_baseline_tree(baseline_ref: str) -> ast.Module:
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:main.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"baseline ref {baseline_ref} unavailable")
    return ast.parse(result.stdout)


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def test_save_to_history_body_ast_zero_diff_vs_baseline():
    """`main.py:save_to_history` 函数体自 baseline `97cd7a0` 以来 AST
    byte-equivalent（数据 PR-12 P0 硬约束 #2 · 独立 pin 与 5 项 save 保护
    列表分离）。

    修复流程（若本测试挂了）：
    1. 确认改动是**故意**的（如 GM-22 反转独立 PR 承接需触碰）→ 更新
       `BASELINE_REF` 到 landing commit + 同步 KB
    2. 若非故意 → 回退对应 diff 段
    """

    baseline_tree = _load_baseline_tree(BASELINE_REF)
    current_tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

    b_node = _find_func(baseline_tree, "save_to_history")
    c_node = _find_func(current_tree, "save_to_history")

    assert b_node is not None, f"baseline save_to_history missing at {BASELINE_REF}"
    assert c_node is not None, "current save_to_history missing"
    assert ast.dump(b_node, include_attributes=False) == ast.dump(
        c_node, include_attributes=False
    ), (
        f"数据 PR-12 P0-2 契约破裂：main.py:save_to_history 函数体自 baseline "
        f"{BASELINE_REF} 以来被触碰；若为故意改动，须更新 BASELINE_REF 并同步 KB"
    )


def test_history_primary_write_default_is_json():
    """数据 PR-12 只加机制不切默认（GM-22 硬约束）· 未设 env · 默认 `"json"`。"""

    from app.stores.history_store import _get_primary_write_mode

    import os

    old = os.environ.pop("HISTORY_PRIMARY_WRITE", None)
    try:
        assert _get_primary_write_mode("generation_history") == "json"
    finally:
        if old is not None:
            os.environ["HISTORY_PRIMARY_WRITE"] = old


def test_main_history_primary_write_constant_present():
    """`main.HISTORY_PRIMARY_WRITE` 常量存在且默认 `"json"`。"""

    import main

    assert hasattr(main, "HISTORY_PRIMARY_WRITE")
    # 值来自 env · 默认 "json"（未设时）· 允许 "db" 显式启用
    assert main.HISTORY_PRIMARY_WRITE in {"json", "db"}
