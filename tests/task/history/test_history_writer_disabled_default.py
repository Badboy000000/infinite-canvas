"""任务 PR-4 · 默认关闭契约测试。

`TASK_HISTORY_ENABLE` 未设置时，4 类挂钩点必须 no-op：
1. `write_history_from_task(record=...)` 顶层 helper 直接返回 None；
2. `main._history_derive("write_from_result", record=...)` 返回 None；
3. `HistoryWriter.write_from_task(source_record=...)` 返回 None；
4. registry 内部 `_task_store` 不构造（未 migrate）。
"""

from __future__ import annotations


def test_env_default_disabled(monkeypatch):
    monkeypatch.delenv("TASK_HISTORY_ENABLE", raising=False)
    from app.task.history import is_history_writer_enabled

    assert is_history_writer_enabled() is False


def test_write_from_task_noop_when_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("TASK_HISTORY_ENABLE", raising=False)
    from app.task.history import get_history_writer, reset_history_writer

    reset_history_writer()
    writer = get_history_writer()
    record = {
        "prompt": "hi",
        "images": ["/output/a.png"],
        "type": "online",
        "provider_id": "comfly",
    }
    result = writer.write_from_task(source_record=record)
    assert result is None
    # 未启用时 store 也没被建（避免 __init__ 的 migrate 副作用）
    assert writer._task_store is None
    reset_history_writer()


def test_history_derive_helper_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("TASK_HISTORY_ENABLE", raising=False)
    import main
    from app.task.history import reset_history_writer

    reset_history_writer()
    record = {
        "prompt": "hi",
        "images": ["/output/a.png"],
        "type": "online",
    }
    assert (
        main._history_derive("write_from_result", record=record) is None
    )
    reset_history_writer()


def test_truthy_env_values(monkeypatch):
    from app.task.history import is_history_writer_enabled

    for value in ("1", "true", "TRUE", "yes", "on", "Enabled"):
        monkeypatch.setenv("TASK_HISTORY_ENABLE", value)
        assert is_history_writer_enabled() is True, value
    for value in ("0", "false", "no", "off", "", "maybe"):
        monkeypatch.setenv("TASK_HISTORY_ENABLE", value)
        assert is_history_writer_enabled() is False, value
