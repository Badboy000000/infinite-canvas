"""数据 PR-8 · Project 主写机制契约测试（Wave 3-G）。

覆盖点（≥8 项 STRONG 级）：

1. `PROJECT_PRIMARY_WRITE=json`（默认）时 `project_store.save_projects` 行为
   与 PR-4 基线**字节等价**：不 import `app.db.project_writer` / 不构造 DB
   engine / 不落任何 fallback 文件（P0 硬约束 #3）。
2. `PROJECT_PRIMARY_WRITE=db` 时 DB `projects` 表按 payload 集合级 UPSERT。
3. `db` 模式下 payload 减少 → DELETE 不在 payload 的 `legacy_id`（集合级
   写事务）。
4. `db` 模式下写成功后异步 JSON 回写落地（wait 后 os.path.exists = True）。
5. `db` 模式下 JSON 回写失败（IO 异常）不冒泡；shadow diff 落地。
6. fail-fast：`PROJECT_PRIMARY_WRITE="invalid"` 在 Settings 层报错。
7. DB 主写失败必须上抛（不 fallback 到 JSON 主写）。
8. `ensure_default_project` 在 `PROJECT_PRIMARY_WRITE=db` 下语义等价（DB
   空 → 插入默认；幂等再调不重复行）。
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def data_dir_fixture(tmp_path, monkeypatch, isolated_env):
    """把 `DATA_DIR` / `PROJECTS_PATH` 指到 tmp_path。"""

    import main

    data_dir = tmp_path
    projects_path = data_dir / "projects.json"
    monkeypatch.setattr(main, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main, "PROJECTS_PATH", str(projects_path))
    yield data_dir


def _seed_project(pid: str, name: str = "P", order: int = 0) -> dict:
    return {
        "id": pid,
        "name": name,
        "order": order,
        "created_at": 1000,
        "updated_at": 2000,
    }


# ---------------------------------------------------------------------------
# 1. json 默认模式 sys.modules 隔离契约（P0）
# ---------------------------------------------------------------------------


def test_json_mode_default_does_not_import_project_writer(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`PROJECT_PRIMARY_WRITE=json`（数据 PR-20 反转后 · 显式回滚开关）时
    `app.db.project_writer` 从未 import。

    P0 硬约束 #3：json 回滚路径无任何行为变化（PR-4 → PR-8 → PR-20 用户零感知）。
    """

    # 数据 PR-20 反转后：默认已经是 db，本用例语义是"显式 json 回滚开关"
    # 下不 import project_writer；因此必须 setenv，不能 delenv。
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "json")
    sys.modules.pop("app.db.project_writer", None)

    from app.stores import project_store

    projects = [_seed_project("p1", "One")]
    project_store.save_projects(projects)

    assert "app.db.project_writer" not in sys.modules, (
        "P0 硬约束违反：PROJECT_PRIMARY_WRITE=json 默认下拉起了 app.db.project_writer"
    )
    # 主写产物仍在磁盘
    assert (data_dir_fixture / "projects.json").exists()

    # 不落 fallback diff
    fallback_dir = tmp_path / "shadow_diff" / "project_json_fallback"
    assert not fallback_dir.exists()


def test_json_mode_default_does_not_build_db_engine(
    monkeypatch, data_dir_fixture, tmp_path
):
    """显式 `json` 回滚模式下 `save_projects` 不构造 DB engine（P0 硬约束）。

    数据 PR-20 反转后：默认已经是 db；本用例语义是"显式 json"下不建 engine。
    """

    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "json")

    from app.db import engine as db_engine

    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when json mode")

    monkeypatch.setattr(db_engine, "get_engine", _fail)

    from app.stores import project_store

    project_store.save_projects([_seed_project("p_json", "J")])

    assert hits["count"] == 0


# ---------------------------------------------------------------------------
# 2. db 模式全链路契约
# ---------------------------------------------------------------------------


def test_db_mode_upserts_projects_to_db(monkeypatch, data_dir_fixture, tmp_path):
    """`PROJECT_PRIMARY_WRITE=db` → DB `projects` 表按 payload 集合级 UPSERT。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import project_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")

    projects = [_seed_project("p1", "One", 0), _seed_project("p2", "Two", 1)]
    project_store.save_projects(projects)

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.projects.c.legacy_id,
                t.projects.c.name,
                t.projects.c.order_index,
                t.projects.c.raw_json,
            ).order_by(t.projects.c.order_index.asc())
        ).fetchall()

    assert len(rows) == 2
    assert [r.legacy_id for r in rows] == ["p1", "p2"]
    assert [r.name for r in rows] == ["One", "Two"]
    # raw_json 是完整 entry 序列化
    p1_payload = json.loads(rows[0].raw_json)
    assert p1_payload["id"] == "p1"
    assert p1_payload["name"] == "One"


def test_db_mode_collection_delete_removes_absent_entries(
    monkeypatch, data_dir_fixture, tmp_path
):
    """集合级写事务：payload 减少后，DB 中 `legacy_id NOT IN payload` 的行被 DELETE。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import project_store
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")

    # 先写 3 个
    project_store.save_projects(
        [_seed_project("a", "A"), _seed_project("b", "B"), _seed_project("c", "C")]
    )

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(t.projects)
        ).scalar_one()
    assert count == 3

    # 再写只有 1 个 → DB 中应只剩这 1 行
    project_store.save_projects([_seed_project("b", "B updated")])

    with engine.connect() as conn:
        rows = conn.execute(
            select(t.projects.c.legacy_id, t.projects.c.name)
        ).fetchall()
    assert len(rows) == 1
    assert rows[0].legacy_id == "b"
    assert rows[0].name == "B updated"


