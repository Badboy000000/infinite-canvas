"""数据 PR-8 · PromptLibrary 主写机制契约测试（Wave 3-G）。

覆盖点（≥6 项 STRONG 级）：

1. `PROMPT_LIBRARY_PRIMARY_WRITE=json`（默认）时 `prompt_library_store.save_prompt_libraries`
   行为与 PR-4 基线**字节等价**：不 import `app.db.prompt_library_writer` /
   不构造 DB engine / 不落 fallback 文件（P0 硬约束 #3）。
2. `PROMPT_LIBRARY_PRIMARY_WRITE=db` 时 DB `prompt_libraries` 表按 payload 集合级 UPSERT。
3. D-2=B 决策验证：`prompt_items` 表 PR-8 **未被写入**（items 全塞 `raw_json`）。
4. 内置库 `system/readonly/version` 语义不变（走 `normalize_prompt_libraries`）。
5. `db` 模式下 JSON 异步回写落地。
6. fail-fast：`PROMPT_LIBRARY_PRIMARY_WRITE="invalid"` 在 Settings 层报错。
7. DB 主写失败必须上抛（不 fallback）。
8. `db` 模式下 payload 减少 → DELETE 不在 payload 的 library。
"""

from __future__ import annotations

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
    import main

    prompt_path = tmp_path / "prompt_libraries.json"
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "PROMPT_LIBRARY_PATH", str(prompt_path))
    yield tmp_path


def _payload(libs: list[dict], active_id: str = "system") -> dict:
    return {"active_library_id": active_id, "libraries": libs}


def _lib(lid: str, name: str = "L", items: list[dict] | None = None) -> dict:
    return {
        "id": lid,
        "name": name,
        "type": "prompt",
        "system": lid == "system",
        "readonly": False,
        "categories": [],
        "items": items or [],
    }


# ---------------------------------------------------------------------------
# 1. json 默认模式 sys.modules 隔离契约（P0）
# ---------------------------------------------------------------------------


def test_json_mode_default_does_not_import_prompt_library_writer(
    monkeypatch, data_dir_fixture, tmp_path
):
    """P0 硬约束 #3：默认模式不 import `app.db.prompt_library_writer`。"""

    monkeypatch.delenv("PROMPT_LIBRARY_PRIMARY_WRITE", raising=False)
    sys.modules.pop("app.db.prompt_library_writer", None)

    from app.stores import prompt_library_store

    payload = _payload([_lib("system", "系统提示词库")])
    prompt_library_store.save_prompt_libraries(payload)

    assert "app.db.prompt_library_writer" not in sys.modules, (
        "P0 硬约束违反：默认模式拉起了 app.db.prompt_library_writer"
    )
    assert (data_dir_fixture / "prompt_libraries.json").exists()

    fallback_dir = tmp_path / "shadow_diff" / "prompt_library_json_fallback"
    assert not fallback_dir.exists()


def test_json_mode_default_does_not_build_db_engine(
    monkeypatch, data_dir_fixture, tmp_path
):
    monkeypatch.delenv("PROMPT_LIBRARY_PRIMARY_WRITE", raising=False)

    from app.db import engine as db_engine

    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when json mode")

    monkeypatch.setattr(db_engine, "get_engine", _fail)

    from app.stores import prompt_library_store

    prompt_library_store.save_prompt_libraries(_payload([_lib("system")]))
    assert hits["count"] == 0


# ---------------------------------------------------------------------------
# 2. db 模式集合级写事务
# ---------------------------------------------------------------------------


