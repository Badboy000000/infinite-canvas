"""数据 PR-8 · WorkflowDefinition 主写机制契约测试（Wave 3-G）。

覆盖点（≥8 项 STRONG 级）：

1. `WORKFLOW_DEFINITION_PRIMARY_WRITE=json`（默认）时不 import
   `app.db.workflow_writer` / 不构造 DB engine / 不落 fallback。
2. `WORKFLOW_DEFINITION_PRIMARY_WRITE=db` 时 DB `workflow_definitions` 表按
   payload 集合级 UPSERT（`provider_id='runninghub'`）。
3. **P0 密钥剪枝**：`workflow_definitions.raw_json` 严禁含 provider 密钥字段
   （`api_key` / `access_token` / `secret` / `authorization` / `password` /
   `client_secret` / `env_file` / ...）——AST + 端到端 dump grep 双验证。
4. 集合级 DELETE 只清 `provider_id='runninghub'` 域，不误伤 builtin `file:*` 行。
5. `db` 模式下 JSON 异步回写落地。
6. fail-fast：`WORKFLOW_DEFINITION_PRIMARY_WRITE="invalid"` 在 Settings 层报错。
7. DB 主写失败必须上抛（不 fallback）。
8. `prune_runninghub_workflow_store_for_provider` 在 `db` 模式下语义等价（rh_workflows
   增删同步）。
9. 大字段 `raw_json` 保留（`workflowJson` 等非敏感大字段完整保留）。
"""

from __future__ import annotations

import ast
import json
import os
import re
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

    store_path = tmp_path / "runninghub_workflow_store.json"
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(store_path))
    yield tmp_path


def _entry(wid: str, **fields) -> dict:
    entry = {
        "workflowId": wid,
        "title": fields.get("title", f"wf-{wid}"),
        "description": fields.get("description", ""),
        "fields": fields.get("fields", []),
        "workflowJson": fields.get("workflowJson", {"nodes": []}),
        "raw": fields.get("raw", {}),
        "updatedAt": fields.get("updatedAt", 1000),
    }
    entry.update({k: v for k, v in fields.items() if k not in entry})
    return entry


# ---------------------------------------------------------------------------
# 1. json 默认模式 sys.modules 隔离契约（P0）
# ---------------------------------------------------------------------------


def test_json_mode_default_does_not_import_workflow_writer(
    monkeypatch, data_dir_fixture, tmp_path
):
    """P0 硬约束 #3：`json` 回滚模式下不 import `app.db.workflow_writer`。

    数据 PR-22（Wave 3-N.5 主线 B）反转默认后：默认已经是 db；本用例语义是
    "显式 json 回滚开关"下不 import writer；因此必须 setenv，不能 delenv。
    """

    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "json")
    sys.modules.pop("app.db.workflow_writer", None)

    from app.stores import workflow_store

    store = {"wf1": _entry("wf1")}
    workflow_store.save_runninghub_workflow_store(store)

    assert "app.db.workflow_writer" not in sys.modules, (
        "P0 硬约束违反：默认模式拉起了 app.db.workflow_writer"
    )
    assert (data_dir_fixture / "runninghub_workflow_store.json").exists()

    fallback_dir = tmp_path / "shadow_diff" / "workflow_definition_json_fallback"
    assert not fallback_dir.exists()


def test_json_mode_default_does_not_build_db_engine(
    monkeypatch, data_dir_fixture, tmp_path
):
    """显式 `json` 回滚模式下不构造 DB engine（P0 硬约束）。

    数据 PR-22 反转默认后：默认已经是 db；本用例语义是"显式 json"下不建 engine。
    """

    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "json")

    from app.db import engine as db_engine

    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when json mode")

    monkeypatch.setattr(db_engine, "get_engine", _fail)

    from app.stores import workflow_store

    workflow_store.save_runninghub_workflow_store({"wf1": _entry("wf1")})
    assert hits["count"] == 0


# ---------------------------------------------------------------------------
# 2. db 模式集合级 UPSERT + DELETE
# ---------------------------------------------------------------------------


