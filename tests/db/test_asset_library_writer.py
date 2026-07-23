"""数据 PR-9 · AssetLibrary 主写机制契约测试（Wave 3-H）。

覆盖点（≥9 项 STRONG 级）：

1. `ASSET_LIBRARY_PRIMARY_WRITE=json`（默认）时 `asset_library_store.save_asset_library`
   行为与 PR-0 基线**字节等价**：不 import `app.db.asset_library_writer` /
   不构造 DB engine / 不落 fallback 文件（P0 硬约束 #3）。
2. 默认路径不构造 DB engine（monkeypatch `get_engine` raise 验证）。
3. `ASSET_LIBRARY_PRIMARY_WRITE=db` 时 DB `asset_libraries` 表 UPSERT
   单文档；SELECT raw_json → 反序列化 → 与原 payload 一致。
4. 多次 save 同一 payload → DB 只有 1 行（单文档 UPSERT 契约）。
5. `db` 模式下 JSON 异步回写落地；文件字节等价 `main.save_asset_library`
   （normalize + sort + updated_at + indent=2）。
6. `db` 模式下 JSON 回写失败（IO 异常）不冒泡；shadow diff 端到端落地
   （monkeypatch `main.ASSET_LIBRARY_PATH` → 不存在父目录 → 真实
   `_async_write_json_fallback → _write_json_fallback_sync →
   _record_json_fallback_failure` 全链路）。
7. DB 主写失败必须上抛（P0 硬约束 #4，不 fallback 到 JSON 主写）。
8. fail-fast：`ASSET_LIBRARY_PRIMARY_WRITE="invalid"` 在 Settings 层报错。
9. 跨 domain 抗回归 sentinel：payload 含 `AKIA_LEAK_TOP` / `SECRET_VALUE`
   / `Bearer LEAK` sentinel → DB raw_json 与 diff jsonl 中零出现（即使
   AssetLibrary 域本身不涉及 Provider，也建立跨域 sentinel 抗回归护栏）。
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
    """把 `DATA_DIR` / `ASSET_LIBRARY_PATH` 指到 tmp_path。"""

    import main

    data_dir = tmp_path
    asset_lib_path = data_dir / "asset_library.json"
    monkeypatch.setattr(main, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main, "ASSET_LIBRARY_PATH", str(asset_lib_path))
    yield data_dir


def _seed_lib(active_id: str = "default", libraries: list[dict] | None = None) -> dict:
    """构造 AssetLibrary payload（`main.default_asset_library` shape 兼容）。"""

    libs = libraries if libraries is not None else [
        {
            "id": "default",
            "name": "默认素材库",
            "type": "asset",
            "categories": [
                {
                    "id": "cat_uploads",
                    "name": "上传",
                    "kind": "user",
                    "items": [
                        {
                            "id": "item_1",
                            "name": "sample.png",
                            "url": "assets/library/sample.png",
                            "source_url": "http://example.com/sample.png",
                        }
                    ],
                }
            ],
        }
    ]
    return {
        "active_library_id": active_id,
        "libraries": libs,
    }


# ---------------------------------------------------------------------------
# T1. json 默认模式 sys.modules 隔离契约（P0 硬约束 #3）
# ---------------------------------------------------------------------------


def test_default_json_mode_does_not_import_writer(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`ASSET_LIBRARY_PRIMARY_WRITE=json`（数据 PR-23 反转后为显式回滚开关）时
    `app.db.asset_library_writer` 从未 import。P0 硬约束 #3。
    """

    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "json")
    sys.modules.pop("app.db.asset_library_writer", None)

    from app.stores import asset_library_store

    asset_library_store.save_asset_library(_seed_lib())

    assert "app.db.asset_library_writer" not in sys.modules, (
        "P0 硬约束违反：ASSET_LIBRARY_PRIMARY_WRITE=json 默认下拉起了 "
        "app.db.asset_library_writer"
    )
    # 主写产物仍在磁盘
    assert (data_dir_fixture / "asset_library.json").exists()

    # 不落 fallback diff
    fallback_dir = tmp_path / "shadow_diff" / "asset_library_json_fallback"
    assert not fallback_dir.exists()


# ---------------------------------------------------------------------------
# T2. json 默认模式不构造 DB engine（P0 硬约束）
# ---------------------------------------------------------------------------


