"""数据 PR-4 · PromptLibrary shadow 双读契约。

- disabled 默认 → 字节等价，无 diff。
- enabled 空 DB → 所有 library 进 missing_in_db。
- enabled 篡改字段 → field_diff 命中。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def prompt_lib_file(tmp_path, monkeypatch, isolated_env):
    import main

    p = tmp_path / "prompt_libraries.json"
    p.write_text(
        json.dumps({
            "active_library_id": "system",
            "libraries": [
                {"id": "system", "name": "System", "scope": "system", "items": []},
                {"id": "user1", "name": "User Lib", "scope": "user", "items": []},
            ],
            "updated_at": 1_234_567_890,
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "PROMPT_LIBRARY_PATH", str(p))
    yield p


def _load():
    from app.stores import prompt_library_store

    return prompt_library_store.load_prompt_libraries()


def test_disabled_no_diff(monkeypatch, prompt_lib_file, tmp_path):
    monkeypatch.delenv("SHADOW_READ_PROMPT_LIBRARY", raising=False)
    _load()
    assert not (Path(tmp_path) / "shadow_diff" / "prompt_library").exists()


def test_enabled_empty_db_yields_missing(monkeypatch, prompt_lib_file, tmp_path):
    migrate_baseline(tmp_path)
    monkeypatch.setenv("SHADOW_READ_PROMPT_LIBRARY", "true")
    _load()
    files = list((Path(tmp_path) / "shadow_diff" / "prompt_library").glob("*.jsonl"))
    assert files
    rec = json.loads(files[0].read_text(encoding="utf-8").splitlines()[-1])
    assert set(rec["missing_in_db"]) == {"system", "user1"}


def test_enabled_field_diff_after_rename(
    monkeypatch, prompt_lib_file, tmp_path
):
    from app.data_import import import_domain

    migrate_baseline(tmp_path)
    import_domain(
        "prompt_library", source_path=str(prompt_lib_file), dry_run=False
    )

    # rename user1
    payload = json.loads(prompt_lib_file.read_text(encoding="utf-8"))
    payload["libraries"][1]["name"] = "User Lib Renamed"
    prompt_lib_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv("SHADOW_READ_PROMPT_LIBRARY", "true")
    _load()

    files = list((Path(tmp_path) / "shadow_diff" / "prompt_library").glob("*.jsonl"))
    assert files
    rec = json.loads(files[0].read_text(encoding="utf-8").splitlines()[-1])
    diffs = {(d["legacy_id"], d["field"]) for d in rec["field_diffs"]}
    assert ("user1", "name") in diffs
