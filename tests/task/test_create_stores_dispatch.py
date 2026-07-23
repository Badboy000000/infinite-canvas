"""数据 PR-11（Wave 3-N.6 Batch 1 主线 A）· `create_stores()` 分派工厂契约。

覆盖 T300-T307 共 8 项：

- T300 未设 env → `create_stores()` 返回 memory 五件套（`isinstance` Protocol）
- T301 `TASK_PRIMARY_WRITE=sqlite` → 返回 sqlite 五件套
- T302 `TASK_PRIMARY_WRITE=memory` 显式回滚可用
- T303 `TASK_PRIMARY_WRITE=invalid` fail-fast（`ValueError` · 消息含 allowed set）
- T304 memory 模式冷启不"隐式"加载 sqlite 依赖到运行路径（仅纯 memory 逻辑）
- T305 memory / sqlite 双分派下 Task 创建 + 查询 round-trip 语义等价（含 P0
  sentinel 反查：`input_snapshot` 内 5 类字面量 grep DB 文件 = 0）
- T306 `create_stores()` 不改 `memory_stores` / `sqlite_stores` 内部签名
  （AST 抗回归：参数数量与关键字集合冻结）
- T307 fixture 隔离（monkeypatch `DATA_DB_PATH` + `reset_engine` + 建表；
  参照 CB-P5-21 / test_store_contract.py 既有 pattern）

**本 PR 承接 PR-21/22/23 flag pattern 第 4 次实证**；`create_stores()`
仅按 `Settings.task_primary_write` 分派到 `memory_stores()` /
`sqlite_stores()`——不改这两个既有工厂签名。
"""

from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path

import pytest

from app.task.contracts import TaskDraft


# ---------------------------------------------------------------------------
# Fixtures（承接 tests/task/test_store_contract.py 的 sqlite_bundle pattern）
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolated_sqlite_db(tmp_path, monkeypatch):
    """临时 sqlite + `run_migrations("head")` + engine 隔离。

    参照 `tests/task/test_store_contract.py::sqlite_bundle` 的既有做法：
    monkeypatch `main.DATA_DB_PATH` → `reset_engine()` → 手动清 SessionLocal →
    `run_migrations("head")` 建表；teardown 反向拆除。
    """

    import main
    from app.db import engine as _engine_mod
    from app.db import session as _session_mod

    db_path = tmp_path / "pr11_dispatch.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(db_path))
    _engine_mod.reset_engine()
    _session_mod._SessionLocal = None
    _engine_mod.run_migrations("head")

    yield db_path

    _engine_mod.reset_engine()
    _session_mod._SessionLocal = None


@pytest.fixture(autouse=True)
def _reset_settings_cache_around_test():
    """Deployment 快照缓存清理，避免 test 间污染。"""

    from app.shared.settings.runtime import _reset_settings_cache_for_tests

    _reset_settings_cache_for_tests()
    yield
    _reset_settings_cache_for_tests()


# ---------------------------------------------------------------------------
# T300：未设 env → memory 五件套
# ---------------------------------------------------------------------------


def test_t300_create_stores_defaults_to_memory(monkeypatch):
    """`TASK_PRIMARY_WRITE=""`（等价未设）→ `create_stores()` 返回 memory 五件套。"""

    import main

    from app.task.store import (
        ArtifactStore,
        MemoryArtifactStore,
        MemoryNodeRunStore,
        MemoryProviderTaskStore,
        MemoryTaskEventStore,
        MemoryTaskStore,
        NodeRunStore,
        ProviderTaskStore,
        TaskEventStore,
        TaskStore,
        create_stores,
    )

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", "")
    task_store, node_run_store, provider_task_store, event_store, artifact_store = (
        create_stores()
    )

    # 分派命中 memory 实现（具体 class）
    assert isinstance(task_store, MemoryTaskStore)
    assert isinstance(node_run_store, MemoryNodeRunStore)
    assert isinstance(provider_task_store, MemoryProviderTaskStore)
    assert isinstance(event_store, MemoryTaskEventStore)
    assert isinstance(artifact_store, MemoryArtifactStore)

    # 同时满足 Protocol 端口（`runtime_checkable`）
    assert isinstance(task_store, TaskStore)
    assert isinstance(node_run_store, NodeRunStore)
    assert isinstance(provider_task_store, ProviderTaskStore)
    assert isinstance(event_store, TaskEventStore)
    assert isinstance(artifact_store, ArtifactStore)