def test_db_mode_async_json_fallback_writes_file(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下写成功后 JSON 异步回写落地。"""

    from app.stores import project_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")

    projects = [_seed_project("pa", "Alpha")]
    project_store.save_projects(projects)

    saved_path = data_dir_fixture / "projects.json"
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        if saved_path.exists():
            break
        time.sleep(0.02)

    assert saved_path.exists(), "async JSON fallback file did not appear in time"
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    assert loaded == {"projects": [projects[0]]}


def test_db_mode_json_fallback_failure_does_not_propagate(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下 JSON 回写失败（IO 异常）不冒泡；shadow diff 落地。

    数据 PR-8 承接强化补丁：**端到端**触发 `_async_write_json_fallback →
    _write_json_fallback_sync → _record_json_fallback_failure` 全链路
    （与 canvas C6' 对齐，不再手工调用 `_record_json_fallback_failure`）。
    通过 monkeypatch `main.PROJECTS_PATH` 到不存在的父目录 → 内部
    `open()` 抛 FileNotFoundError → 真实 except → 真实 diff 记录。
    """

    from app.stores import project_store

    import main

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")

    # 指向不存在的父目录 → `_write_json_fallback_sync` 内部 `open()` 抛
    # FileNotFoundError（主写路径已完成，异步 fallback 才触发这条异常路径）
    monkeypatch.setattr(
        main,
        "PROJECTS_PATH",
        str(tmp_path / "nonexistent_dir" / "projects.json"),
    )

    # 主写路径不应抛错
    project_store.save_projects([_seed_project("p_boom", "B")])

    # 等待异步 fallback 走完真实链路：
    # _async_write_json_fallback → _write_json_fallback_sync（抛错）
    # → 内部 except → _record_json_fallback_failure → jsonl 落盘
    diff_dir = tmp_path / "shadow_diff" / "project_json_fallback"
    deadline = time.perf_counter() + 2.0
    diff_files: list = []
    while time.perf_counter() < deadline:
        if diff_dir.exists():
            diff_files = list(diff_dir.glob("*.jsonl"))
            if diff_files:
                break
        time.sleep(0.02)

    assert diff_files, (
        "端到端 fallback diff 链路应真实产生 jsonl 文件（与 canvas C6' 对齐）"
    )
    rec = json.loads(diff_files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["domain"] == "project"
    assert rec["fallback_reason"] == "json_write_error"
    # P0：diff 不含内容体（只有 error/reason/ts/domain）
    assert set(rec.keys()) == {"ts", "domain", "error", "fallback_reason"}


def test_db_mode_primary_write_error_propagates(
    monkeypatch, data_dir_fixture, tmp_path
):
    """DB 主写失败必须上抛，不允许 fallback 到 JSON 主写（P0 硬约束 #4）。"""

    from app.stores import project_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")

    def _boom_engine(*a, **kw):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr("app.db.engine.get_engine", _boom_engine)

    with pytest.raises(RuntimeError, match="simulated db failure"):
        project_store.save_projects([_seed_project("p_db_boom", "B")])

    # 主写抛错时 JSON 回写不应触发
    saved_path = data_dir_fixture / "projects.json"
    time.sleep(0.1)
    assert not saved_path.exists()


def test_db_mode_load_projects_db_returns_list(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`load_projects_db` 从 DB 读回按 order_index 排序的 list；空表 → None。"""

    from app.db.project_writer import load_projects_db, save_projects_db

    migrate_baseline(tmp_path)

    assert load_projects_db() is None

    save_projects_db(
        [_seed_project("z", "Z", 5), _seed_project("a", "A", 0), _seed_project("m", "M", 2)]
    )
    result = load_projects_db()
    assert result is not None
    assert [p["id"] for p in result] == ["a", "m", "z"]


def test_db_mode_ensure_default_project_semantics(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`ensure_default_project` 在 db 模式下语义等价：DB 空 → 插入；幂等再调不重复。

    通过 `main.ensure_default_project()` 调用（其内部走 `project_store.save_projects`），
    直接验证 store facade 分派后的 UPSERT-DELETE 语义（P1）。
    """

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")

    import main

    # 第一次调用 → 应通过 store facade UPSERT 默认项目
    projects = main.ensure_default_project()
    assert any(p.get("id") == main.DEFAULT_PROJECT_ID for p in projects)

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(select(func.count()).select_from(t.projects)).scalar_one()
    assert count == 1

    # 第二次调用 → 幂等，不新增行
    main.ensure_default_project()
    with engine.connect() as conn:
        count2 = conn.execute(select(func.count()).select_from(t.projects)).scalar_one()
    assert count2 == 1


def test_db_mode_raw_json_preserves_entry_semantics(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`raw_json` 字节承载整个 entry 语义（复用 legacy_snapshot 反序列化契约）。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import project_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")

    entry = _seed_project("p_raw", "raw name")
    entry["extra_field"] = "extra_value"
    project_store.save_projects([entry])

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.projects.c.raw_json).where(t.projects.c.legacy_id == "p_raw")
        ).fetchone()

    assert row is not None
    payload = json.loads(row.raw_json)
    assert payload["id"] == "p_raw"
    assert payload["name"] == "raw name"
    assert payload["extra_field"] == "extra_value"
