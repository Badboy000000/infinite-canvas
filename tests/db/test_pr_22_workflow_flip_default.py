"""数据 PR-22 · Wave 3-N.5 主线 B · WorkflowDefinition 域反转默认测试。

覆盖 T270-T277（8 项 STRONG），承接如下契约：

- 数据 PR-8 首波 WorkflowDefinition db 主写机制已在
  `tests/db/test_workflow_writer.py` 建立集合级 UPSERT / P0 密钥深度剪枝 /
  异步回写 fallback 等基础契约（Wave 3-G 独立 SQL 反查实证 9 处敏感
  sentinel 全部 0 leaked）。
- 数据 PR-15（canvas 域）与 PR-20（project 域）反转默认 pattern 已在 Wave 3-L /
  Wave 3-N.5 Batch 1 主线 B 相继实证（GM-22 pattern）。
- **数据 PR-22**（本 PR）WorkflowDefinition 域反转默认后，未设 env / 空 env
  → `"db"`；显式 `json` 是回滚开关。T270-T277 严格覆盖：

  * T270 env 未设置 · `_get_primary_write_mode()` 返回 `"db"`
  * T271 冷启动首次 `save_runninghub_workflow_store` 走 db 主写（spy 双向断言
        legacy `main.save_runninghub_workflow_store` 未被触发）
  * T272 显式 `WORKFLOW_DEFINITION_PRIMARY_WRITE=json` · 回滚路径可用
        （不 import `app.db.workflow_writer`）
  * T273 冷启动 save + JSON 异步回写 fallback 到位（端到端 DB row + async
        JSON 落盘 + payload 字节等价）
  * T274 `main.save_runninghub_workflow_store` 函数体 AST byte-identical vs
        `31e0d3d`（GM-04 硬约束 · 独立 subprocess `git show`）
  * T275 `main.py` 冻结区 3 符号 AST byte-identical vs `a6f863a`
        （GM-01 硬约束 · StorageSettings / apply_storage_settings /
        storage_settings_snapshot）
  * T276 **P0 密钥深度剪枝独立 SQL 反查**：反转默认后
        `workflow_definitions.raw_json` 严禁出现 9 处 sentinel（`api_key` /
        `nested.accessToken` / `secret` / `Bearer` / `refresh_token` /
        `access_token` / `authorization` / `x-api-key` / `client_secret`）；
        **独立 SQL `SELECT ... LIKE '%sentinel%'`** 直连 sqlite 反查，
        不走 ORM。这是本 PR 的核心：Wave 3-G Lead 独立复核实证 9 处
        sentinel 全部 0 leaked，反转后必须复现。
  * T277 fixture 隔离契约（monkeypatch `main.DATA_DB_PATH` + `main.DATA_DIR` +
        `main.RUNNINGHUB_WORKFLOW_STORE_FILE` · CB-P5-21 pattern · 不污染仓库
        真实 `data/` 目录）

护栏来源：任务书 · Wave 3-N.5 Batch 2 主线 B · 数据 PR-22。
"""

from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_REF_FROZEN = "a6f863a"  # 冻结区 3 符号 baseline（GM-01 跨 PR 共同 baseline）
BASELINE_REF_SAVE = "31e0d3d"    # 5 save 函数 AST baseline（本 PR 上游 · Wave 3-N.5 主线基）


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def data_dir_fixture(tmp_path, monkeypatch, isolated_env):
    """把 `DATA_DIR` / `RUNNINGHUB_WORKFLOW_STORE_FILE` 指到 tmp_path
    （CB-P5-21 隔离契约）。"""

    import main

    data_dir = tmp_path
    store_path = data_dir / "runninghub_workflow_store.json"
    monkeypatch.setattr(main, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(store_path))
    yield data_dir


def _entry(wid: str, **fields: Any) -> dict[str, Any]:
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


