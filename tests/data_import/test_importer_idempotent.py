"""数据 PR-3 · 6 类 domain importer 幂等测试。

对每类 domain 用 `data/` 现有样例（或注入伪数据）执行：

1. `import_domain(...)` → 首次插入 N 条；
2. `reconcile_domain(...)` diff = 0（`missing == []`）；
3. `import_domain(...)` 再次 → `inserted == 0`，同 `legacy_id` 不产生副本；
4. `dry_run=True` 不落库（DB 行数不变）。

所有测试通过 `DATA_DB_PATH=<tmp>` + `run_migrations("head")` 建独立 sqlite。
"""
from __future__ import annotations

import json
import os
import pathlib
from contextlib import contextmanager

import pytest


@contextmanager
def _isolated_db(monkeypatch, tmp_path):
    """把 DB / DATA_DIR / CANVAS_DIR / WORKFLOW_DIR 指向 tmp。"""
    import main
    from app.db import engine as db_engine
    from app.db import session as db_session

    db_path = tmp_path / "pr3_import.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(db_path))

    # Reset engine + sessionmaker so new DATA_DB_PATH is picked up
    db_engine.reset_engine()
    db_session._SessionLocal = None

    db_engine.run_migrations("head")

    try:
        yield db_path
    finally:
        db_engine.reset_engine()
        db_session._SessionLocal = None


def _row_count(db_path, table):
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# project
# ---------------------------------------------------------------------------

def test_project_import_reconcile_idempotent(monkeypatch, tmp_path):
    projects_path = tmp_path / "projects.json"
    projects_path.write_text(json.dumps({
        "projects": [
            {"id": "default", "name": "默认项目", "order": 0, "created_at": 1, "updated_at": 2},
            {"id": "beta", "name": "Beta", "order": 1, "created_at": 3, "updated_at": 4},
        ]
    }, ensure_ascii=False), encoding="utf-8")

    import main
    monkeypatch.setattr(main, "PROJECTS_PATH", str(projects_path))

    with _isolated_db(monkeypatch, tmp_path) as db:
        from app.data_import import import_domain, reconcile_domain

        first = import_domain("project", source_path=str(projects_path))
        assert first.inserted == 2
        assert first.skipped == 0
        assert _row_count(db, "projects") == 2

        report = reconcile_domain("project")
        # reconcile 读的是 store.snapshot() 默认路径。改为按 legacy_id 断言，
        # 我们用 `source_path=None` 走 store → PROJECTS_PATH 也已 monkeypatch。
        assert report.counts["db"] == 2
        assert report.missing == []

        second = import_domain("project", source_path=str(projects_path))
        assert second.inserted == 0
        assert second.skipped == 2
        assert _row_count(db, "projects") == 2


# ---------------------------------------------------------------------------
# provider_config
# ---------------------------------------------------------------------------

def test_provider_config_import_idempotent(monkeypatch, tmp_path):
    providers_path = tmp_path / "api_providers.json"
    providers_path.write_text(json.dumps([
        {"id": "p1", "name": "OpenAI Compat", "protocol": "openai", "base_url": "https://x/v1",
         "enabled": True, "primary": True, "api_key": "sk-EVIL"},
        {"id": "p2", "name": "Local", "protocol": "openai", "enabled": False,
         "authorization": "Bearer LEAK"},
    ], ensure_ascii=False), encoding="utf-8")

    import main
    monkeypatch.setattr(main, "API_PROVIDERS_FILE", str(providers_path))

    with _isolated_db(monkeypatch, tmp_path) as db:
        from app.data_import import import_domain, reconcile_domain

        first = import_domain("provider_config", source_path=str(providers_path))
        assert first.inserted == 2
        assert _row_count(db, "provider_configs") == 2

        report = reconcile_domain("provider_config")
        assert report.counts["db"] == 2
        assert report.missing == []

        second = import_domain("provider_config", source_path=str(providers_path))
        assert second.inserted == 0
        assert second.skipped == 2


# ---------------------------------------------------------------------------
# prompt_library
# ---------------------------------------------------------------------------

def test_prompt_library_import_idempotent(monkeypatch, tmp_path):
    prompts_path = tmp_path / "prompt_libraries.json"
    prompts_path.write_text(json.dumps({
        "libraries": [
            {"id": "default", "name": "默认", "scope": "system", "items": [
                {"id": "p1", "name": "问候", "kind": "text"},
                {"id": "p2", "name": "总结"},
            ]},
        ]
    }, ensure_ascii=False), encoding="utf-8")

    import main
    monkeypatch.setattr(main, "PROMPT_LIBRARY_PATH", str(prompts_path))

    with _isolated_db(monkeypatch, tmp_path) as db:
        from app.data_import import import_domain, reconcile_domain

        first = import_domain("prompt_library", source_path=str(prompts_path))
        assert first.inserted == 3  # 1 library + 2 items
        assert _row_count(db, "prompt_libraries") == 1
        assert _row_count(db, "prompt_items") == 2

        report = reconcile_domain("prompt_library")
        assert report.counts["db"] == 3
        assert report.missing == []

        second = import_domain("prompt_library", source_path=str(prompts_path))
        assert second.inserted == 0


# ---------------------------------------------------------------------------
# workflow_definition
# ---------------------------------------------------------------------------