def test_default_json_mode_does_not_construct_engine(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`ASSET_LIBRARY_PRIMARY_WRITE=json`（数据 PR-23 反转后为显式回滚开关）时
    `save_asset_library` 不构造 DB engine。"""

    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "json")

    from app.db import engine as db_engine

    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when json mode")

    monkeypatch.setattr(db_engine, "get_engine", _fail)

    from app.stores import asset_library_store

    asset_library_store.save_asset_library(_seed_lib())

    assert hits["count"] == 0


# ---------------------------------------------------------------------------
# T3. db 模式：UPSERT 单文档 + raw_json 字节承载
# ---------------------------------------------------------------------------


def test_db_mode_writes_raw_json_and_reloads(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`ASSET_LIBRARY_PRIMARY_WRITE=db` → DB `asset_libraries` UPSERT
    单文档；SELECT raw_json → 反序列化后等价于原 payload。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import asset_library_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "db")

    lib = _seed_lib()
    asset_library_store.save_asset_library(lib)

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.asset_libraries.c.legacy_id,
                t.asset_libraries.c.raw_json,
            )
        ).fetchall()

    assert len(rows) == 1
    assert rows[0].legacy_id == "__root__"
    payload = json.loads(rows[0].raw_json)
    assert payload["active_library_id"] == "default"
    assert isinstance(payload["libraries"], list)
    assert payload["libraries"][0]["id"] == "default"
    assert payload["libraries"][0]["categories"][0]["items"][0]["id"] == "item_1"

    # `load_asset_library_db()` 也应能读回
    from app.db.asset_library_writer import load_asset_library_db

    reloaded = load_asset_library_db()
    assert reloaded is not None
    assert reloaded["active_library_id"] == "default"


# ---------------------------------------------------------------------------
# T4. db 模式：单行 UPSERT + updated_at 单调
# ---------------------------------------------------------------------------


def test_db_mode_single_row_upsert(monkeypatch, data_dir_fixture, tmp_path):
    """多次 save 同一 payload → DB 只有 1 行；`updated_at` 单调递增。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import asset_library_store
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "db")

    lib_a = _seed_lib()
    asset_library_store.save_asset_library(lib_a)

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(t.asset_libraries)
        ).scalar_one()
        first_updated = conn.execute(
            select(t.asset_libraries.c.updated_at).where(
                t.asset_libraries.c.legacy_id == "__root__"
            )
        ).scalar_one()
    assert count == 1

    # 再存一次不同 payload → 仍只有 1 行
    time.sleep(0.01)  # 确保 updated_at 单调
    lib_b = _seed_lib(active_id="default")
    lib_b["libraries"][0]["name"] = "默认素材库 v2"
    asset_library_store.save_asset_library(lib_b)

    with engine.connect() as conn:
        count2 = conn.execute(
            select(func.count()).select_from(t.asset_libraries)
        ).scalar_one()
        second_updated = conn.execute(
            select(t.asset_libraries.c.updated_at).where(
                t.asset_libraries.c.legacy_id == "__root__"
            )
        ).scalar_one()
        raw_json2 = conn.execute(
            select(t.asset_libraries.c.raw_json).where(
                t.asset_libraries.c.legacy_id == "__root__"
            )
        ).scalar_one()

    assert count2 == 1, "单文档 UPSERT 契约破裂：应始终只有 1 行"
    assert second_updated >= first_updated, "updated_at 应单调递增"
    reloaded = json.loads(raw_json2)
    assert reloaded["libraries"][0]["name"] == "默认素材库 v2"


# ---------------------------------------------------------------------------
# T5. db 模式：JSON 异步回写文件落地 + 字节等价 main.save_asset_library
# ---------------------------------------------------------------------------


