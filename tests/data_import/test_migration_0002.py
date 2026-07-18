"""数据 PR-3 · Alembic revision `0002_baseline_tables` 契约测试。

覆盖：

1. `alembic upgrade head` 建 6 类对象 + 4 张子表 = 9 张业务表 + 承接 5 张任务表；
2. `upgrade → downgrade base → upgrade` 幂等；
3. 每张表关键索引存在；
4. `revision` id / `down_revision` 正确。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import sqlite3


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

EXPECTED_INDEXES = (
    "ix_projects_legacy_id",
    "ix_provider_configs_legacy_id",
    "ix_prompt_libraries_legacy_id",
    "ix_prompt_items_library_id",
    "ix_prompt_items_legacy_library_id",
    "ix_workflow_definitions_provider_id",
    "ix_workflow_definitions_legacy_id",
    "ix_asset_libraries_legacy_id",
    "ix_asset_categories_library_id",
    "ix_asset_categories_legacy_library_id",
    "ix_asset_items_category_id",
    "ix_asset_items_legacy_category_id",
    "ix_asset_items_legacy_url",
    "ix_canvases_legacy_id",
    "ix_canvases_project_legacy_id",
)


def _run_migrate(revision: str, db_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["DATA_DB_PATH"] = str(db_path)
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "migrate", revision],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _run_downgrade(revision: str, db_path: Path) -> subprocess.CompletedProcess:
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
        timeout=120,
    )


def _tables_in(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    finally:
        conn.close()


def _indexes_in(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()}
    finally:
        conn.close()


def test_revision_ids_are_correct():
    """`0002_baseline_tables.revision == '0002_baseline_tables'`；
    `down_revision == '0001_task_layer'`。"""
    import importlib.util

    path = REPO_ROOT / "app" / "db" / "migrations" / "versions" / "0002_baseline_tables.py"
    spec = importlib.util.spec_from_file_location("_baseline_tables_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    assert mod.revision == "0002_baseline_tables"
    assert mod.down_revision == "0001_task_layer"


def test_migrate_upgrade_creates_baseline_tables(tmp_path):
    db = tmp_path / "pr3_upgrade.db"
    result = _run_migrate("head", db)
    assert result.returncode == 0, (
        f"upgrade head 失败：stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    tables = _tables_in(db)
    for name in EXPECTED_TABLES:
        assert name in tables, f"表 {name!r} 未在 upgrade head 后创建"
    # 承接任务 PR-0 的 5 张表也必须仍然存在
    for name in ("tasks", "node_runs", "provider_tasks", "task_events", "artifacts"):
        assert name in tables, f"任务表 {name!r} 应仍存在"


def test_migrate_upgrade_creates_expected_indexes(tmp_path):
    db = tmp_path / "pr3_indexes.db"
    result = _run_migrate("head", db)
    assert result.returncode == 0, result.stderr
    idx = _indexes_in(db)
    missing = set(EXPECTED_INDEXES) - idx
    assert not missing, f"缺失索引：{missing}"


def test_migrate_upgrade_downgrade_upgrade_idempotent(tmp_path):
    """`upgrade head → downgrade 0001_task_layer → upgrade head` 幂等。

    downgrade 到 `0001_task_layer`（回滚 baseline_tables，只保留 task 层）。
    """
    db = tmp_path / "pr3_idem.db"

    r1 = _run_migrate("head", db)
    assert r1.returncode == 0, r1.stderr
    tables_after_1 = _tables_in(db)
    for name in EXPECTED_TABLES:
        assert name in tables_after_1

    r2 = _run_downgrade("0001_task_layer", db)
    assert r2.returncode == 0, r2.stderr
    tables_mid = _tables_in(db)
    for name in EXPECTED_TABLES:
        assert name not in tables_mid
    # Task 层仍在
    assert "tasks" in tables_mid

    r3 = _run_migrate("head", db)
    assert r3.returncode == 0, r3.stderr
    tables_final = _tables_in(db)
    for name in EXPECTED_TABLES:
        assert name in tables_final
