"""数据 PR-4 · 冻结区 AST byte-equivalent 断言。

数据 PR-4 承诺 `class StorageSettings` body + `def apply_storage_settings`
body + `def storage_settings_snapshot` body 三处零触碰。除 `tests/files/
test_main_integration.py::test_storage_settings_frozen_functions_match_baseline`
（对 baseline `ba4b87e` 断言）之外，本文件补一条 shadow_read 专题的
byte-equivalent 断言，覆盖同一冻结区、加强抗回归。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"
BASELINE_REF = "ba4b87e"  # `main.py` 冻结区共同基线（文件 PR-2 前）


def _function_source(tree: ast.AST, name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.dump(node, include_attributes=False)
    raise AssertionError(f"function not found: {name}")


def _class_source(tree: ast.AST, name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return ast.dump(node, include_attributes=False)
    raise AssertionError(f"class not found: {name}")


def _baseline_tree() -> ast.AST:
    result = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:main.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"baseline ref {BASELINE_REF} unavailable: {result.stderr}")
    return ast.parse(result.stdout)


def test_storage_settings_frozen_zone_unchanged_by_pr4():
    current = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    baseline = _baseline_tree()
    for func in ("storage_settings_snapshot", "apply_storage_settings"):
        assert _function_source(current, func) == _function_source(baseline, func), (
            f"数据 PR-4 触碰了冻结区 def {func}(...) body"
        )
    assert _class_source(current, "StorageSettings") == _class_source(
        baseline, "StorageSettings"
    ), "数据 PR-4 触碰了冻结区 class StorageSettings body"


def test_pr4_did_not_import_sqlalchemy_at_main_top_level():
    """数据 PR-3 起 `main.py` 顶层 body **不许** import sqlalchemy。数据 PR-4
    的 shadow-read 桥仅通过 `app/stores/*_store.py` 惰性 import
    `app.shadow_read.*`；`main.py` 顶层不应新增 sqlalchemy import。"""

    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    for node in tree.body:  # 只看顶层，不含 if __name__ 内嵌
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("sqlalchemy"), (
                    f"main.py 顶层禁 import sqlalchemy（数据 PR-3 抗回归）"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith("sqlalchemy"), (
                    f"main.py 顶层禁 from sqlalchemy…（数据 PR-3 抗回归）"
                )
