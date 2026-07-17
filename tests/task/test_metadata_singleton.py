"""任务 PR-0 · `base.metadata` 单例挂载 CI 抗回归。

覆盖 Lead 建议：任何后续 PR 定义 Table 时**必须**挂到
`from app.db.base import metadata` 单例，禁止另建 `MetaData()`。

- 5 张 Task 层表必须出现在 `app.db.base.metadata.tables`。
- 五张 `Table` 对象的 `.metadata` 属性必须 is `app.db.base.metadata`。
- AST：`app/task/tables.py` 内禁出现 `MetaData(...)` 调用。
- AST：`app/task/tables.py` 内不许 import `MetaData` 直接构造。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


EXPECTED_TABLES = (
    "tasks",
    "node_runs",
    "provider_tasks",
    "task_events",
    "artifacts",
)


def test_all_five_tables_on_shared_metadata():
    """5 张 Table 都挂在 `app.db.base.metadata` 上。"""
    import app.task.tables as t
    from app.db.base import metadata as shared_metadata

    tables_dict = shared_metadata.tables
    for name in EXPECTED_TABLES:
        assert name in tables_dict, (
            f"{name!r} 缺失于 base.metadata；实际："
            f"{list(tables_dict.keys())}"
        )
        table = tables_dict[name]
        assert table.metadata is shared_metadata, (
            f"{name!r}.metadata 不是 base.metadata 单例；违反 CI 抗回归"
        )

    # 同时验证 module 级引用
    for name in EXPECTED_TABLES:
        table = getattr(t, name)
        assert table.metadata is shared_metadata


def test_task_tables_module_does_not_construct_metadata():
    """AST 抗回归：`app/task/tables.py` 内不许 `MetaData(...)` 构造。"""
    src = (REPO_ROOT / "app" / "task" / "tables.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # `MetaData(...)` 直接调用
            if isinstance(func, ast.Name) and func.id == "MetaData":
                offenders.append(f"line {node.lineno}: MetaData(...)")
            # `sa.MetaData(...)` / `sqlalchemy.MetaData(...)` 属性调用
            if isinstance(func, ast.Attribute) and func.attr == "MetaData":
                offenders.append(
                    f"line {node.lineno}: {ast.unparse(func)}(...)"
                )
    assert not offenders, (
        f"app/task/tables.py 出现自建 MetaData 调用：{offenders}"
    )


def test_task_tables_module_imports_shared_metadata():
    """AST 抗回归：`app/task/tables.py` 必须 `from app.db.base import metadata`。"""
    src = (REPO_ROOT / "app" / "task" / "tables.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    ok = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.db.base":
                for alias in node.names:
                    if alias.name == "metadata":
                        ok = True
                        break
    assert ok, (
        "app/task/tables.py 缺少 `from app.db.base import metadata` —— "
        "五张 Table 必须挂到该单例上"
    )
