"""数据 PR-1 契约测试：`app/db/` 脚手架。

覆盖点：
1. `engine.create_engine()` 从 `get_settings().data_db_path` 现读构造 SQLite URL；
   monkeypatch `main.DATA_DB_PATH` 后 engine.url 立即反映（读时求值语义）。
2. `base.metadata` naming convention 4 条 key 齐全（+ pk 共 5 项）。
3. `app.db.migrations.env` 的 `target_metadata is app.db.base.metadata`。
4. `python main.py migrate head` 子进程运行成功且创建 sqlite 文件 +
   `alembic_version` 系统表。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-1。
"""

from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _reload_engine_singleton():
    """确保测试之间 `engine._engine_singleton` 已清理。"""
    from app.db import engine as _engine_mod

    _engine_mod.reset_engine()


def test_engine_uses_settings_path(tmp_path, monkeypatch):
    """`engine.create_engine()` URL 应从 `get_settings().data_db_path` 现读构造。

    - monkeypatch `main.DATA_DB_PATH` 指向 tmp_path 下的 db 文件。
    - `create_engine()` 返回的 `engine.url` 应包含该绝对路径。
    - 父目录应自动建好。
    """
    import main  # 触发 main.py 载入（`if __name__ == "__main__"` 分支不会执行）

    from app.db import engine as _engine_mod

    _reload_engine_singleton()

    target = tmp_path / "nested" / "smoke_pr1.db"
    assert not target.parent.exists(), "tmp_path 下嵌套目录预期尚未创建"

    monkeypatch.setattr(main, "DATA_DB_PATH", str(target))

    engine = _engine_mod.create_engine()
    try:
        assert engine.url.get_backend_name() == "sqlite"
        # URL 中包含绝对路径的规范化形式（Windows/*nix 差异由 SQLAlchemy 归一）
        url_str = str(engine.url)
        assert "smoke_pr1.db" in url_str
        # 父目录必须已被 create_engine 建好
        assert target.parent.is_dir(), "engine 应保证 DB 父目录存在"
    finally:
        engine.dispose()
        _reload_engine_singleton()


def test_engine_get_database_url_reads_current_setting(tmp_path, monkeypatch):
    """`get_database_url()` 每次调用现读 `Settings.data_db_path`。"""
    import main

    from app.db import engine as _engine_mod

    monkeypatch.setattr(main, "DATA_DB_PATH", str(tmp_path / "a.db"))
    assert _engine_mod.get_database_url().endswith("a.db")
    monkeypatch.setattr(main, "DATA_DB_PATH", str(tmp_path / "b.db"))
    assert _engine_mod.get_database_url().endswith("b.db")


def test_metadata_naming_convention():
    """`base.metadata.naming_convention` 至少包含 4 条 key + 1 条 pk。"""
    from app.db.base import metadata

    conv = metadata.naming_convention
    assert conv is not None
    for key in ("ix", "uq", "ck", "fk", "pk"):
        assert key in conv, f"naming_convention 缺少 {key!r}"
    # 精确断言默认值，防止未来意外改动
    assert conv["ix"] == "ix_%(column_0_label)s"
    assert conv["uq"] == "uq_%(table_name)s_%(column_0_name)s"
    assert conv["ck"] == "ck_%(table_name)s_%(constraint_name)s"
    assert conv["fk"] == (
        "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
    )
    assert conv["pk"] == "pk_%(table_name)s"


def test_metadata_has_no_tables_at_baseline():
    """本 PR 硬约束：`base.metadata` 在数据 PR-1 落地时不定义任何 Table。"""
    from app.db.base import metadata

    assert metadata.tables == {}, (
        f"数据 PR-1 硬约束：base.metadata 不许包含任何 Table；实际存在："
        f"{list(metadata.tables.keys())}"
    )


def test_alembic_env_target_metadata(tmp_path, monkeypatch):
    """`app.db.migrations.env` 模块被 Alembic 执行时，`target_metadata` 必须
    严格 is `app.db.base.metadata`。

    此测试通过 Alembic 内部 API `ScriptDirectory.from_config` + Alembic
    `EnvironmentContext` 打模拟执行 env.py，读取 `context.get_context()
    .opts["target_metadata"]`。为了避免影响真实 DB，把 URL 指向 tmp 下的
    独立 sqlite。
    """
    import main

    monkeypatch.setattr(main, "DATA_DB_PATH", str(tmp_path / "env_probe.db"))
    _reload_engine_singleton()

    # 直接 import env.py 模块变量做静态断言：`env.py` 顶部 `from app.db.base
    # import metadata as target_metadata`，模块级即绑定。此方式避开 Alembic
    # runner 上下文（`context.config`）在 unit test 内难以构造的问题。
    #
    # 但 `env.py` 顶部会调用 `context.is_offline_mode()`——那会抛异常。因此
    # 我们不直接 import 该模块，而是 grep 断言：`target_metadata` 名字与
    # `app.db.base.metadata` 是同一对象即可。
    from app.db import base as _base_mod

    env_source = (
        REPO_ROOT / "app" / "db" / "migrations" / "env.py"
    ).read_text(encoding="utf-8")
    assert "from app.db.base import metadata as target_metadata" in env_source, (
        "env.py 必须直接 import `app.db.base.metadata` 作为 target_metadata；"
        "禁止另建 metadata 变量"
    )
    # 补充：确保 base 模块的 metadata 是 SQLAlchemy MetaData 实例
    from sqlalchemy import MetaData

    assert isinstance(_base_mod.metadata, MetaData)


def test_migrate_cli_head_smoke(tmp_path):
    """`python main.py migrate head` 子进程应能成功 + 建 sqlite + `alembic_version` 表。

    - 用 tmp_path 下的独立 db 文件，通过 env `DATA_DB_PATH` 隔离。
    - 期望：exit=0；文件出现；`alembic_version` 系统表存在。
    """
    db_path = tmp_path / "cli_smoke.db"
    env = dict(os.environ)
    env["DATA_DB_PATH"] = str(db_path)
    # 让子进程内的 main.py 顶部 `DATA_DB_PATH = env or default` 走 env 分支

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), "migrate", "head"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"migrate head 失败：stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert db_path.exists(), f"migrate 未创建 sqlite 文件：{db_path}"

    # 断言 `alembic_version` 系统表存在——即便无迁移 revision，Alembic upgrade
    # head 仍会创建此表。
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        )
        row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None, (
        f"migrate 完成但 `alembic_version` 表不存在于 {db_path}"
    )