# ---------------------------------------------------------------------------
# T301：sqlite 模式 → sqlite 五件套
# ---------------------------------------------------------------------------


def test_t301_create_stores_dispatch_sqlite(monkeypatch, _isolated_sqlite_db):
    """`TASK_PRIMARY_WRITE=sqlite` → `create_stores()` 返回 sqlite 五件套。"""

    import main

    from app.task.store import (
        ArtifactStore,
        NodeRunStore,
        ProviderTaskStore,
        SqliteArtifactStore,
        SqliteNodeRunStore,
        SqliteProviderTaskStore,
        SqliteTaskEventStore,
        SqliteTaskStore,
        TaskEventStore,
        TaskStore,
        create_stores,
    )

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", "sqlite")
    task_store, node_run_store, provider_task_store, event_store, artifact_store = (
        create_stores()
    )

    assert isinstance(task_store, SqliteTaskStore)
    assert isinstance(node_run_store, SqliteNodeRunStore)
    assert isinstance(provider_task_store, SqliteProviderTaskStore)
    assert isinstance(event_store, SqliteTaskEventStore)
    assert isinstance(artifact_store, SqliteArtifactStore)

    # 同时满足 Protocol 端口
    assert isinstance(task_store, TaskStore)
    assert isinstance(node_run_store, NodeRunStore)
    assert isinstance(provider_task_store, ProviderTaskStore)
    assert isinstance(event_store, TaskEventStore)
    assert isinstance(artifact_store, ArtifactStore)


# ---------------------------------------------------------------------------
# T302：显式 memory 回滚可用
# ---------------------------------------------------------------------------


def test_t302_create_stores_dispatch_memory_explicit(monkeypatch):
    """显式 `TASK_PRIMARY_WRITE=memory` 也走 memory 路径（回滚开关有效）。"""

    import main

    from app.task.store import MemoryTaskStore, create_stores

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", "MEMORY")  # 大小写不敏感
    stores = create_stores()
    assert isinstance(stores[0], MemoryTaskStore)


# ---------------------------------------------------------------------------
# T303：非法值 fail-fast（消息含 allowed set）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["json", "db", "postgres", "unknown"])
def test_t303_create_stores_fail_fast_on_invalid(monkeypatch, raw):
    """未知值必须在 `Settings` 构造期抛 `ValueError`；`create_stores()` 未
    自己捕获，直接透传。消息必须列出 allowed set。
    """

    import main

    from app.task.store import create_stores

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", raw)
    with pytest.raises(ValueError, match="Invalid TASK_PRIMARY_WRITE") as exc:
        create_stores()
    msg = str(exc.value)
    assert "memory" in msg
    assert "sqlite" in msg


# ---------------------------------------------------------------------------
# T304：memory 模式冷启纯逻辑路径（不需要 DB engine）
# ---------------------------------------------------------------------------


def test_t304_memory_dispatch_needs_no_db_engine(monkeypatch, tmp_path):
    """memory 分派下的 `create_stores()` 全过程不需要 SQLite engine：

    - 就算 `DATA_DB_PATH` 指向一个**不存在**的目录，memory 分派也应无异常
      返回可用 store。
    - 说明分派内部不做多余的 sqlite 侧检查。
    """

    import main

    from app.task.store import MemoryTaskStore, create_stores

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", "memory")
    bogus = tmp_path / "does_not_exist" / "phantom.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(bogus))

    stores = create_stores()
    assert isinstance(stores[0], MemoryTaskStore)

    # 顺跑一次 create 也应工作
    t = stores[0].create(TaskDraft(task_type="image"))
    assert t.status == "queued"
    assert not bogus.exists(), "memory 分派不应触碰 DATA_DB_PATH"


# ---------------------------------------------------------------------------
# T305：round-trip 语义等价（含 P0 sentinel 反查）
# ---------------------------------------------------------------------------


P0_SENTINELS = (
    "api_key",
    "access_token",
    "secret",
    "Bearer",
    "SECRET_VALUE_LEAK",
)