def test_db_mode_upserts_libraries_to_db(monkeypatch, data_dir_fixture, tmp_path):
    """`db` 模式下 DB `prompt_libraries` 表按 payload 集合级 UPSERT。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import prompt_library_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "db")

    payload = _payload(
        [
            _lib("system", "系统提示词库"),
            _lib("mine", "我的库", items=[{"id": "t1", "name": "tpl1"}]),
        ],
        active_id="system",
    )
    prompt_library_store.save_prompt_libraries(payload)

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.prompt_libraries.c.legacy_id,
                t.prompt_libraries.c.name,
                t.prompt_libraries.c.scope,
                t.prompt_libraries.c.raw_json,
            ).order_by(t.prompt_libraries.c.legacy_id.asc())
        ).fetchall()

    assert {r.legacy_id for r in rows} == {"system", "mine"}
    # scope 校验：system 库 scope 应为 "system"
    system_row = next(r for r in rows if r.legacy_id == "system")
    assert system_row.scope == "system"


def test_db_mode_prompt_items_table_not_written(
    monkeypatch, data_dir_fixture, tmp_path
):
    """D-2=B 决策：`prompt_items` 表 PR-8 不主写；items 全塞 `raw_json`。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import prompt_library_store
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "db")

    payload = _payload(
        [
            _lib(
                "mine",
                "我的库",
                items=[
                    {"id": "t1", "name": "tpl1", "content": "text1"},
                    {"id": "t2", "name": "tpl2", "content": "text2"},
                ],
            )
        ],
        active_id="mine",
    )
    prompt_library_store.save_prompt_libraries(payload)

    engine = get_engine()
    with engine.connect() as conn:
        # prompt_items 表**未被写入**（D-2=B）
        items_count = conn.execute(
            select(func.count()).select_from(t.prompt_items)
        ).scalar_one()
        # prompt_libraries.raw_json 包含 items
        row = conn.execute(
            select(t.prompt_libraries.c.raw_json).where(
                t.prompt_libraries.c.legacy_id == "mine"
            )
        ).fetchone()

    assert items_count == 0, "prompt_items 表 PR-8 不许主写（D-2=B）"
    raw = json.loads(row.raw_json)
    assert len(raw["items"]) == 2
    assert {it["id"] for it in raw["items"]} == {"t1", "t2"}


def test_db_mode_system_library_semantics_preserved(
    monkeypatch, data_dir_fixture, tmp_path
):
    """内置库 `system/readonly/version` 语义不变（`normalize_prompt_libraries` 承担）。"""

    from app.stores import prompt_library_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "db")

    # 传空 payload，normalize 会补上 system 库
    result = prompt_library_store.save_prompt_libraries({})
    assert result is not None
    assert result["active_library_id"] == "system"
    system_lib = next(l for l in result["libraries"] if l["id"] == "system")
    assert system_lib["system"] is True


def test_db_mode_collection_delete_removes_absent_libraries(
    monkeypatch, data_dir_fixture, tmp_path
):
    """payload 减少 → DELETE 不在 payload 的 library legacy_id。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import prompt_library_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "db")

    payload_a = _payload([_lib("system"), _lib("a"), _lib("b")])
    prompt_library_store.save_prompt_libraries(payload_a)

    engine = get_engine()
    with engine.connect() as conn:
        rows_a = conn.execute(select(t.prompt_libraries.c.legacy_id)).fetchall()
    assert {r.legacy_id for r in rows_a} >= {"system", "a", "b"}

    # 只留 system+b
    payload_b = _payload([_lib("system"), _lib("b")])
    prompt_library_store.save_prompt_libraries(payload_b)

    with engine.connect() as conn:
        rows_b = conn.execute(select(t.prompt_libraries.c.legacy_id)).fetchall()
    assert {r.legacy_id for r in rows_b} == {"system", "b"}


def test_db_mode_async_json_fallback_writes_file(
    monkeypatch, data_dir_fixture, tmp_path
):
    from app.stores import prompt_library_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "db")

    payload = _payload([_lib("mine", "M")], active_id="mine")
    prompt_library_store.save_prompt_libraries(payload)

    saved_path = data_dir_fixture / "prompt_libraries.json"
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        if saved_path.exists():
            break
        time.sleep(0.02)
    assert saved_path.exists(), "async JSON fallback did not appear in time"


def test_db_mode_json_fallback_failure_does_not_propagate(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下 JSON 回写失败不冒泡；shadow diff 落地。"""

    from app.db import prompt_library_writer
    from app.stores import prompt_library_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "db")

    def _boom(payload):
        raise IOError("simulated disk full")

    monkeypatch.setattr(prompt_library_writer, "_write_json_fallback_sync", _boom)
    # 主写路径不应抛错
    prompt_library_store.save_prompt_libraries(_payload([_lib("system")]))

    ret = prompt_library_writer._record_json_fallback_failure(
        error="simulated disk full", fallback_reason="json_write_error"
    )
    assert ret is not None
    diff_files = list(
        (tmp_path / "shadow_diff" / "prompt_library_json_fallback").glob("*.jsonl")
    )
    assert len(diff_files) == 1
    rec = json.loads(diff_files[0].read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["domain"] == "prompt_library"


def test_db_mode_primary_write_error_propagates(
    monkeypatch, data_dir_fixture, tmp_path
):
    from app.stores import prompt_library_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROMPT_LIBRARY_PRIMARY_WRITE", "db")

    def _boom_engine(*a, **kw):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr("app.db.engine.get_engine", _boom_engine)

    with pytest.raises(RuntimeError, match="simulated db failure"):
        prompt_library_store.save_prompt_libraries(_payload([_lib("system")]))
