"""数据 PR-3 · `base.metadata` 单例挂载 CI 抗回归。

覆盖 [[70 开发过程跟踪/治理机制/subagent 任务书回写义务清单]]：任何 Table
定义**必须**挂到 `from app.db.base import metadata` 单例，禁自建 `MetaData()`。

- 9 张 baseline 表全部在 `base.metadata.tables` 内；
- `Table.metadata is base.metadata`；
- AST：`app/data_import/tables.py` 内不许 `MetaData(...)` 构造；
- AST：`app/data_import/tables.py` 必须 `from app.db.base import metadata`。
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


EXPECTED_TABLES = (
    "projects",
    "provider_configs",
    "prompt_libraries",
    "prompt_items",
    "workflow_definitions",
    "asset_libraries",
    "asset_categories",
    "asset_items",
    "canvases",
)


def test_all_baseline_tables_on_shared_metadata():
    import app.data_import.tables as t
    from app.db.base import metadata as shared_metadata

    tables_dict = shared_metadata.tables
    for name in EXPECTED_TABLES:
        assert name in tables_dict, (
            f"{name!r} 缺失于 base.metadata；实际：{sorted(tables_dict.keys())}"
        )
        table = tables_dict[name]
        assert table.metadata is shared_metadata, (
            f"{name!r}.metadata 不是 base.metadata 单例；违反 CI 抗回归"
        )

    for name in EXPECTED_TABLES:
        table = getattr(t, name)
        assert table.metadata is shared_metadata


def test_data_import_tables_no_ad_hoc_metadata():
    src = (REPO_ROOT / "app" / "data_import" / "tables.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "MetaData":
                offenders.append(f"line {node.lineno}: MetaData(...)")
            if isinstance(func, ast.Attribute) and func.attr == "MetaData":
                offenders.append(f"line {node.lineno}: {ast.unparse(func)}(...)")
    assert not offenders, f"app/data_import/tables.py 出现自建 MetaData：{offenders}"


def test_data_import_tables_imports_shared_metadata():
    src = (REPO_ROOT / "app" / "data_import" / "tables.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    ok = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "app.db.base":
            for alias in node.names:
                if alias.name == "metadata":
                    ok = True
                    break
    assert ok, (
        "app/data_import/tables.py 缺少 `from app.db.base import metadata`；"
        "9 张 baseline 表必须挂到该单例"
    )