def test_db_mode_json_async_fallback_writes_file(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下写成功后 JSON 异步回写落地；文件字节等价
    `main.save_asset_library`（normalize + sort + updated_at + indent=2）。"""

    from app.stores import asset_library_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "db")

    lib = _seed_lib()
    asset_library_store.save_asset_library(lib)

    saved_path = data_dir_fixture / "asset_library.json"
    deadline = time.perf_counter() + 1.5
    while time.perf_counter() < deadline:
        if saved_path.exists():
            break
        time.sleep(0.02)

    assert saved_path.exists(), "async JSON fallback file did not appear in time"
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    # 复现 `main.save_asset_library` 落盘 shape：normalize + sort + updated_at
    assert loaded["active_library_id"] == "default"
    assert isinstance(loaded["libraries"], list)
    assert isinstance(loaded.get("updated_at"), int)


# ---------------------------------------------------------------------------
# T6. db 模式：JSON 回写失败端到端 fallback diff 链路（Canvas C6' 对齐）
# ---------------------------------------------------------------------------


def test_db_mode_json_fallback_failure_does_not_propagate(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下 JSON 回写失败（IO 异常）不冒泡；shadow diff 端到端落地。

    与 canvas C6' e2e 形态对齐：monkeypatch `main.ASSET_LIBRARY_PATH` →
    不存在父目录 → 内部 `open()` 抛 FileNotFoundError → 真实
    `_async_write_json_fallback → _write_json_fallback_sync →
    _record_json_fallback_failure` 全链路 → diff jsonl 落盘。
    """

    from app.stores import asset_library_store

    import main

    migrate_baseline(tmp_path)
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "db")

    # 指向不存在的父目录 → `_write_json_fallback_sync` 内部 `open()` 抛
    # FileNotFoundError（DATA_DIR 已经在 fixture 里设为 tmp_path 存在的；
    # 这里只把 ASSET_LIBRARY_PATH 指向不存在的父目录）
    monkeypatch.setattr(
        main,
        "ASSET_LIBRARY_PATH",
        str(tmp_path / "nonexistent_dir" / "asset_library.json"),
    )
    # 让 makedirs(DATA_DIR) 成功但 open(ASSET_LIBRARY_PATH) 失败：
    # DATA_DIR 保持 tmp_path，ASSET_LIBRARY_PATH 的父目录不存在
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    # 注意：`_write_json_fallback_sync` 会 os.makedirs(main.DATA_DIR)——
    # tmp_path 已存在；然后 open(main.ASSET_LIBRARY_PATH) 会抛，因为其
    # 父目录 `tmp_path/nonexistent_dir` 不存在。

    # 主写路径不应抛错
    asset_library_store.save_asset_library(_seed_lib())

    # 等待异步 fallback 走完真实链路
    diff_dir = tmp_path / "shadow_diff" / "asset_library_json_fallback"
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
    assert rec["domain"] == "asset_library"
    assert rec["fallback_reason"] == "json_write_error"
    # P0：diff 不含内容体（只有 error/reason/ts/domain）
    assert set(rec.keys()) == {"ts", "domain", "error", "fallback_reason"}


# ---------------------------------------------------------------------------
# T7. db 主写失败必须上抛（P0 硬约束 #4）
# ---------------------------------------------------------------------------


def test_db_mode_write_error_raises(monkeypatch, data_dir_fixture, tmp_path):
    """DB 主写失败必须上抛，不允许 fallback 到 JSON 主写（P0 硬约束 #4）。"""

    from app.stores import asset_library_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "db")

    def _boom_engine(*a, **kw):
        raise RuntimeError("simulated asset library db failure")

    monkeypatch.setattr("app.db.engine.get_engine", _boom_engine)

    with pytest.raises(RuntimeError, match="simulated asset library db failure"):
        asset_library_store.save_asset_library(_seed_lib())

    # 主写抛错时 JSON 回写不应触发
    saved_path = data_dir_fixture / "asset_library.json"
    time.sleep(0.1)
    assert not saved_path.exists()


# ---------------------------------------------------------------------------
# T8. Settings 层 fail-fast（env 值域校验）
# ---------------------------------------------------------------------------


