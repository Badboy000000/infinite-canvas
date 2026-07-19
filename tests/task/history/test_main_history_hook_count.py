"""任务 PR-4 · AST 断言 —— main.py 内 History 派生挂钩点数量下限。

保护未来 PR 不误删挂钩：statically 断言 `main.py` 中：

1. `_history_derive(...)` 出现次数 ≥ 3（本 PR 挂钩点数下限）；
2. `_history_derive` 顶层 `def` 存在；
3. `from app.task.history import get_history_writer` facade 桥 import 存在。
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


def test_history_derive_call_count_meets_lower_bound():
    tree = _tree()
    count = _count_calls(tree, "_history_derive")
    assert count >= 3, (
        f"任务 PR-4 挂钩点被误删；期望 ≥ 3 处 `_history_derive(...)` 调用，"
        f"实际发现 {count} 处"
    )


def test_history_derive_helper_defined_and_facade_present():
    tree = _tree()
    names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    assert "_history_derive" in names, (
        "顶层 `def _history_derive` 缺失 —— 任务 PR-4 顶层 helper 契约"
    )
    src = MAIN_PATH.read_text(encoding="utf-8")
    assert "from app.task.history import get_history_writer" in src, (
        "任务 PR-4 facade 桥 import `from app.task.history import "
        "get_history_writer as _get_history_writer` 必须保留"
    )