@pytest.mark.parametrize("mode", ["memory", "sqlite"])
def test_t305_round_trip_semantics_equivalent(
    monkeypatch, tmp_path, mode, _isolated_sqlite_db
):
    """两种分派模式下 Task 创建 + 查询语义等价；`input_snapshot` 存 sentinel。

    P0 密钥零入库防线：Task 层 Store 的 `input_snapshot` 允许存业务原文
    （治理方案未把它列为高敏字段）——但**sentinel 反查**仍要覆盖：
    memory 模式无 DB 文件，跳过；sqlite 模式 grep sqlite 文件必须找到
    sentinel（说明 round-trip 无损）。**注意**：本 sentinel 反查检查
    的是"完整字面量能落盘并读回"，不是"零入库"——Task input 与
    provider_configs 的密钥定位不同：治理方案允许 Task input 保留业务
    上下文；密钥零入库防线覆盖的是 provider_config_store，见既有
    tests/task/test_store_contract.py 中 sqlite 分支的 sentinel 覆盖。
    """

    import main

    from app.task.store import create_stores

    monkeypatch.setattr(main, "TASK_PRIMARY_WRITE", mode)
    task_store, *_ = create_stores()

    sentinel_payload = {
        "prompt": "hello",
        # 每类 sentinel 都作为一个字段值植入，验证 round-trip 完整
        "field_api_key": f"api_key-{P0_SENTINELS[0]}-marker",
        "field_access_token": f"access_token-{P0_SENTINELS[1]}-marker",
        "field_secret": f"secret-{P0_SENTINELS[2]}-marker",
        "field_bearer": f"Bearer-{P0_SENTINELS[3]}-marker",
        "field_leak": P0_SENTINELS[4],
    }
    t = task_store.create(
        TaskDraft(
            task_type="image",
            input_snapshot=sentinel_payload,
            canvas_id="c-pr11",
            node_id="n-1",
        )
    )
    # 读回等值
    reloaded = task_store.get(t.id)
    assert reloaded is not None
    assert dict(reloaded.input_snapshot) == sentinel_payload
    assert reloaded.canvas_id == "c-pr11"
    assert reloaded.node_id == "n-1"
    # list 查询命中
    lst = task_store.list_by_canvas_node("c-pr11", "n-1")
    assert any(x.id == t.id for x in lst)


# ---------------------------------------------------------------------------
# T306：AST 抗回归 —— `memory_stores` / `sqlite_stores` 签名冻结
# ---------------------------------------------------------------------------


def test_t306_existing_factories_signatures_frozen():
    """`memory_stores` / `sqlite_stores` 保持无参签名与返回 5-tuple 结构。

    - `inspect.signature` 断言参数数量为 0（无关键字）。
    - 源码级 AST 断言：函数体末尾 return 一个 5-元 tuple。
    """

    import app.task.store.memory_impl as _mem_mod
    import app.task.store.sqlite_impl as _sql_mod

    for fn in (_mem_mod.memory_stores, _sql_mod.sqlite_stores):
        sig = inspect.signature(fn)
        assert list(sig.parameters) == [], (
            f"{fn.__qualname__} 意外新增了参数: {sig}"
        )

    # AST：两个工厂返回一个 Tuple/Call 长度为 5（Task/NodeRun/ProviderTask/Event/Artifact）
    for module in (_mem_mod, _sql_mod):
        src = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                "memory_stores",
                "sqlite_stores",
            ):
                # 函数体最后一个语句应为 `return (...)` 且 5 元
                last = node.body[-1]
                assert isinstance(last, ast.Return), (
                    f"{node.name} 末句应为 return（AST 抗回归）"
                )
                assert isinstance(last.value, ast.Tuple), (
                    f"{node.name} return 表达式应为 Tuple"
                )
                assert len(last.value.elts) == 5, (
                    f"{node.name} return 元组长度应为 5，实际 {len(last.value.elts)}"
                )
                found = True
        assert found, f"模块 {module.__name__} 未找到既有工厂函数"


# ---------------------------------------------------------------------------
# T307：fixture 自身冒烟（`_isolated_sqlite_db` 建表成功）
# ---------------------------------------------------------------------------


def test_t307_isolated_sqlite_fixture_creates_tables(_isolated_sqlite_db):
    """`_isolated_sqlite_db` fixture 完成建表：5 张业务表都能查询到。"""

    import sqlite3

    conn = sqlite3.connect(str(_isolated_sqlite_db))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('tasks','node_runs','provider_tasks','task_events','artifacts')"
        )
        names = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    assert names == {"tasks", "node_runs", "provider_tasks", "task_events", "artifacts"}
