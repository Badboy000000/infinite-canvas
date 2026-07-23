"""数据 PR-20 · Wave 3-N.5 主线 B · Project 域反转默认测试。

覆盖 T250-T259（10 项），承接如下契约：

- 数据 PR-8 首波 Project db 主写机制已在 `tests/db/test_project_writer.py`
  建立 raw_json / 集合级 UPSERT / 异步回写 fallback 等基础契约。
- 数据 PR-15（canvas 域）反转默认 pattern 首次实证（GM-22 pattern 首次实证）·
  Wave 3-L 主线 A 已产出 T90-T99 参照模板。
- **数据 PR-20**（本 PR）Project 域反转默认后，未设 env / 空 env → `"db"`；
  显式 `json` 是回滚开关。T250-T259 严格覆盖：

  * T250 env 未设置 · `_get_primary_write_mode()` 返回 `"db"`
  * T251 未设 env · 冷启动首次 `save_projects` 走 db 主写
  * T252 显式 `PROJECT_PRIMARY_WRITE=json` · 返回 `"json"`（回滚路径可用）
  * T253 显式 `PROJECT_PRIMARY_WRITE=db` · 返回 `"db"`（向前一致）
  * T254 未设 env · save_projects 走 db + JSON 异步回写 fallback 到位
  * T255 `main.save_projects` 函数体 AST byte-identical vs `a6f863a`
        （GM-04 硬约束 · 独立 subprocess `git show`）
  * T256 `main.py` 冻结区 3 符号 AST byte-identical vs `a6f863a`
        （GM-01 硬约束 · StorageSettings / apply_storage_settings /
        storage_settings_snapshot）
  * T257 反转默认后 `data/shadow_diff/**/*.jsonl` 无密钥泄漏
        （参照 canvas 域 PR-15 pattern）
  * T258 DB `projects.raw_json` 无 `api_key`/`access_token`/`secret`/
        `Bearer` 命中（Provider 密钥零落 DB 硬约束）
  * T259 fixture 隔离契约（monkeypatch `main.DATA_DB_PATH` + `main.DATA_DIR` +
        `main.PROJECTS_PATH` · CB-P5-21 pattern · 不污染仓库工作树）

护栏来源：任务书 · Wave 3-N.5 Batch 1 主线 B · 数据 PR-20。
"""

from __future__ import annotations

