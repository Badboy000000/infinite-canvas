"""数据 PR-8 承接强化补丁 · save 函数 byte-identical AST 契约（PR-9 扩至 4 项）。

承接 PR-8 Test Results Analyzer 观察项 P0-1:

- `save_projects` (main.py:3562-3565)
- `save_prompt_libraries` (main.py:7770-7776)
- `save_runninghub_workflow_store` (main.py:17423-17426)

数据 PR-9（Wave 3-H）追加第 4 项 byte-identical 契约：

- `save_asset_library` (main.py:7438-7446)：本 PR 首次确立 AssetLibrary
  byte-identical 契约，pin baseline `ae50b28`（与 `save_canvas` 同 baseline，
  是 4 个 save_* 函数体 byte-identical 的最初共同起点）。

三个（现四个）函数体是数据 M2 主写迁移的 P0 冻结契约(`db` 模式下 writer 复现
其落盘字节)。PR-8 landing 时 3 项走 baseline `6127578`；PR-9 起 `save_asset_library`
走 baseline `ae50b28`。

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

# (function_name, baseline_ref) tuples —— 每个函数体独立 pin 自己的 baseline。
FROZEN_FUNCS: tuple[tuple[str, str], ...] = (
    ("save_projects", "6127578"),
    ("save_prompt_libraries", "6127578"),
    ("save_runninghub_workflow_store", "6127578"),
    # 数据 PR-9（Wave 3-H）首次确立 AssetLibrary byte-identical 契约。
    ("save_asset_library", "ae50b28"),
)


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


@pytest.mark.parametrize(("fname", "baseline_ref"), FROZEN_FUNCS)
def test_save_function_frozen_zone_byte_equivalent(fname: str, baseline_ref: str) -> None:
    """`main.py:<fname>` 函数体自 baseline `<baseline_ref>` 以来 AST byte-equivalent。

    数据 PR-8 P0-1 硬约束升级（PR-9 扩至 4 项）：任何后续 PR 触碰这些 save
    函数体 → `ast.dump(include_attributes=False)` 差异 → 本测试爆红。

    修复流程(若这个测试挂了):
    1. 确认改动是**故意**的(如新增业务字段) → 更新对应函数的 baseline_ref
       到当前 landing commit + 同步 KB 现状地图
    2. 若非故意 → 回退该 PR 的对应 diff 段
    """

    baseline_tree = _load_baseline_tree(baseline_ref)
    current_tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))

    b_node = _find_func(baseline_tree, fname)
    c_node = _find_func(current_tree, fname)

    assert b_node is not None, f"baseline {fname} missing"
    assert c_node is not None, f"current {fname} missing"
    assert ast.dump(b_node, include_attributes=False) == ast.dump(
        c_node, include_attributes=False
    ), (
        f"数据 PR-8/PR-9 P0-1 契约破裂:main.py:{fname} 函数体自 baseline "
        f"{baseline_ref} 以来被触碰;若为故意改动,须更新 baseline_ref 并同步 KB"
    )
