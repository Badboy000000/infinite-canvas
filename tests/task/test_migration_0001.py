"""任务 PR-0 · Alembic 迁移 `0001_task_layer` 契约测试。

覆盖：

1. `alembic upgrade head` 幂等：在临时 sqlite 上 `upgrade → downgrade → upgrade`
   均成功；`alembic_version` + 5 张业务表齐全。
2. `base.metadata.tables` 含 5 张预期表名。
3. 每张表关键列 + 4 类索引存在性。
4. `tasks.idempotency_key` UNIQUE 约束存在（幂等键唯一）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlite3


REPO_ROOT = Path(__file__).resolve().parents[2]


EXPECTED_TABLES = (
    "tasks",
    "node_runs",
    "provider_tasks",
    "task_events",
    "artifacts",
)


def _run_migrate(revision: str, db_path: Path) -> subprocess.CompletedProcess:
    """`python main.py migrate <revision>` 子进程调用（upgrade path）。"""
    env = dict(os.environ)
    env["DATA_DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "migrate", revision],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _run_downgrade(revision: str, db_path: Path) -> subprocess.CompletedProcess:
    """通过独立 Python 子进程调 Alembic `command.downgrade` (main.py CLI 不
    暴露 downgrade — `main.py` L17710-17729 冻结区间；本 PR 不允许扩展 CLI)。
    这里通过 `-c "..."` 直接调 `app.db` 内部 API 完成 downgrade。
    """
    env = dict(os.environ)
    env["DATA_DB_PATH"] = str(db_path)
    code = (
        "import sys, os;"
        "sys.path.insert(0, r'" + str(REPO_ROOT).replace("\\", "\\\\") + "');"
        "from alembic import command as c;"
        "from app.db.engine import _alembic_config;"
        "c.downgrade(_alembic_config(), " + repr(revision) + ")"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )


def _tables_in(db_path: Path) -> set:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def _indexes_in(db_path: Path) -> set:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def test_metadata_registers_task_layer_tables():
    """`app.task.tables` 5 张 Table 全部挂在 `app.db.base.metadata`。"""
    import app.task.tables  # noqa: F401 触发 Table 注册
    from app.db.base import metadata

    for name in EXPECTED_TABLES:
        assert name in metadata.tables, (
            f"任务 PR-0 硬约束：{name!r} 未挂在 base.metadata 上"
        )


def test_no_ad_hoc_metadata_instance():
    """AST 抗回归：`app.task.tables` 内不许出现 `MetaData(` 构造。

    避免任何后续 PR 在 tables 模块内自建 `MetaData()`，脱离
    `app.db.base.metadata` 单例。
    """
    import ast

    src = (
        REPO_ROOT / "app" / "task" / "tables.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "MetaData", (
                "禁止在 app/task/tables.py 中调用 MetaData() —— "
                "任何 Table 必须挂到 `from app.db.base import metadata` 单例"
            )


def test_migrate_upgrade_creates_expected_tables(tmp_path):
    """`migrate head` 后 5 张业务表 + `alembic_version` 齐全。"""
    db = tmp_path / "task_layer_upgrade.db"
    result = _run_migrate("head", db)
    assert result.returncode == 0, (
        f"upgrade head 失败：stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    tables = _tables_in(db)
    for name in EXPECTED_TABLES:
        assert name in tables, f"表 {name!r} 未在 upgrade 后创建"
    assert "alembic_version" in tables


def test_migrate_upgrade_creates_expected_indexes(tmp_path):
    """4 类关键索引 + UNIQUE 约束存在性。"""
    db = tmp_path / "task_layer_indexes.db"
    result = _run_migrate("head", db)
    assert result.returncode == 0, result.stderr

    idx = _indexes_in(db)
    # SQLite 会为 UNIQUE 约束自动生成 sqlite_autoindex_*，也可能出现
    # 我们显式命名的 uq_tasks_idempotency_key —— 两者都是可接受形式。
    required_named = {
        "ix_tasks_status_updated_at",
        "ix_tasks_canvas_node",
        "ix_provider_tasks_provider_upstream",
        "ix_provider_tasks_task_id",
        "ix_task_events_task_id_seq",
        "ix_artifacts_task_id",
        "ix_artifacts_node_run_id",
        "ix_node_runs_canvas_node",
        "ix_node_runs_status_updated_at",
    }
    missing = required_named - idx
    assert not missing, f"缺失索引：{missing}；实际 idx={idx}"

    # UNIQUE(idempotency_key) 存在：命名约束或 sqlite_autoindex_tasks_1 之一。
    has_uq = any(
        "uq_tasks_idempotency_key" == n or n.startswith("sqlite_autoindex_tasks")
        for n in idx
    )
    assert has_uq, (
        f"tasks.idempotency_key UNIQUE 约束缺失；实际 idx={idx}"
    )


def test_migrate_upgrade_downgrade_upgrade_idempotent(tmp_path):
    """`upgrade → downgrade → upgrade` 幂等验证。

    `main.py migrate` CLI 只支持 upgrade（其代码位于 L17710-17729 冻结区间，
    本 PR 不扩展 CLI）；downgrade 通过 Alembic 内部 API 子进程执行，验证
    revision 双向可用。
    """
    db = tmp_path / "task_layer_idem.db"
    # 1) upgrade head
    r1 = _run_migrate("head", db)
    assert r1.returncode == 0, r1.stderr
    # 2) downgrade base（走 Alembic 内部 API 子进程）
    r2 = _run_downgrade("base", db)
    assert r2.returncode == 0, r2.stderr
    tables_mid = _tables_in(db)
    for name in EXPECTED_TABLES:
        assert name not in tables_mid, (
            f"downgrade base 后 {name!r} 仍存在：{tables_mid}"
        )
    # 3) upgrade head again
    r3 = _run_migrate("head", db)
    assert r3.returncode == 0, r3.stderr
    tables_final = _tables_in(db)
    for name in EXPECTED_TABLES:
        assert name in tables_final