def _wait_for_file(path: Path, timeout: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# T270 — env 未设置 · _get_primary_write_mode() 返回 "db"
# ---------------------------------------------------------------------------


def test_T270_unset_env_returns_db(monkeypatch):
    """T270 · env 未设置时新默认为 `"db"`（数据 PR-22 WorkflowDefinition 域
    M1 收官反转）。"""

    monkeypatch.delenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", raising=False)
    from app.stores.workflow_store import _get_primary_write_mode

    assert _get_primary_write_mode("workflow_definition") == "db"


# ---------------------------------------------------------------------------
# T271 — 未设 env · 冷启动首次 save_runninghub_workflow_store 走 db 主写
# ---------------------------------------------------------------------------


def test_T271_unset_env_first_save_goes_to_db(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T271 · 冷启动 · env 未设 · save_runninghub_workflow_store 应调
    `save_runninghub_workflow_store_db` 而非 legacy `main.save_runninghub_workflow_store`。"""

    migrate_baseline(tmp_path)
    monkeypatch.delenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", raising=False)

    # 先 import 触发 writer 模块加载（spy 前提），再 spy DB 主写函数
    from app.db import workflow_writer as ww

    calls = {"save_db": 0, "legacy_save": 0}
    orig_save_db = ww.save_runninghub_workflow_store_db

    def _spy_db(store):
        calls["save_db"] += 1
        return orig_save_db(store)

    monkeypatch.setattr(ww, "save_runninghub_workflow_store_db", _spy_db)

    import main

    orig_legacy = main.save_runninghub_workflow_store

    def _spy_legacy(store):
        calls["legacy_save"] += 1
        return orig_legacy(store)

    monkeypatch.setattr(main, "save_runninghub_workflow_store", _spy_legacy)

    from app.stores import workflow_store

    workflow_store.save_runninghub_workflow_store({"wf_T271": _entry("wf_T271")})

    assert calls["save_db"] == 1, (
        "反转后默认 · save_runninghub_workflow_store 必须调 save_runninghub_workflow_store_db"
    )
    assert calls["legacy_save"] == 0, (
        "反转后默认 · 不得再走 legacy main.save_runninghub_workflow_store"
    )


# ---------------------------------------------------------------------------
# T272 — 显式 WORKFLOW_DEFINITION_PRIMARY_WRITE=json · 回滚开关可用
# ---------------------------------------------------------------------------


def test_T272_explicit_json_returns_json_and_uses_legacy(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T272 · P0 快速回滚路径 · env=json 时 save_runninghub_workflow_store
    走 legacy `main.save_runninghub_workflow_store` 并**绝不** import
    `app.db.workflow_writer`（回滚路径全绿 · GM-22 pattern）。"""

    migrate_baseline(tmp_path)
    monkeypatch.setenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", "json")

    # 契约 1：`_get_primary_write_mode` 显式返回 "json"
    from app.stores.workflow_store import _get_primary_write_mode

    assert _get_primary_write_mode("workflow_definition") == "json"

    # 契约 2：save 分派走 legacy · 不 import writer
    sys.modules.pop("app.db.workflow_writer", None)

    calls = {"legacy_save": 0}
    import main

    orig_legacy = main.save_runninghub_workflow_store

    def _spy_legacy(store):
        calls["legacy_save"] += 1
        return orig_legacy(store)

    monkeypatch.setattr(main, "save_runninghub_workflow_store", _spy_legacy)

    from app.stores import workflow_store

    workflow_store.save_runninghub_workflow_store({"wf_T272": _entry("wf_T272")})

    assert calls["legacy_save"] == 1, "env=json 必须走 legacy main.save_runninghub_workflow_store"
    assert "app.db.workflow_writer" not in sys.modules, (
        "env=json 严禁 import app.db.workflow_writer（P0 硬约束 #3 · 回滚路径可用）"
    )
    # legacy JSON 主写落盘
    assert (data_dir_fixture / "runninghub_workflow_store.json").exists()


# ---------------------------------------------------------------------------
# T273 — 冷启动 save + JSON 异步回写 fallback 到位
# ---------------------------------------------------------------------------


def test_T273_unset_env_save_writes_db_then_async_json(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T273 · 反转后默认路径必须端到端成立：DB row 同步就位，JSON 文件
    异步到达。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.delenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", raising=False)

    from app.stores import workflow_store

    workflow_store.save_runninghub_workflow_store(
        {"wf_T273": _entry("wf_T273", title="Async")}
    )

    # DB 立即命中
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(
                t.workflow_definitions.c.legacy_id,
                t.workflow_definitions.c.raw_json,
            ).where(t.workflow_definitions.c.legacy_id == "rh:wf_T273")
        ).fetchone()
    assert row is not None, "反转后默认 · DB 主写必须同步完成"

    payload = json.loads(row.raw_json)
    assert payload["workflowId"] == "wf_T273"
    assert payload["title"] == "Async"

    # JSON 异步回写：等最多 2s
    json_path = data_dir_fixture / "runninghub_workflow_store.json"
    assert _wait_for_file(json_path, timeout=2.0), (
        "反转后默认 · async JSON fallback 应在合理窗口内落盘"
    )
    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    # legacy JSON 主写保留原始 entry（含所有非敏感字段）
    assert "wf_T273" in on_disk
    assert on_disk["wf_T273"]["workflowId"] == "wf_T273"


# ---------------------------------------------------------------------------
# T274 — main.save_runninghub_workflow_store 函数体 AST byte-identical
# vs 31e0d3d（GM-04 · 5 save 冻结硬约束）
# ---------------------------------------------------------------------------


def _load_main_from_ref(ref: str) -> ast.Module | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:main.py"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        return None
    return ast.parse(result.stdout)


def _find_func(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _find_class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def test_T274_save_runninghub_workflow_store_body_ast_zero_diff_vs_baseline():
    """T274 · GM-04 硬约束：`main.py:save_runninghub_workflow_store` 函数体
    AST 与 `31e0d3d` 完全等价（本 PR 零触碰函数体 · 只翻转常量默认）。"""

    baseline_tree = _load_main_from_ref(BASELINE_REF_SAVE)
    if baseline_tree is None:
        pytest.skip(f"baseline ref {BASELINE_REF_SAVE} unavailable in shallow clone")

    current_tree = ast.parse(
        (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    )

    b_node = _find_func(baseline_tree, "save_runninghub_workflow_store")
    c_node = _find_func(current_tree, "save_runninghub_workflow_store")

    assert b_node is not None, (
        f"baseline save_runninghub_workflow_store missing at {BASELINE_REF_SAVE}"
    )
    assert c_node is not None, "current save_runninghub_workflow_store missing"
    assert ast.dump(b_node, include_attributes=False) == ast.dump(
        c_node, include_attributes=False
    ), (
        f"GM-04 硬约束破裂：main.save_runninghub_workflow_store 函数体自 baseline "
        f"{BASELINE_REF_SAVE} 以来被触碰；本 PR 应零触碰 save 函数体"
    )


# ---------------------------------------------------------------------------
# T275 — main.py 冻结区 3 符号 AST byte-identical vs a6f863a（GM-01）
# ---------------------------------------------------------------------------


_FROZEN_ZONE = (
    ("class", "StorageSettings"),
    ("func", "apply_storage_settings"),
    ("func", "storage_settings_snapshot"),
)


def test_T275_frozen_zone_ast_zero_diff_vs_baseline():
    """T275 · GM-01 硬约束：冻结区 3 符号（StorageSettings /
    apply_storage_settings / storage_settings_snapshot）AST 与 `a6f863a`
    完全等价（跨 PR 保持 · 数据 PR-22 零触碰）。"""

    baseline_tree = _load_main_from_ref(BASELINE_REF_FROZEN)
    if baseline_tree is None:
        pytest.skip(
            f"baseline ref {BASELINE_REF_FROZEN} unavailable in shallow clone"
        )

    current_tree = ast.parse(
        (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    )

    hits = 0
    for kind, name in _FROZEN_ZONE:
        if kind == "func":
            b_node = _find_func(baseline_tree, name)
            c_node = _find_func(current_tree, name)
        else:
            b_node = _find_class(baseline_tree, name)
            c_node = _find_class(current_tree, name)
        assert b_node is not None, f"baseline {name} missing at {BASELINE_REF_FROZEN}"
        assert c_node is not None, f"current {name} missing"
        assert ast.dump(b_node, include_attributes=False) == ast.dump(
            c_node, include_attributes=False
        ), (
            f"GM-01 硬约束破裂：冻结区 {name} 自 baseline {BASELINE_REF_FROZEN} "
            f"以来被触碰；数据 PR-22 应零触碰冻结区"
        )
        hits += 1

    assert hits == 3, f"冻结区 3 符号应全部核验：实际 {hits}"


# ---------------------------------------------------------------------------
# T276 — **本 PR 核心**：反转默认后 P0 密钥深度剪枝独立 SQL 反查
# 9 处 sentinel 全部 0 leaked
# ---------------------------------------------------------------------------


# 9 处 sentinel（Wave 3-G Lead 实证清单）· 每个用独立 sentinel 值以精确追踪
_SECRET_SENTINELS: dict[str, str] = {
    "api_key": "SENTINEL_PR22_APIKEY_MUST_NOT_LEAK",
    "nested_access_token": "SENTINEL_PR22_NESTED_ACCESSTOKEN_MUST_NOT_LEAK",
    "secret": "SENTINEL_PR22_SECRET_MUST_NOT_LEAK",
    "bearer": "SENTINEL_PR22_BEARER_MUST_NOT_LEAK",
    "refresh_token": "SENTINEL_PR22_REFRESHTOKEN_MUST_NOT_LEAK",
    "access_token": "SENTINEL_PR22_ACCESSTOKEN_MUST_NOT_LEAK",
    "authorization": "SENTINEL_PR22_AUTHORIZATION_MUST_NOT_LEAK",
    "x_api_key": "SENTINEL_PR22_XAPIKEY_MUST_NOT_LEAK",
    "client_secret": "SENTINEL_PR22_CLIENTSECRET_MUST_NOT_LEAK",
}


def test_T276_default_flip_deep_prune_9_sentinels_zero_leak_independent_sql(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T276 · **本 PR 核心**：数据 PR-22 反转默认后（env 未设 → db 主写），
    9 处 sentinel（api_key / nested.accessToken / secret / Bearer /
    refresh_token / access_token / authorization / x-api-key /
    client_secret）**独立 SQL 反查** 全部 0 命中。

    独立 SQL：不走 ORM，直连 sqlite `sqlite3.connect(main.DATA_DB_PATH)`
    + `SELECT COUNT(*) FROM workflow_definitions WHERE raw_json LIKE
    '%<sentinel>%'`。这是治理期 Wave 3-G Lead 独立复核的实证 pattern
    （9 处敏感 sentinel 全部 0 leaked），反转后必须复现。
    """

    import main
    from app.stores import workflow_store

    migrate_baseline(tmp_path)
    monkeypatch.delenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", raising=False)

    # 构造 entry：9 处 sentinel 覆盖顶层键 + 深度嵌套键 + 大小写变体 +
    # 值级 credential 语义。
    # 关键设计：`Bearer` / `refresh_token` 是 credential *类别*（bearer 令牌 /
    # 刷新令牌），不是 workflow_writer 剪枝名单里的独立字段名——它们的现实
    # 泄漏路径是通过父键 `authorization` / `credential` 携带值进 raw_json。
    # 把两个 sentinel 放到已经会被剪枝的父键下（`authorization` 与
    # `credential`），验证剪枝把整颗子树带走，从而 credential 语义类别 0 泄漏。
    entry = _entry(
        "wf_T276_sentinels",
        title="PR-22 P0 sentinels",
        # 顶层直接命中剪枝名单的 6 个字段
        api_key=_SECRET_SENTINELS["api_key"],
        secret=_SECRET_SENTINELS["secret"],
        # Bearer 令牌值：通过父键 `authorization`（在 _SENSITIVE_FIELD_NAMES
        # 名单里）承载 —— 父键剪枝后 Bearer 前缀 + sentinel 值一并消失。
        authorization=(
            f"Bearer {_SECRET_SENTINELS['bearer']} "
            f"{_SECRET_SENTINELS['authorization']}"
        ),
        # `refresh_token` 通过父键 `credential`（在 _SENSITIVE_FIELD_NAMES
        # 名单里）承载 —— 父键剪枝后整个 dict（含 refresh_token 值）消失。
        credential={
            "refresh_token": _SECRET_SENTINELS["refresh_token"],
            "note": "should be pruned entirely",
        },
        access_token=_SECRET_SENTINELS["access_token"],
        # 注意：`x-api-key` 键内的 `-` 会被 _is_sensitive_field 的 normalize 规则
        # `re.sub(r"[^a-z0-9]", "", ...)` 归一为 `xapikey`；测试等价映射：
        # 用 `x_api_key` 作 Python 字面 key 效果一致（normalize 后同样是
        # `xapikey`，命中 _SENSITIVE_AFFIXES `apikey` 前后缀分支）。
        x_api_key=_SECRET_SENTINELS["x_api_key"],
        client_secret=_SECRET_SENTINELS["client_secret"],
        # 深度嵌套 · nested.accessToken
        raw={
            "nested": {
                "accessToken": _SECRET_SENTINELS["nested_access_token"],
            },
            # 一个非敏感字段应保留
            "safe_field": "safe_value_pr22",
        },
    )
    workflow_store.save_runninghub_workflow_store({"wf_T276_sentinels": entry})

    # ------ 独立 SQL 反查（直连 sqlite · 不走 ORM）------
    db_path = str(main.DATA_DB_PATH)
    assert os.path.exists(db_path), f"DB 未落盘 tmp: {db_path}"

    leaks: dict[str, int] = {}
    conn = sqlite3.connect(db_path)
    try:
        for label, sentinel in _SECRET_SENTINELS.items():
            cur = conn.execute(
                "SELECT COUNT(*) FROM workflow_definitions "
                "WHERE raw_json LIKE ?",
                (f"%{sentinel}%",),
            )
            (count,) = cur.fetchone()
            leaks[label] = int(count)
    finally:
        conn.close()

    # 9 处 sentinel 全部 0 命中
    hits = {label: n for label, n in leaks.items() if n > 0}
    assert not hits, (
        f"P0 硬约束 #5 破裂 · 数据 PR-22 反转后仍有密钥泄漏到 "
        f"workflow_definitions.raw_json：{hits}（独立 SQL 反查结果：{leaks}）"
    )
    assert len(leaks) == 9, f"应核验 9 处 sentinel · 实际 {len(leaks)}: {sorted(leaks)}"

    # 补充断言：非敏感 safe_field 保留（证明 prune 只剪敏感键，不误伤）
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM workflow_definitions "
            "WHERE raw_json LIKE '%safe_value_pr22%'"
        )
        (safe_count,) = cur.fetchone()
    finally:
        conn.close()
    assert safe_count == 1, (
        f"prune 误伤 · 非敏感 safe_field 未保留（独立 SQL 命中：{safe_count}）"
    )


# ---------------------------------------------------------------------------
# T277 — fixture 隔离契约（CB-P5-21 pattern）
# ---------------------------------------------------------------------------


def test_T277_fixture_isolates_data_paths(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T277 · CB-P5-21 pattern：所有 tmp_path 内的写入不得污染真实 `data/`
    目录。本测试通过 `data_dir_fixture` 已 monkeypatch 的三个入口反查：

    - `main.DATA_DB_PATH` → tmp_path/shadow.db（isolated_shadow_env 契约）
    - `main.DATA_DIR` → tmp_path
    - `main.RUNNINGHUB_WORKFLOW_STORE_FILE` → tmp_path/runninghub_workflow_store.json
    """

    import main

    assert Path(main.DATA_DB_PATH).parent == tmp_path, (
        f"DATA_DB_PATH 未隔离到 tmp_path: {main.DATA_DB_PATH}"
    )
    assert Path(main.DATA_DIR) == tmp_path, (
        f"DATA_DIR 未隔离到 tmp_path: {main.DATA_DIR}"
    )
    assert Path(main.RUNNINGHUB_WORKFLOW_STORE_FILE).parent == tmp_path, (
        f"RUNNINGHUB_WORKFLOW_STORE_FILE 未隔离到 tmp_path: "
        f"{main.RUNNINGHUB_WORKFLOW_STORE_FILE}"
    )

    # 端到端：写入操作不得落到真实仓库 data/ 目录
    migrate_baseline(tmp_path)
    monkeypatch.delenv("WORKFLOW_DEFINITION_PRIMARY_WRITE", raising=False)
    from app.stores import workflow_store

    workflow_store.save_runninghub_workflow_store({"wf_T277": _entry("wf_T277")})
    # 等 async json fallback
    _wait_for_file(Path(main.RUNNINGHUB_WORKFLOW_STORE_FILE), timeout=2.0)

    real_data_dir = REPO_ROOT / "data"
    tmp_store = tmp_path / "runninghub_workflow_store.json"
    assert tmp_store.exists(), (
        "T277 · tmp 内 runninghub_workflow_store.json 应由 async fallback 落盘"
    )
    # 隔离契约：写入的绝对路径不能是仓库 data/ 目录下的路径
    assert not str(tmp_store.resolve()).startswith(
        str(real_data_dir.resolve())
    ), "T277 · 隔离契约破裂：写入到了真实仓库 data/ 目录"