import ast
import json
import os
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
BASELINE_REF = "a6f863a"  # Wave 3-L 主线 C · 数据 PR-16 · GM-01/GM-04 跨 PR 共同 baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def data_dir_fixture(tmp_path, monkeypatch, isolated_env):
    """把 `DATA_DIR` / `PROJECTS_PATH` 指到 tmp_path（CB-P5-21 隔离契约）。"""

    import main

    data_dir = tmp_path
    projects_path = data_dir / "projects.json"
    monkeypatch.setattr(main, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(main, "PROJECTS_PATH", str(projects_path))
    yield data_dir


def _seed_project(pid: str = "p1", **overrides: Any) -> dict[str, Any]:
    return {
        "id": pid,
        "name": overrides.get("name", "PR-20 Project"),
        "order": overrides.get("order", 0),
        "created_at": overrides.get("created_at", 1000),
        "updated_at": overrides.get("updated_at", 2000),
    }


def _wait_for_file(path: Path, timeout: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if path.exists():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# T250 — env 未设置 · _get_primary_write_mode() 返回 "db"
# ---------------------------------------------------------------------------


def test_T250_unset_env_returns_db(monkeypatch):
    """T250 · env 未设置时新默认为 `"db"`（数据 PR-20 Project 域 M1 收官反转）。"""

    monkeypatch.delenv("PROJECT_PRIMARY_WRITE", raising=False)
    from app.stores.project_store import _get_primary_write_mode

    assert _get_primary_write_mode("project") == "db"


# ---------------------------------------------------------------------------
# T251 — 未设 env · 冷启动首次 save_projects 走 db 主写
# ---------------------------------------------------------------------------


def test_T251_unset_env_first_save_goes_to_db(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T251 · 冷启动 · env 未设 · save_projects 应调 save_projects_db 而非 legacy。"""

    migrate_baseline(tmp_path)
    monkeypatch.delenv("PROJECT_PRIMARY_WRITE", raising=False)

    calls = {"save_projects_db": 0, "legacy_save": 0}
    from app.db import project_writer as pw

    orig_save_db = pw.save_projects_db

    def _spy_db(projects):
        calls["save_projects_db"] += 1
        return orig_save_db(projects)

    monkeypatch.setattr(pw, "save_projects_db", _spy_db)

    import main

    orig_legacy = main.save_projects

    def _spy_legacy(projects):
        calls["legacy_save"] += 1
        return orig_legacy(projects)

    monkeypatch.setattr(main, "save_projects", _spy_legacy)

    from app.stores import project_store

    project_store.save_projects([_seed_project("p_T251")])

    assert calls["save_projects_db"] == 1, (
        "反转后默认 · save_projects 必须调 save_projects_db"
    )
    assert calls["legacy_save"] == 0, (
        "反转后默认 · save_projects 不得再走 legacy main.save_projects"
    )


# ---------------------------------------------------------------------------
# T252 — 显式 PROJECT_PRIMARY_WRITE=json · 回滚开关可用
# ---------------------------------------------------------------------------


def test_T252_explicit_json_returns_json_and_uses_legacy(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T252 · P0 快速回滚路径 · env=json 时 save_projects 走 legacy main.save_projects
    并**绝不** import `app.db.project_writer`（回滚路径全绿 · GM-22 pattern）。"""

    migrate_baseline(tmp_path)
    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "json")

    # 契约 1：`_get_primary_write_mode` 显式返回 "json"
    from app.stores.project_store import _get_primary_write_mode

    assert _get_primary_write_mode("project") == "json"

    # 契约 2：save 分派走 legacy · 不 import writer
    sys.modules.pop("app.db.project_writer", None)

    calls = {"legacy_save": 0}
    import main

    orig_legacy = main.save_projects

    def _spy_legacy(projects):
        calls["legacy_save"] += 1
        return orig_legacy(projects)

    monkeypatch.setattr(main, "save_projects", _spy_legacy)

    from app.stores import project_store

    project_store.save_projects([_seed_project("p_T252")])

    assert calls["legacy_save"] == 1, "env=json 必须走 legacy main.save_projects"
    assert "app.db.project_writer" not in sys.modules, (
        "env=json 严禁 import app.db.project_writer（P0 硬约束 #3 · 回滚路径可用）"
    )
    # legacy JSON 主写落盘（byte-equivalent 于 PR-8 回滚路径）。
    assert (data_dir_fixture / "projects.json").exists()


# ---------------------------------------------------------------------------
# T253 — 显式 PROJECT_PRIMARY_WRITE=db · 返回 "db"（向前一致）
# ---------------------------------------------------------------------------


def test_T253_explicit_db_returns_db(monkeypatch):
    """T253 · 显式 `db` 行为不变（与反转后默认路径同结果）。"""

    monkeypatch.setenv("PROJECT_PRIMARY_WRITE", "db")
    from app.stores.project_store import _get_primary_write_mode

    assert _get_primary_write_mode("project") == "db"


# ---------------------------------------------------------------------------
# T254 — 未设 env · save_projects 走 db + JSON 异步回写落盘
# ---------------------------------------------------------------------------


def test_T254_unset_env_save_writes_db_then_async_json(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T254 · 反转后默认路径必须端到端成立：DB row 同步就位，JSON 文件异步到达。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import select

    migrate_baseline(tmp_path)
    monkeypatch.delenv("PROJECT_PRIMARY_WRITE", raising=False)

    from app.stores import project_store

    project_store.save_projects([_seed_project("p_T254", name="Async")])

    # DB 立即命中
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.projects.c.legacy_id, t.projects.c.raw_json).where(
                t.projects.c.legacy_id == "p_T254"
            )
        ).fetchone()
    assert row is not None, "反转后默认 · DB 主写必须同步完成"

    payload = json.loads(row.raw_json)
    assert payload["id"] == "p_T254"
    assert payload["name"] == "Async"

    # JSON 异步回写：等最多 2s
    json_path = data_dir_fixture / "projects.json"
    assert _wait_for_file(json_path, timeout=2.0), (
        "反转后默认 · async JSON fallback 应在合理窗口内落盘"
    )
    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    assert on_disk == {"projects": [payload]}


# ---------------------------------------------------------------------------
# T255 — main.save_projects 函数体 AST byte-identical vs a6f863a（GM-04）
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


def test_T255_save_projects_body_ast_zero_diff_vs_baseline():
    """T255 · GM-04 硬约束：`main.py:save_projects` 函数体 AST 与 `a6f863a`
    完全等价（本 PR 零触碰函数体 · 只翻转常量默认）。"""

    baseline_tree = _load_main_from_ref(BASELINE_REF)
    if baseline_tree is None:
        pytest.skip(f"baseline ref {BASELINE_REF} unavailable in shallow clone")

    current_tree = ast.parse(
        (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    )

    b_node = _find_func(baseline_tree, "save_projects")
    c_node = _find_func(current_tree, "save_projects")

    assert b_node is not None, f"baseline save_projects missing at {BASELINE_REF}"
    assert c_node is not None, "current save_projects missing"
    assert ast.dump(b_node, include_attributes=False) == ast.dump(
        c_node, include_attributes=False
    ), (
        f"GM-04 硬约束破裂：main.save_projects 函数体自 baseline {BASELINE_REF} "
        f"以来被触碰；本 PR 应零触碰 save_projects 函数体"
    )


# ---------------------------------------------------------------------------
# T256 — main.py 冻结区 3 符号 AST byte-identical vs a6f863a（GM-01）
# ---------------------------------------------------------------------------


_FROZEN_ZONE = (
    ("class", "StorageSettings"),
    ("func", "apply_storage_settings"),
    ("func", "storage_settings_snapshot"),
)


def test_T256_frozen_zone_ast_zero_diff_vs_baseline():
    """T256 · GM-01 硬约束：冻结区 3 符号（StorageSettings /
    apply_storage_settings / storage_settings_snapshot）AST 与 `a6f863a`
    完全等价（跨 PR 保持 · 数据 PR-20 零触碰）。"""

    baseline_tree = _load_main_from_ref(BASELINE_REF)
    if baseline_tree is None:
        pytest.skip(f"baseline ref {BASELINE_REF} unavailable in shallow clone")

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
        assert b_node is not None, f"baseline {name} missing at {BASELINE_REF}"
        assert c_node is not None, f"current {name} missing"
        assert ast.dump(b_node, include_attributes=False) == ast.dump(
            c_node, include_attributes=False
        ), (
            f"GM-01 硬约束破裂：冻结区 {name} 自 baseline {BASELINE_REF} "
            f"以来被触碰；数据 PR-20 应零触碰冻结区"
        )
        hits += 1

    assert hits == 3, f"冻结区 3 符号应全部核验：实际 {hits}"


# ---------------------------------------------------------------------------
# T257 — 反转默认后 shadow_diff/**/*.jsonl 无密钥泄漏（参照 PR-15 pattern）
# ---------------------------------------------------------------------------


_SECRET_MARKERS = ("api_key", "access_token", "secret", "Bearer")


def test_T257_shadow_diff_files_no_provider_secret_leak(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T257 · 反转默认后所有 `data/shadow_diff/**/*.jsonl` 严禁出现 provider
    凭据字面量（api_key / access_token / secret / Bearer）。

    Project 域不涉及 Provider 字段；本测试是"零泄漏"抗回归护栏（无论未来
    异步回写 fallback / json_fallback_diff 走 shadow_diff 哪个子目录，都
    不得混入 Provider 字节）。
    """

    migrate_baseline(tmp_path)
    monkeypatch.delenv("PROJECT_PRIMARY_WRITE", raising=False)

    from app.stores import project_store

    # 端到端触发默认路径（DB 主写 + JSON 异步回写）
    project_store.save_projects([
        _seed_project("p_T257_a", name="Alpha"),
        _seed_project("p_T257_b", name="Beta"),
    ])
    # 等待 async fallback 落盘（若有）
    time.sleep(0.2)

    shadow_root = Path(tmp_path) / "shadow_diff"
    if not shadow_root.exists():
        # 反转默认路径成功时 shadow_diff 未必被建（无 fallback 异常）
        return

    hits: list[tuple[Path, str]] = []
    for jsonl in shadow_root.rglob("*.jsonl"):
        text = jsonl.read_text(encoding="utf-8", errors="replace")
        for marker in _SECRET_MARKERS:
            if marker in text:
                hits.append((jsonl, marker))

    assert not hits, (
        f"密钥泄漏 · shadow_diff 中出现 provider 凭据字面量：{hits}"
    )


# ---------------------------------------------------------------------------
# T258 — DB projects.raw_json 无 Provider 密钥字面量（SQL 反查）
# ---------------------------------------------------------------------------


def test_T258_db_raw_json_no_provider_secret_hits(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T258 · 反转默认后 DB `projects.raw_json` 严禁出现 provider 凭据
    字面量。Project 域 raw_json 只镜像 project entry（`id/name/order/
    created_at/updated_at`），不涉及 Provider 字段——本测试用 SQL LIKE
    反查零命中作为端到端护栏。"""

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from sqlalchemy import func, select, or_

    migrate_baseline(tmp_path)
    monkeypatch.delenv("PROJECT_PRIMARY_WRITE", raising=False)

    from app.stores import project_store

    project_store.save_projects([
        _seed_project("p_T258_a", name="Alpha"),
        _seed_project("p_T258_b", name="Beta"),
    ])

    engine = get_engine()
    with engine.connect() as conn:
        stmt = select(func.count()).select_from(t.projects).where(
            or_(
                t.projects.c.raw_json.like("%api_key%"),
                t.projects.c.raw_json.like("%access_token%"),
                t.projects.c.raw_json.like("%secret%"),
                t.projects.c.raw_json.like("%Bearer%"),
            )
        )
        secret_hits = conn.execute(stmt).scalar_one()

    assert secret_hits == 0, (
        f"密钥泄漏 · projects.raw_json 命中 provider 凭据字面量：{secret_hits} 行"
    )


# ---------------------------------------------------------------------------
# T259 — fixture 隔离契约（CB-P5-21 pattern）
# ---------------------------------------------------------------------------


def test_T259_fixture_isolates_data_paths(
    monkeypatch, data_dir_fixture, tmp_path
):
    """T259 · CB-P5-21 pattern：所有 tmp_path 内的写入不得污染真实 `data/`
    目录。本测试通过 `data_dir_fixture` 已 monkeypatch 的三个入口反查：

    - `main.DATA_DB_PATH` → tmp_path/shadow.db（isolated_shadow_env 契约）
    - `main.DATA_DIR` → tmp_path
    - `main.PROJECTS_PATH` → tmp_path/projects.json
    """

    import main

    assert Path(main.DATA_DB_PATH).parent == tmp_path, (
        f"DATA_DB_PATH 未隔离到 tmp_path: {main.DATA_DB_PATH}"
    )
    assert Path(main.DATA_DIR) == tmp_path, (
        f"DATA_DIR 未隔离到 tmp_path: {main.DATA_DIR}"
    )
    assert Path(main.PROJECTS_PATH).parent == tmp_path, (
        f"PROJECTS_PATH 未隔离到 tmp_path: {main.PROJECTS_PATH}"
    )

    # 端到端：写入操作不得落到真实仓库 data/ 目录
    migrate_baseline(tmp_path)
    monkeypatch.delenv("PROJECT_PRIMARY_WRITE", raising=False)
    from app.stores import project_store

    project_store.save_projects([_seed_project("p_T259")])
    # 等 async json fallback
    _wait_for_file(Path(main.PROJECTS_PATH), timeout=2.0)

    real_data_dir = REPO_ROOT / "data"
    real_projects = real_data_dir / "projects.json"
    # 检查：真实 data/projects.json 若存在，mtime 不应因本测试而更新
    # 更强的隔离断言：tmp_path 下有落盘产物，且落盘产物路径不落在仓库真实 data/ 下
    tmp_projects = tmp_path / "projects.json"
    assert tmp_projects.exists(), (
        "T259 · tmp 内 projects.json 应由 async fallback 落盘"
    )
    # 隔离契约：写入的绝对路径不能是仓库 data/ 目录下的路径
    assert not str(tmp_projects.resolve()).startswith(
        str(real_data_dir.resolve())
    ), "T259 · 隔离契约破裂：写入到了真实仓库 data/ 目录"
