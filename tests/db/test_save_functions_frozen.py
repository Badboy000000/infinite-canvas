"""数据 PR-8 承接强化补丁 · 3 save 函数 byte-identical AST 契约。

承接 PR-8 Test Results Analyzer 观察项 P0-1:

- `save_projects` (main.py:3562-3565)
- `save_prompt_libraries` (main.py:7770-7776)
- `save_runninghub_workflow_store` (main.py:17423-17426)

三个函数体是数据 M2 主写迁移的 P0 冻结契约(`db` 模式下 writer 复现其落盘字节)。
PR-8 只有 commit-time AST 审查,无 pytest 防线;本文件把 3 个函数升级到与
`tests/shadow_write/test_canvas_shadow_write.py::test_save_canvas_frozen_zone_byte_equivalent`
同级的自动化断言。

Baseline `6127578`(PR-8 landing commit; Reality Checker + Test Results Analyzer
+ Lead 独立 AST unparse 三方 verified byte-identical vs `ae50b28`;下游 PR 触碰
任一函数体 → 本测试即刻爆红)。

若 baseline ref 在 shallow clone 中不可达 → `pytest.skip`(与
`test_canvas_shadow_write.py` 现存写法一致)。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"
BASELINE_REF = "6127578"
FROZEN_FUNCS = (
    "save_projects",
    "save_prompt_libraries",
    "save_runninghub_workflow_store",
)


def _load_baseline_tree() -> ast.Module:
    result = subprocess.run(
        ["git", "show", f"{BASELINE_REF}:main.py"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"baseline ref {BASELINE_REF} unavailable")
    return ast.parse(result.stdout)


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


@pytest.mark.parametrize("fname", FROZEN_FUNCS)
def test_save_function_frozen_zone_byte_equivalent(fname: str) -> None:
    """`main.py:<fname>` 函数体自 baseline `6127578` 以来 AST byte-equivalent。

    数据 PR-8 P0-1 硬约束升级:任何后续 PR 触碰 3 个 save 函数体 →
    `ast.dump(include_attributes=False)` 差异 → 本测试爆红。

    修复流程(若这个测试挂了):
    1. 确认改动是**故意**的(如新增业务字段) → 更新 baseline `BASELINE_REF`
       到当前 landing commit + 同步 KB 现状地图
    2. 若非故意 → 回退该 PR 的对应 diff 段
    """

    baseline_tree = _load_baseline_tree()
    current_tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

    b_node = _find_func(baseline_tree, fname)
    c_node = _find_func(current_tree, fname)

    assert b_node is not None, f"baseline {fname} missing"
    assert c_node is not None, f"current {fname} missing"
    assert ast.dump(b_node, include_attributes=False) == ast.dump(
        c_node, include_attributes=False
    ), (
        f"数据 PR-8 P0-1 契约破裂:main.py:{fname} 函数体自 baseline "
        f"{BASELINE_REF} 以来被触碰;若为故意改动,须更新 BASELINE_REF 并同步 KB"
    )
