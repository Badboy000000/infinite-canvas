"""数据 PR-3 · AST 层断言：`main.py` 顶层 body 不许 `import sqlalchemy` /
`from sqlalchemy import Session`。

CLI 子命令（`data-import` / `data-reconcile`）**只**能调
`from app.data_import import import_domain, reconcile_domain`；
禁止在 `main.py` 内直接 `import sqlalchemy` / 拉取 `Session` / 直连 engine。

由此在 CI 层护栏，避免未来 PR 在 `main.py` 里回填 SQL 泄漏。
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_main_module_does_not_import_sqlalchemy():
    src = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders: list[str] = []

    for node in ast.walk(tree):
        # `import sqlalchemy` / `import sqlalchemy.orm ...`
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlalchemy" or alias.name.startswith("sqlalchemy."):
                    offenders.append(
                        f"line {node.lineno}: import {alias.name}"
                    )
        # `from sqlalchemy import ...` / `from sqlalchemy.orm import Session`
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "sqlalchemy"
                or node.module.startswith("sqlalchemy.")
            ):
                names = ", ".join(a.name for a in node.names)
                offenders.append(
                    f"line {node.lineno}: from {node.module} import {names}"
                )

    assert not offenders, (
        "main.py 不许 import sqlalchemy / Session；请通过 "
        "`app.data_import.*` 或 `app.db.*` facade 调用。违规：\n  - "
        + "\n  - ".join(offenders)
    )
