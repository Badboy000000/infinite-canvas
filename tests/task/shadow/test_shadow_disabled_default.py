"""任务 PR-3 · 默认关闭契约测试。

未设置 `TASK_SHADOW_ENABLE` 时，`register_*` 都必须 no-op；`main._shadow_register`
不因 registry 内部路径退化。
"""

from __future__ import annotations


def test_env_default_disabled(monkeypatch):
    monkeypatch.delenv("TASK_SHADOW_ENABLE", raising=False)
    from app.task.shadow import is_shadow_enabled

    assert is_shadow_enabled() is False


def test_register_submit_noop_when_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("TASK_SHADOW_ENABLE", raising=False)
    from app.task.shadow import get_shadow_registry, reset_shadow_registry

    reset_shadow_registry()
    registry = get_shadow_registry()
    result = registry.register_submit("canvas_img_off", task_type="online-image")
    assert result is None
    # 未启用时 store 也没被建（避免 __init__ 的 migrate 副作用）
    assert registry._task_store is None
    reset_shadow_registry()


def test_shadow_register_helper_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("TASK_SHADOW_ENABLE", raising=False)
    import main
    from app.task.shadow import reset_shadow_registry

    reset_shadow_registry()
    assert main._shadow_register("submit", "canvas_img_off_helper", task_type="x") is None
    assert main._shadow_register("transition", "canvas_img_off_helper", status="running") is None
    assert main._shadow_register("release", "canvas_img_off_helper", status="succeeded") is None
    reset_shadow_registry()


def test_truthy_env_values(monkeypatch):
    from app.task.shadow import is_shadow_enabled

    for value in ("1", "true", "TRUE", "yes", "on", "Enabled"):
        monkeypatch.setenv("TASK_SHADOW_ENABLE", value)
        assert is_shadow_enabled() is True, value
    for value in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv("TASK_SHADOW_ENABLE", value)
        assert is_shadow_enabled() is False, value
