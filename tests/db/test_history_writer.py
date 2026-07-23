"""数据 PR-12 · GenerationHistory 主写机制契约测试（Wave 3-N.6 Batch 2 主线 B）。

覆盖 T370-T380（11 项 STRONG 级）：

- T370 sys.modules 隔离契约：默认 `json` 模式不加载 `app.db.history_writer`
- T371 默认路径不构造 DB engine
- T372 UPSERT 幂等（同 legacy_id 双写只保留 1 行；含 T372a `record["id"]` 存在
  场景 + T372b `record["id"]` 缺失走合成键兜底）
- T373 5000 条上限硬约束（DB 侧 DELETE oldest · 与 legacy JSON 上限对齐）
- T374 async fallback 落地（db 主写成功后 JSON 异步回写落盘）
- T375 fallback diff jsonl 稳定键位（ts / domain / error / fallback_reason ·
  不含内容体）
- T376 主写失败上抛（non-fallback path · P0 硬约束 #4）
- T377 Settings fail-fast（invalid 值域）
- T378 shadow_diff 无密钥泄漏（record 深度嵌套字段注入 sentinel · shadow diff
  jsonl grep 5 类 = 0 命中）
- T379 跨 domain sentinel 抗回归（DB dump grep = 0 命中 · 参照 PR-9 T9 pattern）
- T380 legacy JSON round-trip 兼容（json 模式行为与 baseline 完全一致）

护栏来源：任务书 · Wave 3-N.6 Batch 2 主线 B · 数据 PR-12。
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def data_dir_fixture(tmp_path, monkeypatch, isolated_env):
    """把 `DATA_DIR` / `HISTORY_FILE` 指到 tmp_path。"""

    import main

    data_dir = tmp_path
    history_path = data_dir / "history.json"
    monkeypatch.setattr(main, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main, "HISTORY_FILE", str(history_path))
    yield data_dir


def _record(
    *,
    rid: str | None = "r1",
    timestamp: float = 1000.0,
    prompt: str = "sample prompt",
    images: list[str] | None = None,
    **extras,
) -> dict:
    """构造 legacy `save_to_history` 消费的 record。"""

    rec: dict = {
        "timestamp": timestamp,
        "type": "zimage",
        "images": images if images is not None else ["assets/output/a.png"],
        "prompt": prompt,
    }
    if rid is not None:
        rec["id"] = rid
    rec.update(extras)
    return rec


# ---------------------------------------------------------------------------
# T370 · sys.modules 隔离契约（P0 硬约束 #3）
# ---------------------------------------------------------------------------


def test_T370_default_json_mode_does_not_import_writer(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`HISTORY_PRIMARY_WRITE` 未设 / 显式 `json` 时 `app.db.history_writer`
    从未 import（P0 硬约束 #3 · 数据 PR-12 默认路径隔离）。"""

    monkeypatch.delenv("HISTORY_PRIMARY_WRITE", raising=False)
    sys.modules.pop("app.db.history_writer", None)

    from app.stores import history_store

    history_store.save_to_history(_record())

    assert "app.db.history_writer" not in sys.modules, (
        "P0 硬约束违反：默认 `json` 模式下拉起了 app.db.history_writer"
    )
    # legacy save 走的 HISTORY_FILE 应存在
    assert (data_dir_fixture / "history.json").exists()

    # 不落 fallback diff
    fallback_dir = tmp_path / "shadow_diff" / "history_json_fallback"
    assert not fallback_dir.exists()


# ---------------------------------------------------------------------------
# T371 · 默认路径不构造 DB engine
# ---------------------------------------------------------------------------


def test_T371_default_json_mode_does_not_construct_engine(
    monkeypatch, data_dir_fixture, tmp_path
):
    """默认 `json` 模式 · `save_to_history` 不构造 DB engine。"""

    monkeypatch.delenv("HISTORY_PRIMARY_WRITE", raising=False)

    from app.db import engine as db_engine

    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when json mode")

    monkeypatch.setattr(db_engine, "get_engine", _fail)

    from app.stores import history_store

    history_store.save_to_history(_record())

    assert hits["count"] == 0


