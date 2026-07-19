"""任务 PR-3 · 影子失败隔离契约测试。

模拟 registry 内部 raise：`_shadow_register` 必须吞掉；`main` 侧
`run_canvas_image_task` 的 `try/finally` 顺序不受影响。
"""

from __future__ import annotations


def test_shadow_register_swallows_registry_exception(monkeypatch):
    monkeypatch.setenv("TASK_SHADOW_ENABLE", "true")
    import main
    from app.task import shadow as shadow_module

    shadow_module.reset_shadow_registry()

    class ExplodingRegistry:
        def register_submit(self, *args, **kwargs):
            raise RuntimeError("shadow write blew up")

        def register_transition(self, *args, **kwargs):
            raise RuntimeError("shadow write blew up")

        def register_release(self, *args, **kwargs):
            raise RuntimeError("shadow write blew up")

    monkeypatch.setattr(main, "_get_shadow_registry", lambda: ExplodingRegistry())
    # main 层 helper 必须不抛
    assert main._shadow_register("submit", "canvas_img_boom", task_type="x") is None
    assert main._shadow_register("transition", "canvas_img_boom", status="running") is None
    assert (
        main._shadow_register("release", "canvas_img_boom", status="failed", error_message="e")
        is None
    )
    shadow_module.reset_shadow_registry()


def test_shadow_register_unknown_operation_returns_none(monkeypatch):
    monkeypatch.setenv("TASK_SHADOW_ENABLE", "true")
    import main
    from app.task import shadow as shadow_module

    shadow_module.reset_shadow_registry()
    assert main._shadow_register("nonexistent_op", "canvas_img_x") is None
    shadow_module.reset_shadow_registry()


def test_registry_init_failure_is_isolated(monkeypatch, caplog):
    """迁移失败时 registry 保持 broken 状态，helper 返回 None。"""

    monkeypatch.setenv("TASK_SHADOW_ENABLE", "true")
    from app.task import shadow as shadow_module

    shadow_module.reset_shadow_registry()
    registry = shadow_module.get_shadow_registry()
    # 注入一个必失败的 run_migrations
    import app.db.engine as db_engine

    def failing_migrate(rev):
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(db_engine, "run_migrations", failing_migrate)
    # 强制走 lazy init
    result = registry.register_submit("canvas_img_boom_init", task_type="online-image")
    assert result is None
    assert registry._broken is True
    # 再调用一次也应走 broken 快路
    assert registry.register_submit("canvas_img_boom_init2", task_type="online-image") is None
    shadow_module.reset_shadow_registry()