def test_db_mode_upserts_workflows_to_db(monkeypatch, data_dir_fixture, tmp_path):
    """`db` 模式下 DB `workflow_definitions` 表按 payload 集合级 UPSERT。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import workflow_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    store = {"wfA": _entry("wfA", title="Alpha"), "wfB": _entry("wfB", title="Beta")}
    workflow_store.save_runninghub_workflow_store(store)

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(
                t.workflow_definitions.c.legacy_id,
                t.workflow_definitions.c.name,
                t.workflow_definitions.c.provider_id,
                t.workflow_definitions.c.kind,
            ).where(t.workflow_definitions.c.provider_id == "runninghub")
            .order_by(t.workflow_definitions.c.legacy_id.asc())
        ).fetchall()

    assert {r.legacy_id for r in rows} == {"rh:wfA", "rh:wfB"}
    assert all(r.provider_id == "runninghub" for r in rows)
    assert all(r.kind == "workflow" for r in rows)
    names = {r.legacy_id: r.name for r in rows}
    assert names["rh:wfA"] == "Alpha"


# ---------------------------------------------------------------------------
# 3. P0 密钥剪枝（AST + 端到端 grep 双验证）
# ---------------------------------------------------------------------------


def test_workflow_writer_ast_contains_secret_pruning():
    """AST 静态验证：workflow_writer 模块含 `_is_sensitive_field` 与 `_prune_secrets`
    符号；`_build_row` 内部调用 `_prune_secrets`（P0 硬约束 #5 AST 检测）。
    """

    from app.db import workflow_writer

    source = Path(workflow_writer.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    func_names: set[str] = set()
    build_row_body_src: str | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            func_names.add(node.name)
            if node.name == "_build_row":
                build_row_body_src = ast.unparse(node)

    assert "_is_sensitive_field" in func_names, "workflow_writer must define _is_sensitive_field"
    assert "_prune_secrets" in func_names, "workflow_writer must define _prune_secrets"
    assert build_row_body_src is not None
    assert "_prune_secrets" in build_row_body_src, (
        "_build_row must call _prune_secrets on cfg payload"
    )


def test_workflow_writer_raw_json_strips_provider_secrets(
    monkeypatch, data_dir_fixture, tmp_path
):
    """端到端 dump grep 双验证：即使 workflow entry 含 `api_key` / `access_token` /
    `secret` / `authorization` / `password` / `client_secret` / `env_file` 等键，
    `workflow_definitions.raw_json` 都不含（P0 硬约束 #5）。
    """

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import workflow_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    secret_marker = "MARKER_MUST_NOT_LEAK_PR8"
    entry = _entry(
        "wf_top_level_priv",
        title="wf with secrets",
        api_key=secret_marker,
        access_token=secret_marker,
        secret=secret_marker,
        authorization=secret_marker,
        password=secret_marker,
        client_secret=secret_marker,
        env_file=secret_marker,
        # 深度嵌套 & 大小写变体
        raw={
            "config": {
                "APIKey": secret_marker,
                "authToken": secret_marker,
                "walletKey": secret_marker,
                "safe_field": "safe_value",
            },
            "provider_secret_access_key": secret_marker,
        },
        # 非敏感大字段（应保留）
        workflowJson={"nodes": [{"id": "n1", "data": "x" * 500}]},
    )
    workflow_store.save_runninghub_workflow_store({"wf_top_level_priv": entry})

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.workflow_definitions.c.raw_json).where(
                t.workflow_definitions.c.legacy_id == "rh:wf_top_level_priv"
            )
        ).fetchone()

    assert row is not None
    raw_json_text = row.raw_json

    # P0：端到端 grep 双验证——密钥字面值不出现
    assert secret_marker not in raw_json_text, (
        f"P0 硬约束 #5 违反：密钥字面值 {secret_marker} 泄露到 workflow_definitions.raw_json"
    )
    # 反序列化后按 key 精确验证（避免与 workflow_id 中的 substring 混淆）
    payload = json.loads(raw_json_text)

    def _walk_keys(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                yield k
                yield from _walk_keys(v)
        elif isinstance(obj, list):
            for item in obj:
                yield from _walk_keys(item)

    from app.db.workflow_writer import _is_sensitive_field

    seen_keys = list(_walk_keys(payload))
    leaked = [k for k in seen_keys if _is_sensitive_field(k)]
    assert not leaked, (
        f"P0 硬约束 #5 违反：以下敏感键泄露到 raw_json: {leaked}"
    )

    # 非敏感字段应保留
    payload = json.loads(raw_json_text)
    assert "workflowJson" in payload
    assert payload["workflowJson"]["nodes"][0]["id"] == "n1"
    assert payload["raw"]["config"]["safe_field"] == "safe_value"


def test_workflow_writer_prune_secrets_helper_unit():
    """`_prune_secrets` 单元验证：递归剪除 dict/list 中的敏感键。"""

    from app.db.workflow_writer import _prune_secrets

    payload = {
        "api_key": "SECRET",
        "safe": "OK",
        "nested": {"password": "SECRET", "kept": "KEPT"},
        "list": [{"secret": "SECRET", "id": "n1"}],
    }
    pruned = _prune_secrets(payload)
    assert "api_key" not in pruned
    assert pruned["safe"] == "OK"
    assert "password" not in pruned["nested"]
    assert pruned["nested"]["kept"] == "KEPT"
    assert "secret" not in pruned["list"][0]
    assert pruned["list"][0]["id"] == "n1"


# ---------------------------------------------------------------------------
# 4. 集合级 DELETE 只清 runninghub 域
# ---------------------------------------------------------------------------


def test_db_mode_delete_only_touches_runninghub_provider(
    monkeypatch, data_dir_fixture, tmp_path
):
    """DB 集合级 DELETE 只清 `provider_id='runninghub'` 域，不误伤其他 provider。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id
    from app.stores import workflow_store
    from sqlalchemy import select
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    import datetime as _dt

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    # 先塞一个 builtin file:xxx 行（模拟 importer 的产物）
    engine = get_engine()
    now = _dt.datetime.now(_dt.timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            sqlite_insert(t.workflow_definitions).values(
                id=generate_id(),
                legacy_id="file:builtin.json",
                name="builtin",
                provider_id=None,
                kind="builtin",
                legacy_path="/tmp/x",
                raw_json="{}",
                schema_version="v1_legacy_json",
                imported_at=now,
                created_at=now,
                updated_at=now,
            )
        )

    # 通过 store facade 写 runninghub 域
    workflow_store.save_runninghub_workflow_store({"wf1": _entry("wf1")})

    # 再写 empty rh payload → 应清空 rh 域，但 builtin 保留
    workflow_store.save_runninghub_workflow_store({})

    with engine.connect() as conn:
        rows = conn.execute(select(t.workflow_definitions.c.legacy_id)).fetchall()

    ids = {r.legacy_id for r in rows}
    assert "file:builtin.json" in ids, "builtin 行被误清除"
    assert not any(x.startswith("rh:") for x in ids), "rh: 行未清空"