# ---------------------------------------------------------------------------
# T372 · UPSERT 幂等（两条支线）
# ---------------------------------------------------------------------------


def test_T372a_upsert_idempotent_with_explicit_id(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T372a · `record["id"]` 存在 · 二次 save 覆盖不新增行（DB 侧单行）。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")

    from app.stores import history_store

    history_store.save_to_history(_record(rid="stable_id", prompt="v1"))
    history_store.save_to_history(_record(rid="stable_id", prompt="v2"))
    history_store.save_to_history(_record(rid="stable_id", prompt="v3"))

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(t.generation_history)
        ).scalar_one()
        raw = conn.execute(
            select(t.generation_history.c.raw_json).where(
                t.generation_history.c.legacy_id == "stable_id"
            )
        ).scalar_one()

    assert count == 1, f"UPSERT 幂等破裂 · 期望 1 行 · 实际 {count}"
    payload = json.loads(raw)
    assert payload["prompt"] == "v3", "覆盖失败 · raw_json 未随 UPSERT 更新"


def test_T372b_upsert_idempotent_via_synthesized_key(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T372b · `record["id"]` 缺失 · 走 `_synthesize_history_legacy_id`
    兜底；相同 task_id/request_id/timestamp/prompt_summary 二次 save 幂等。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")

    from app.stores import history_store

    rec = {
        "type": "zimage",
        "task_id": "task_abc",
        "request_id": "req_xyz",
        "timestamp": 2000.5,
        "prompt": "same prompt",
        "images": ["assets/output/x.png"],
    }
    history_store.save_to_history(dict(rec))
    history_store.save_to_history(dict(rec))
    history_store.save_to_history(dict(rec))

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(t.generation_history)
        ).scalar_one()

    assert count == 1, (
        f"合成键幂等破裂 · 相同输入 3 次 save 应只 1 行 · 实际 {count}"
    )

    # 同一 record 二次调用合成键必须完全一致（幂等契约）
    from app.db.history_writer import _synthesize_history_legacy_id

    k1 = _synthesize_history_legacy_id(rec)
    k2 = _synthesize_history_legacy_id(rec)
    assert k1 == k2 and len(k1) == 16


# ---------------------------------------------------------------------------
# T373 · 5000 条上限硬约束（DB 侧 DELETE oldest）
# ---------------------------------------------------------------------------


def test_T373_max_records_trim_oldest(monkeypatch, data_dir_fixture, tmp_path):
    """DB 侧 DELETE oldest 保持 ≤5000 条上限（与 legacy JSON `history[:5000]`
    对齐 · GM-06 兼容契约）。

    为避免测试时间成本，直接把 HISTORY_MAX_RECORDS monkeypatch 到小值验证机制。
    """

    from app.data_import import tables as t
    from app.db import history_writer
    from app.db.engine import get_engine
    from sqlalchemy import func, select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")
    monkeypatch.setattr(history_writer, "HISTORY_MAX_RECORDS", 3)

    from app.stores import history_store

    # 塞 5 条不同 id 的 record（timestamp 单调递增 · 便于验证保留最新）
    for i in range(5):
        history_store.save_to_history(
            _record(rid=f"rec_{i:03d}", timestamp=3000.0 + i, prompt=f"p{i}")
        )

    engine = get_engine()
    with engine.connect() as conn:
        count = conn.execute(
            select(func.count()).select_from(t.generation_history)
        ).scalar_one()
        remaining = conn.execute(
            select(t.generation_history.c.legacy_id).order_by(
                t.generation_history.c.created_at.desc()
            )
        ).fetchall()

    assert count == 3, f"5000 条上限契约破裂 · 上限 3 · 实际 {count}"
    remaining_ids = {row.legacy_id for row in remaining}
    # 保留 timestamp 最新的 3 条 → rec_002 / rec_003 / rec_004
    assert remaining_ids == {"rec_002", "rec_003", "rec_004"}, (
        f"DELETE oldest 顺序错误 · 应保留最新 3 条 · 实际 {remaining_ids}"
    )