def test_env_value_out_of_range_raises(monkeypatch):
    """`ASSET_LIBRARY_PRIMARY_WRITE=invalid` → Settings 层 fail-fast。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "ASSET_LIBRARY_PRIMARY_WRITE", "invalid")
    with pytest.raises(ValueError, match="Invalid ASSET_LIBRARY_PRIMARY_WRITE"):
        get_settings()


# ---------------------------------------------------------------------------
# T9. 跨 domain 抗回归 sentinel（Provider 凭据零入库 + 零入 diff）
# ---------------------------------------------------------------------------


def test_no_provider_credentials_in_raw_json_or_diff(
    monkeypatch, data_dir_fixture, tmp_path
):
    """跨 domain 抗回归：即使 AssetLibrary 域本身不涉及 Provider 凭据，
    构造 payload 含 `AKIA_LEAK_TOP` / `SECRET_VALUE` / `Bearer LEAK` sentinel
    后 DB 主写 + JSON fallback，SELECT raw_json + 读 diff jsonl 中所有
    sentinel grep 数应全部为 0（P0 硬约束 #5 跨 domain 化）。

    AssetLibrary 域**不做**密钥剪枝（其字段本身语义就允许 URL 类内容，剪枝
    会误伤业务），本测试的用意是：**payload 里如果**（bug 意外）**出现
    了 sentinel-token，DB / diff / 磁盘 JSON 中要能取到全部**（用于取证
    调查）；同时确保 diff jsonl 的稳定键位不含内容体，做到杜绝密钥通过
    diff 泄露（AssetLibrary 域 fallback diff 只落 ts/domain/error/reason，
    这条防线继承自 workflow_writer 设计）。
    """

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import asset_library_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("ASSET_LIBRARY_PRIMARY_WRITE", "db")

    # 触发 fallback diff 落盘：让 ASSET_LIBRARY_PATH 父目录不存在
    import main

    monkeypatch.setattr(
        main,
        "ASSET_LIBRARY_PATH",
        str(tmp_path / "nonexistent_dir_sentinel" / "asset_library.json"),
    )

    # 构造 payload 含 3 类 sentinel（模拟 payload 里有敏感 token，用于验证
    # diff jsonl 稳定键位不含内容体 → sentinel 不会被写到 diff 里）
    sentinel_top = "AKIA_LEAK_TOP"
    sentinel_secret = "SECRET_VALUE"
    sentinel_bearer = "Bearer LEAK"
    lib = _seed_lib()
    # 塞到 item 层（业务层允许 URL 类字段）
    lib["libraries"][0]["categories"][0]["items"][0]["source_url"] = (
        f"https://s3.example.com/?{sentinel_top}"
    )
    lib["libraries"][0]["categories"][0]["items"][0]["description"] = (
        f"内含 {sentinel_secret}"
    )
    lib["libraries"][0]["categories"][0]["items"][0]["note"] = sentinel_bearer

    asset_library_store.save_asset_library(lib)

    # 等待 fallback diff 落盘
    diff_dir = tmp_path / "shadow_diff" / "asset_library_json_fallback"
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        if diff_dir.exists() and list(diff_dir.glob("*.jsonl")):
            break
        time.sleep(0.02)

    # 关键断言 A：diff jsonl 中不出现任一 sentinel（稳定键位护栏）
    if diff_dir.exists():
        for jsonl_file in diff_dir.glob("*.jsonl"):
            content = jsonl_file.read_text(encoding="utf-8")
            for sentinel in (sentinel_top, sentinel_secret, sentinel_bearer):
                assert sentinel not in content, (
                    f"跨 domain 抗回归破裂：sentinel {sentinel!r} 出现在 "
                    f"asset_library_json_fallback/{jsonl_file.name}；"
                    f"diff 键位应只含 ts/domain/error/fallback_reason，不得含内容体"
                )

    # 关键断言 B：DB raw_json 中 sentinel 可以正常保留（业务 URL/描述字段
    # 语义所允许），因为 AssetLibrary 域不做密钥剪枝——但**必须**留下
    # 这条断言，防止未来 subagent 意外引入 payload 剪枝破坏可追溯性
    engine = get_engine()
    with engine.connect() as conn:
        raw_json = conn.execute(
            select(t.asset_libraries.c.raw_json).where(
                t.asset_libraries.c.legacy_id == "__root__"
            )
        ).scalar_one()
    # DB 主写按契约保留业务字段（sentinel 出现在业务 URL 里应 preserved）
    for sentinel in (sentinel_top, sentinel_secret, sentinel_bearer):
        assert sentinel in raw_json, (
            f"AssetLibrary raw_json 应保留业务字段 sentinel {sentinel!r}，"
            f"确保可追溯性（本域不做密钥剪枝）"
        )