def test_workflow_definition_import_idempotent(monkeypatch, tmp_path):
    rh_path = tmp_path / "runninghub_workflows.json"
    rh_path.write_text(json.dumps({
        "providers": [
            {"provider_id": "rh1", "workflows": [
                {"id": "w1", "name": "flow-A"},
                {"id": "w2", "name": "flow-B"},
            ], "apps": [
                {"id": "a1", "name": "app-A"},
            ]}
        ]
    }, ensure_ascii=False), encoding="utf-8")

    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "sample.json").write_text('{"nodes": []}', encoding="utf-8")

    import main
    monkeypatch.setattr(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(rh_path))
    monkeypatch.setattr(main, "WORKFLOW_DIR", str(wf_dir))

    with _isolated_db(monkeypatch, tmp_path) as db:
        from app.data_import import import_domain, reconcile_domain

        first = import_domain("workflow_definition", source_path=str(rh_path))
        # 3 RH + 1 builtin = 4
        assert first.inserted == 4
        assert _row_count(db, "workflow_definitions") == 4

        report = reconcile_domain("workflow_definition")
        assert report.counts["db"] == 4
        assert report.missing == []

        second = import_domain("workflow_definition", source_path=str(rh_path))
        assert second.inserted == 0


# ---------------------------------------------------------------------------
# asset_library
# ---------------------------------------------------------------------------

def test_asset_library_import_idempotent(monkeypatch, tmp_path):
    asset_path = tmp_path / "asset_library.json"
    asset_path.write_text(json.dumps({
        "libraries": [
            {"id": "default", "name": "默认", "categories": [
                {"id": "cat-a", "name": "角色", "items": [
                    {"id": "i1", "name": "img1", "url": "/assets/library/1.png"},
                    {"id": "i2", "name": "img2", "url": "/assets/library/2.png"},
                ]},
                {"id": "cat-b", "name": "场景", "items": []},
            ]}
        ]
    }, ensure_ascii=False), encoding="utf-8")

    import main
    monkeypatch.setattr(main, "ASSET_LIBRARY_PATH", str(asset_path))

    with _isolated_db(monkeypatch, tmp_path) as db:
        from app.data_import import import_domain, reconcile_domain

        first = import_domain("asset_library", source_path=str(asset_path))
        # 1 library + 2 categories + 2 items = 5
        assert first.inserted == 5
        assert _row_count(db, "asset_libraries") == 1
        assert _row_count(db, "asset_categories") == 2
        assert _row_count(db, "asset_items") == 2

        # asset_items.file_ref 全部为 NULL（本 PR 不启用）
        import sqlite3
        conn = sqlite3.connect(str(db))
        try:
            rows = conn.execute("SELECT file_ref FROM asset_items").fetchall()
            assert rows and all(r[0] is None for r in rows)
        finally:
            conn.close()

        report = reconcile_domain("asset_library")
        assert report.counts["db"] == 5
        assert report.missing == []

        second = import_domain("asset_library", source_path=str(asset_path))
        assert second.inserted == 0


# ---------------------------------------------------------------------------
# canvas
# ---------------------------------------------------------------------------

def test_canvas_import_idempotent(monkeypatch, tmp_path):
    canvas_dir = tmp_path / "canvases"
    canvas_dir.mkdir()
    (canvas_dir / "cA.json").write_text(json.dumps({
        "id": "cA", "title": "画布 A", "kind": "classic", "revision": 3,
        "base_updated_at": "2026-07-19T00:00:00Z", "nodes": [], "connections": [],
    }, ensure_ascii=False), encoding="utf-8")
    (canvas_dir / "cB.json").write_text(json.dumps({
        "id": "cB", "title": "画布 B", "kind": "smart", "revision": 0,
    }, ensure_ascii=False), encoding="utf-8")

    import main
    monkeypatch.setattr(main, "CANVAS_DIR", str(canvas_dir))

    with _isolated_db(monkeypatch, tmp_path) as db:
        from app.data_import import import_domain, reconcile_domain

        first = import_domain("canvas", source_path=str(canvas_dir))
        assert first.inserted == 2
        assert _row_count(db, "canvases") == 2

        # revision 落到独立列
        import sqlite3
        conn = sqlite3.connect(str(db))
        try:
            rows = dict(conn.execute("SELECT legacy_id, revision FROM canvases").fetchall())
            assert rows.get("cA") == 3
            assert rows.get("cB") == 0
        finally:
            conn.close()

        report = reconcile_domain("canvas")
        # reconcile 走 store snapshot 默认 CANVAS_DIR = monkeypatch 后的目录
        assert report.counts["db"] == 2
        assert report.missing == []

        second = import_domain("canvas", source_path=str(canvas_dir))
        assert second.inserted == 0


# ---------------------------------------------------------------------------
# dry-run 不落库
# ---------------------------------------------------------------------------

def test_dry_run_does_not_persist(monkeypatch, tmp_path):
    projects_path = tmp_path / "projects.json"
    projects_path.write_text(json.dumps({
        "projects": [{"id": "p1", "name": "X", "order": 0}]
    }), encoding="utf-8")

    import main
    monkeypatch.setattr(main, "PROJECTS_PATH", str(projects_path))

    with _isolated_db(monkeypatch, tmp_path) as db:
        from app.data_import import import_domain

        outcome = import_domain("project", source_path=str(projects_path), dry_run=True)
        assert outcome.dry_run is True
        # dry-run 应该报告可插入数，但 DB 未提交
        assert outcome.candidate_count == 1
        assert _row_count(db, "projects") == 0

        # 之后真跑一次，验证 DB 空表 → 落 1 行（说明 dry_run 未把 legacy_id 提交）
        real = import_domain("project", source_path=str(projects_path))
        assert real.inserted == 1
        assert _row_count(db, "projects") == 1


def test_unknown_domain_rejected():
    from app.data_import import import_domain

    with pytest.raises(ValueError):
        import_domain("does_not_exist")