# ---------------------------------------------------------------------------
# 5. 异步 JSON 回写
# ---------------------------------------------------------------------------


def test_db_mode_async_json_fallback_writes_file(
    monkeypatch, data_dir_fixture, tmp_path
):
    from app.stores import workflow_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    workflow_store.save_runninghub_workflow_store({"wf1": _entry("wf1")})

    saved_path = data_dir_fixture / "runninghub_workflow_store.json"
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        if saved_path.exists():
            break
        time.sleep(0.02)
    assert saved_path.exists(), "async JSON fallback did not appear"
    payload = json.loads(saved_path.read_text(encoding="utf-8"))
    assert "wf1" in payload


def test_db_mode_json_fallback_failure_does_not_propagate(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`db` 模式下 JSON 回写失败不冒泡；shadow diff 落地（P0 密钥剪枝：diff 只
    落 error/reason，不落内容体）。

    数据 PR-8 承接强化补丁：**端到端**触发 `_async_write_json_fallback →
    _write_json_fallback_sync → _record_json_fallback_failure` 全链路
    （与 canvas C6' 对齐）。通过 monkeypatch `main.RUNNINGHUB_WORKFLOW_STORE_FILE`
    到不存在的父目录让 `open()` 抛 FileNotFoundError，走真实 except 链路。
    """

    from app.stores import workflow_store

    import main

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    monkeypatch.setattr(
        main,
        "RUNNINGHUB_WORKFLOW_STORE_FILE",
        str(tmp_path / "nonexistent_dir" / "runninghub_workflow_store.json"),
    )

    # 主写路径不应抛错
    workflow_store.save_runninghub_workflow_store({"wf1": _entry("wf1")})

    diff_dir = tmp_path / "shadow_diff" / "workflow_definition_json_fallback"
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
    assert rec["domain"] == "workflow_definition"
    assert rec["fallback_reason"] == "json_write_error"
    # P0：diff 不含内容体（只有 error/reason/ts/domain）
    assert set(rec.keys()) == {"ts", "domain", "error", "fallback_reason"}


# ---------------------------------------------------------------------------
# 6. 主写失败上抛
# ---------------------------------------------------------------------------


def test_db_mode_primary_write_error_propagates(
    monkeypatch, data_dir_fixture, tmp_path
):
    from app.stores import workflow_store

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    def _boom_engine(*a, **kw):
        raise RuntimeError("simulated db failure")

    monkeypatch.setattr("app.db.engine.get_engine", _boom_engine)

    with pytest.raises(RuntimeError, match="simulated db failure"):
        workflow_store.save_runninghub_workflow_store({"wf1": _entry("wf1")})


# ---------------------------------------------------------------------------
# 7. prune_runninghub_workflow_store_for_provider 语义等价
# ---------------------------------------------------------------------------


def test_db_mode_prune_for_provider_semantics_equivalent(
    monkeypatch, data_dir_fixture, tmp_path
):
    """`prune_runninghub_workflow_store_for_provider` 在 `db` 模式下语义等价：
    provider `rh_workflows` 减少时，DB 中对应 rh workflow 行同步 DELETE（走 store
    facade 分派，集合级 DELETE 事务自动承接）。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import workflow_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    # 初始状态：DB 有 wfA / wfB / wfC
    workflow_store.save_runninghub_workflow_store(
        {"wfA": _entry("wfA"), "wfB": _entry("wfB"), "wfC": _entry("wfC")}
    )

    # 等待 async JSON 回写完成（prune 会走 load facade，当前 facade `load` 分支
    # 未做 db 优先——由 `main.load_runninghub_workflow_store` 读 JSON；这与老
    # 语义一致，`load` DB 优先属 M2 后续 PR 承接）。
    saved_path = data_dir_fixture / "runninghub_workflow_store.json"
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        if saved_path.exists():
            break
        time.sleep(0.02)
    assert saved_path.exists(), "async JSON fallback did not appear before prune"

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.workflow_definitions.c.legacy_id).where(
                t.workflow_definitions.c.provider_id == "runninghub"
            )
        ).fetchall()
    assert {r.legacy_id for r in rows} == {"rh:wfA", "rh:wfB", "rh:wfC"}

    # 调 main.prune_runninghub_workflow_store_for_provider（走 store facade）
    import main

    provider = {
        "id": "runninghub",
        "rh_workflows": [
            {"workflowId": "wfA", "hidden": False},
            {"workflowId": "wfC", "hidden": False},
        ],
    }
    main.prune_runninghub_workflow_store_for_provider(provider)

    # 结果：wfB 应被移除
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.workflow_definitions.c.legacy_id).where(
                t.workflow_definitions.c.provider_id == "runninghub"
            )
        ).fetchall()
    assert {r.legacy_id for r in rows} == {"rh:wfA", "rh:wfC"}


# ---------------------------------------------------------------------------
# 8. 大字段 raw_json 保留
# ---------------------------------------------------------------------------


def test_db_mode_raw_json_preserves_large_non_sensitive_fields(
    monkeypatch, data_dir_fixture, tmp_path
):
    """rh 大字段 `workflowJson` / `raw` 非敏感字段完整保留。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.stores import workflow_store
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "db")

    big_wfjson = {"nodes": [{"id": f"n{i}", "type": "op", "data": "x" * 64} for i in range(500)]}
    entry = _entry("wf_big", workflowJson=big_wfjson, description="big wf")
    workflow_store.save_runninghub_workflow_store({"wf_big": entry})

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.workflow_definitions.c.raw_json).where(
                t.workflow_definitions.c.legacy_id == "rh:wf_big"
            )
        ).fetchone()

    payload = json.loads(row.raw_json)
    assert len(payload["workflowJson"]["nodes"]) == 500
    assert payload["description"] == "big wf"
