"""任务 PR-3 · AST 断言 —— main.py 内影子挂钩点数量下限。

保护未来 PR 不误删挂钩：statically 断言 `main.py` 中：

1. `_shadow_register(...)` 出现次数 ≥ 6（本 PR 挂钩点数下限）；
2. `_shadow_register` 顶层 `def` 存在；
3. `from app.task.shadow import get_shadow_registry` facade 桥 import 存在。
"""

from __future__ import annotations

import ast
from pathlib import Path


MAIN_PATH = Path(__file__).resolve().parents[3] / "main.py"


def _tree():
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"))


def _count_calls(tree: ast.AST, name: str) -> int:
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == name:
                count += 1
    return count


def test_shadow_register_call_count_meets_lower_bound():
    tree = _tree()
    count = _count_calls(tree, "_shadow_register")
    assert count >= 6, (
        f"任务 PR-3 挂钩点被误删；期望 ≥ 6 处 `_shadow_register(...)` 调用，"
        f"实际发现 {count} 处"
    )


def test_shadow_register_helper_defined():
    tree = _tree()
    names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    assert "_shadow_register" in names


def test_shadow_facade_import_present():
    src = MAIN_PATH.read_text(encoding="utf-8")
    assert "from app.task.shadow import get_shadow_registry" in src