# ---------------------------------------------------------------------------
# T374 · async fallback 落地
# ---------------------------------------------------------------------------


def test_T374_db_mode_async_fallback_writes_history_file(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下写成功后 JSON 异步回写落地；`history.json` 承接 legacy
    `save_to_history` 落盘 shape（`history.insert(0, record)` + `[:5000]`
    + indent=4）。"""

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")

    from app.stores import history_store

    history_store.save_to_history(_record(rid="rec_fb1", timestamp=4000.0))

    saved_path = data_dir_fixture / "history.json"
    deadline = time.perf_counter() + 1.5
    while time.perf_counter() < deadline:
        if saved_path.exists():
            break
        time.sleep(0.02)

    assert saved_path.exists(), "async JSON fallback file did not appear in time"
    loaded = json.loads(saved_path.read_text(encoding="utf-8"))
    assert isinstance(loaded, list)
    assert loaded[0]["id"] == "rec_fb1"


# ---------------------------------------------------------------------------
# T375 · fallback diff jsonl 稳定键位（不含内容体）
# ---------------------------------------------------------------------------


def test_T375_json_fallback_failure_diff_stable_keys(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下 JSON 回写失败（IO 异常）不冒泡；shadow diff 端到端落地 ·
    键位严格 `{ts, domain, error, fallback_reason}` · 不含内容体。"""

    import main

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")

    # 指向不存在的父目录 → open() 抛 FileNotFoundError
    monkeypatch.setattr(
        main,
        "HISTORY_FILE",
        str(tmp_path / "nonexistent_dir" / "history.json"),
    )

    from app.db import history_writer

    # 让 makedirs 也失败：把 os.makedirs 打桩失败
    orig_makedirs = os.makedirs

    def _boom_makedirs(path, *a, **kw):
        # 只让 history 目录的 makedirs 失败，diff 目录的 makedirs 保持成功
        if "nonexistent_dir" in str(path):
            raise OSError("simulated makedirs failure")
        return orig_makedirs(path, *a, **kw)

    monkeypatch.setattr(
        "app.db.history_writer.os.makedirs", _boom_makedirs
    )

    from app.stores import history_store

    # 主写路径不应抛错
    history_store.save_to_history(_record(rid="rec_fail", timestamp=5000.0))

    # 等待异步 fallback 走完真实链路
    diff_dir = tmp_path / "shadow_diff" / "history_json_fallback"
    deadline = time.perf_counter() + 2.0
    diff_files: list = []
    while time.perf_counter() < deadline:
        if diff_dir.exists():
            diff_files = list(diff_dir.glob("*.jsonl"))
            if diff_files:
                break
        time.sleep(0.02)

    assert diff_files, "端到端 fallback diff 链路应真实产生 jsonl 文件"
    rec = json.loads(
        diff_files[0].read_text(encoding="utf-8").strip().splitlines()[-1]
    )
    assert rec["domain"] == "generation_history"
    assert rec["fallback_reason"] == "json_write_error"
    # 稳定键位断言：只有 4 个 key · 不含内容体
    assert set(rec.keys()) == {"ts", "domain", "error", "fallback_reason"}


# ---------------------------------------------------------------------------
# T376 · db 主写失败必须上抛
# ---------------------------------------------------------------------------


def test_T376_db_mode_write_error_raises(
    monkeypatch, data_dir_fixture, tmp_path
):
    """DB 主写失败必须上抛，不允许 fallback 到 JSON 主写（P0 硬约束 #4）。"""

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")

    def _boom_engine(*a, **kw):
        raise RuntimeError("simulated history db failure")

    monkeypatch.setattr("app.db.engine.get_engine", _boom_engine)

    from app.stores import history_store

    with pytest.raises(RuntimeError, match="simulated history db failure"):
        history_store.save_to_history(_record(rid="rec_err"))

    # 主写抛错时 JSON 回写不应触发
    saved_path = data_dir_fixture / "history.json"
    time.sleep(0.1)
    assert not saved_path.exists()


# ---------------------------------------------------------------------------
# T377 · Settings fail-fast（invalid 值域）
# ---------------------------------------------------------------------------


def test_T377_env_value_out_of_range_raises(monkeypatch):
    """`HISTORY_PRIMARY_WRITE=invalid` → Settings 层 fail-fast。"""

    import main

    from app.shared.settings import get_settings

    monkeypatch.setattr(main, "HISTORY_PRIMARY_WRITE", "invalid")
    with pytest.raises(ValueError, match="Invalid HISTORY_PRIMARY_WRITE"):
        get_settings()


# ---------------------------------------------------------------------------
# T378 · shadow_diff 无密钥泄漏（sentinel 深度嵌套 · 5 类 grep = 0）
# ---------------------------------------------------------------------------


def test_T378_shadow_diff_no_secret_leak_deep_nested(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`record` 任意深度嵌套字段（`provider.raw_response.*` / `nested.Bearer`
    / 顶层 `api_key`）注入 sentinel → shadow_diff jsonl grep 5 类 = 0 命中
    （P0 硬约束 #5 · 稳定键位不含内容体）。"""

    import main

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")

    # 触发 fallback diff 落盘
    monkeypatch.setattr(
        main,
        "HISTORY_FILE",
        str(tmp_path / "nope_dir" / "history.json"),
    )
    orig_makedirs = os.makedirs

    def _boom_makedirs(path, *a, **kw):
        if "nope_dir" in str(path):
            raise OSError("simulated")
        return orig_makedirs(path, *a, **kw)

    monkeypatch.setattr("app.db.history_writer.os.makedirs", _boom_makedirs)

    sentinels = {
        "api_key": "AKIA_SENTINEL_TOP",
        "access_token": "AT_SENTINEL",
        "secret": "SECRET_SENTINEL",
        "password": "PWD_SENTINEL",
        "bearer": "BR_SENTINEL",
    }
    # 深度嵌套注入
    rec = _record(rid="rec_sentinel", api_key=sentinels["api_key"])
    rec["provider"] = {
        "raw_response": {"access_token": sentinels["access_token"]},
        "config": {"secret": sentinels["secret"]},
    }
    rec["auth"] = {"password": sentinels["password"]}
    rec["nested_list"] = [
        {"Bearer": sentinels["bearer"], "safe_url": "https://ok.example.com"},
    ]

    from app.stores import history_store

    history_store.save_to_history(rec)

    # 等待 fallback diff
    diff_dir = tmp_path / "shadow_diff" / "history_json_fallback"
    deadline = time.perf_counter() + 2.0
    while time.perf_counter() < deadline:
        if diff_dir.exists() and list(diff_dir.glob("*.jsonl")):
            break
        time.sleep(0.02)

    # 断言 A：diff jsonl 中不出现任一 sentinel
    if diff_dir.exists():
        for jsonl_file in diff_dir.glob("*.jsonl"):
            content = jsonl_file.read_text(encoding="utf-8")
            for label, value in sentinels.items():
                assert value not in content, (
                    f"P0 破裂 · sentinel {value!r}（{label}）出现在 "
                    f"history_json_fallback/{jsonl_file.name}"
                )


# ---------------------------------------------------------------------------
# T379 · 跨 domain sentinel 抗回归（DB dump grep = 0）
# ---------------------------------------------------------------------------


def test_T379_db_raw_json_no_secret_leak_deep_nested(
    monkeypatch, data_dir_fixture, tmp_path
):
    """深度嵌套 sentinel record → 落 DB 后 SELECT raw_json + 全库 dump grep
    5 类 = 0 命中（P0 硬约束 #5 · raw_json 承载前已由 `_safe_history_record`
    深度剪枝）。参照 PR-9 T9 pattern · 但对 history 而言是数据面 sentinel。"""

    import sqlite3

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "db")

    sentinels = {
        "api_key": "AKIA_DB_TOP",
        "access_token": "AT_DB",
        "secret": "SECRET_DB",
        "password": "PWD_DB",
        "bearer": "BR_DB",
    }
    rec = _record(rid="rec_db_sent", api_key=sentinels["api_key"])
    rec["provider"] = {
        "raw_response": {"access_token": sentinels["access_token"]},
        "secret_key": sentinels["secret"],
    }
    rec["auth"] = {"password": sentinels["password"]}
    rec["Bearer"] = sentinels["bearer"]

    from app.stores import history_store

    history_store.save_to_history(rec)

    # SELECT raw_json 断言
    engine = get_engine()
    with engine.connect() as conn:
        raw_json = conn.execute(
            select(t.generation_history.c.raw_json).where(
                t.generation_history.c.legacy_id == "rec_db_sent"
            )
        ).scalar_one()

    for label, value in sentinels.items():
        assert value not in raw_json, (
            f"P0 破裂 · raw_json 中残留 sentinel {value!r}（{label}）· "
            f"深度剪枝失效"
        )

    # 全库 dump grep（sqlite level · 覆盖所有字段，含索引）
    import main

    con = sqlite3.connect(main.DATA_DB_PATH)
    try:
        dump = "\n".join(con.iterdump())
    finally:
        con.close()
    for label, value in sentinels.items():
        assert value not in dump, (
            f"P0 破裂 · DB dump grep 命中 sentinel {value!r}（{label}）"
        )


# ---------------------------------------------------------------------------
# T380 · legacy JSON round-trip 兼容
# ---------------------------------------------------------------------------


def test_T380_json_mode_legacy_round_trip(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`HISTORY_PRIMARY_WRITE=json` 模式行为与 legacy 完全一致：

    - 走 `main.save_to_history` · `HISTORY_FILE` 是 list · `history.insert(0, record)`
    - `record["timestamp"]` 由 legacy 加上（若 record 无）
    - 上限 `[:5000]`
    - 不 import writer
    """

    monkeypatch.setenv("HISTORY_PRIMARY_WRITE", "json")
    sys.modules.pop("app.db.history_writer", None)

    from app.stores import history_store

    # legacy save_to_history 会加 timestamp
    r1 = {"type": "zimage", "images": ["assets/output/x.png"], "prompt": "a"}
    r2 = {"type": "zimage", "images": ["assets/output/y.png"], "prompt": "b"}
    history_store.save_to_history(r1)
    history_store.save_to_history(r2)

    saved = json.loads(
        (data_dir_fixture / "history.json").read_text(encoding="utf-8")
    )
    # legacy `history.insert(0, record)` 语义 · r2 在最前
    assert saved[0]["prompt"] == "b"
    assert saved[1]["prompt"] == "a"
    # legacy 加过 timestamp
    assert isinstance(saved[0]["timestamp"], (int, float))
    assert "app.db.history_writer" not in sys.modules


# ---------------------------------------------------------------------------
# 顶注跨模块引用抗回归（GM-04 pattern · T379 已删 legacy · 这里补硬约束）
# ---------------------------------------------------------------------------


def test_history_writer_does_not_import_task_domain_writer():
    """`app/db/history_writer.py` 顶层 body 不 import `app.task.history.writer`
    （避免未来跨子系统漂移 · GM-04 pattern · 硬护栏原任务书要求）。"""

    src = (
        REPO_ROOT / "app" / "db" / "history_writer.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("app.task.history"), (
                f"`app/db/history_writer.py` 不得 import `app.task.history.*` "
                f"（发现 from {node.module} ...）· 顶注硬约束 · 两个 writer 域分离"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("app.task.history"), (
                    f"`app/db/history_writer.py` 不得 import `app.task.history.*`"
                    f"（发现 import {alias.name}）· 顶注硬约束"
                )
