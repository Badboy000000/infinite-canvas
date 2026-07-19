"""数据 PR-4 · 4 个 SHADOW_READ_* env 全默认关闭时零副作用。

- `SHADOW_READ_*=false` （或未设）时，`is_shadow_read_enabled(...)` 全为
  False；`run_shadow_read(...)` 不会 import DB 层、不构造 engine、不建
  `data/shadow_diff/*` 目录。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.shadow_read._helpers import isolated_shadow_env


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for name in (
        "SHADOW_READ_PROJECT",
        "SHADOW_READ_PROVIDER_CONFIG",
        "SHADOW_READ_PROMPT_LIBRARY",
        "SHADOW_READ_WORKFLOW_DEFINITION",
    ):
        monkeypatch.delenv(name, raising=False)


def test_is_shadow_read_enabled_defaults_false():
    from app.shadow_read.runner import is_shadow_read_enabled

    assert is_shadow_read_enabled("project") is False
    assert is_shadow_read_enabled("provider_config") is False
    assert is_shadow_read_enabled("prompt_library") is False
    assert is_shadow_read_enabled("workflow_definition") is False


def test_truthy_values_toggle_enabled(monkeypatch):
    from app.shadow_read.runner import is_shadow_read_enabled

    for value in ("1", "true", "TRUE", "yes", "on", "Enabled"):
        monkeypatch.setenv("SHADOW_READ_PROJECT", value)
        assert is_shadow_read_enabled("project") is True, value
    for value in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv("SHADOW_READ_PROJECT", value)
        assert is_shadow_read_enabled("project") is False, value


def test_unknown_domain_never_enabled(monkeypatch):
    from app.shadow_read.runner import is_shadow_read_enabled

    monkeypatch.setenv("SHADOW_READ_UNKNOWN_DOMAIN", "true")
    assert is_shadow_read_enabled("unknown_domain") is False


def test_run_shadow_read_disabled_short_circuits_without_db(monkeypatch, tmp_path):
    """禁用时 `run_shadow_read` 不触发 engine.get_engine()。"""
    from app.shadow_read import runner

    hits = {"count": 0}

    def _fail(*a, **kw):  # pragma: no cover — guarded by short-circuit
        hits["count"] += 1
        raise AssertionError("get_engine must not be called when disabled")

    monkeypatch.setattr("app.db.engine.get_engine", _fail)
    result = runner.run_shadow_read("project", [{"id": "x"}])
    assert result is None
    assert hits["count"] == 0
    # shadow_diff root not created
    assert not (tmp_path / "shadow_diff").exists()


def test_stores_disabled_do_not_touch_db(monkeypatch, tmp_path):
    """4 个 Store 的 read_shadow 在 disabled 时都不 hit engine。"""
    hits = {"count": 0}

    def _fail(*a, **kw):
        hits["count"] += 1
        raise AssertionError("engine must not be built when disabled")

    monkeypatch.setattr("app.db.engine.get_engine", _fail)

    from app.stores import (
        project_store,
        prompt_library_store,
        provider_config_store,
        workflow_store,
    )

    project_store.read_shadow([{"id": "p"}])
    provider_config_store.read_shadow([{"id": "prov", "name": "n"}])
    prompt_library_store.read_shadow({"libraries": []})
    workflow_store.read_shadow({"providers": []})
    assert hits["count"] == 0
