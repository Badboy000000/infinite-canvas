"""任务 PR-4 · History writer 失败隔离契约测试。

模拟 writer 内部 raise：`_history_derive` 必须吞掉；`main.py` 侧
`history_store.save_to_history` 主写路径不受影响。
"""

from __future__ import annotations


def test_history_derive_swallows_writer_exception(monkeypatch):
    monkeypatch.setenv("TASK_HISTORY_ENABLE", "true")
    import main
    from app.task import history as history_module

    history_module.reset_history_writer()

    class ExplodingWriter:
        def write_from_task(self, *args, **kwargs):
            raise RuntimeError("history write blew up")

    monkeypatch.setattr(main, "_get_history_writer", lambda: ExplodingWriter())
    # main 层 helper 必须不抛
    record = {"prompt": "hi", "images": ["/x.png"], "type": "online"}
    assert main._history_derive("write_from_result", record=record) is None
    history_module.reset_history_writer()


def test_history_derive_unknown_operation_returns_none(monkeypatch):
    monkeypatch.setenv("TASK_HISTORY_ENABLE", "true")
    import main
    from app.task import history as history_module

    history_module.reset_history_writer()
    assert main._history_derive("nonexistent_op", record={"foo": "bar"}) is None
    history_module.reset_history_writer()


def test_save_to_history_main_write_survives_writer_failure(monkeypatch, tmp_path):
    """主写路径 (`save_to_history`) 在派生 writer raise 时仍然把 record
    写入 `history.json`——3 处调用点的 try/finally 顺序不受派生层影响。"""

    monkeypatch.setenv("TASK_HISTORY_ENABLE", "true")
    import json

    import main
    from app.task import history as history_module

    history_module.reset_history_writer()

    class ExplodingWriter:
        def write_from_task(self, *args, **kwargs):
            raise RuntimeError("simulated writer failure")

    monkeypatch.setattr(main, "_get_history_writer", lambda: ExplodingWriter())

    history_path = tmp_path / "history.json"
    monkeypatch.setattr(main, "HISTORY_FILE", str(history_path))
    record = {
        "prompt": "isolation",
        "images": ["/output/failure_test.png"],
        "type": "online",
        "task_id": "isolation-failure",
    }
    # 直接调用 save_to_history 主写路径 —— 派生失败应吞掉不影响写盘
    main.save_to_history(dict(record))
    assert main._history_derive("write_from_result", record=dict(record)) is None
    assert history_path.exists()
    saved = json.loads(history_path.read_text(encoding="utf-8"))
    assert len(saved) >= 1
    assert saved[0]["prompt"] == "isolation"
    history_module.reset_history_writer()
