"""任务 PR-3 · ProviderTask 副本 + `(provider_id, upstream_task_id)` 幂等。"""

from __future__ import annotations

import pytest

from tests.task.shadow._helpers import isolated_shadow_db


@pytest.fixture
def enable_shadow(monkeypatch):
    monkeypatch.setenv("TASK_SHADOW_ENABLE", "true")
    yield


def test_provider_task_registered_once(monkeypatch, tmp_path, enable_shadow):
    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        registry.register_submit("canvas_img_prov", task_type="online-image")
        first = registry.register_provider_task(
            "canvas_img_prov",
            provider_id="runninghub",
            provider_protocol="runninghub",
            upstream_task_id="rh-abc-1",
        )
        second = registry.register_provider_task(
            "canvas_img_prov",
            provider_id="runninghub",
            provider_protocol="runninghub",
            upstream_task_id="rh-abc-1",
        )
        assert first is not None
        assert first == second


def test_provider_task_upstream_key_isolates_providers(
    monkeypatch, tmp_path, enable_shadow
):
    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        registry.register_submit("canvas_img_iso", task_type="online-image")
        pt1 = registry.register_provider_task(
            "canvas_img_iso",
            provider_id="runninghub",
            provider_protocol="runninghub",
            upstream_task_id="rh-x",
        )
        pt2 = registry.register_provider_task(
            "canvas_img_iso",
            provider_id="comfly",
            provider_protocol="comfly",
            upstream_task_id="rh-x",
        )
        assert pt1 != pt2  # 不同 provider 视作不同上游


def test_provider_task_returns_none_when_task_unknown(
    monkeypatch, tmp_path, enable_shadow
):
    from app.task.shadow import get_shadow_registry

    with isolated_shadow_db(monkeypatch, tmp_path):
        registry = get_shadow_registry()
        result = registry.register_provider_task(
            "canvas_never_submitted",
            provider_id="runninghub",
            provider_protocol="runninghub",
            upstream_task_id="stray",
        )
        assert result is None
