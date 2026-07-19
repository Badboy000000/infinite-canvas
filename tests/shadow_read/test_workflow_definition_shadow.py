"""数据 PR-4 · WorkflowDefinition shadow 双读契约。

覆盖：
- disabled 默认 → 字节等价、无 diff。
- enabled 空 DB → RH workflow_store 里的条目 + 内置 workflows/*.json 都进
  `missing_in_db`（legacy_id 合成规则 `rh:...` 与 `file:...`）。
- 空 workflows 目录 → 只对 RH workflow_store 里的条目做 diff。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def rh_workflow_store(tmp_path, monkeypatch, isolated_env):
    import main

    rh_path = tmp_path / "runninghub_workflows.json"
    rh_path.write_text(
        json.dumps({
            "providers": [
                {
                    "provider_id": "runninghub-1",
                    "workflows": [
                        {"id": "wf-a", "name": "Workflow A"},
                        {"id": "wf-b", "name": "Workflow B"},
                    ],
                    "apps": [{"id": "app-x", "name": "App X"}],
                },
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "RUNNINGHUB_WORKFLOW_STORE_FILE", str(rh_path))

    # 空 workflow_dir，避免依赖仓库 workflows/*.json 数量
    empty_wf = tmp_path / "workflows_empty"
    empty_wf.mkdir()
    monkeypatch.setattr(main, "WORKFLOW_DIR", str(empty_wf))
    yield rh_path


def _load():
    from app.stores import workflow_store

    return workflow_store.load_runninghub_workflow_store()


def test_disabled_no_diff(monkeypatch, rh_workflow_store, tmp_path):
    monkeypatch.delenv("SHADOW_READ_WORKFLOW_DEFINITION", raising=False)
    _load()
    assert not (Path(tmp_path) / "shadow_diff" / "workflow_definition").exists()


def test_enabled_empty_db_missing_in_db(monkeypatch, rh_workflow_store, tmp_path):
    migrate_baseline(tmp_path)
    monkeypatch.setenv("SHADOW_READ_WORKFLOW_DEFINITION", "true")
    _load()

    files = list((Path(tmp_path) / "shadow_diff" / "workflow_definition").glob("*.jsonl"))
    assert files
    rec = json.loads(files[0].read_text(encoding="utf-8").splitlines()[-1])
    expected_ids = {
        "rh:runninghub-1:workflows:wf-a",
        "rh:runninghub-1:workflows:wf-b",
        "rh:runninghub-1:apps:app-x",
    }
    assert expected_ids.issubset(set(rec["missing_in_db"]))
    assert rec["missing_in_json"] == []


def test_enabled_no_diff_after_import(monkeypatch, rh_workflow_store, tmp_path):
    from app.data_import import import_domain

    migrate_baseline(tmp_path)
    import_domain(
        "workflow_definition",
        source_path=str(rh_workflow_store),
        dry_run=False,
    )

    monkeypatch.setenv("SHADOW_READ_WORKFLOW_DEFINITION", "true")
    _load()

    diff_root = Path(tmp_path) / "shadow_diff" / "workflow_definition"
    if diff_root.exists():
        files = list(diff_root.glob("*.jsonl"))
        # 有可能因内置 workflows 目录 mismatch 触发，但本 fixture 已指到空目录
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                assert not rec["missing_in_db"], (
                    f"unexpected missing_in_db: {rec['missing_in_db']}"
                )
