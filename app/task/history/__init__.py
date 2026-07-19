"""`app.task.history` — 任务 PR-4 History writer 辅助模块。

在 `main.py` 现有 `history_store.save_to_history(record)` 主写调用**旁边**挂钩，
把生成结果以 Task + Artifact 副本形式派生写入事实层。**主写仍是
`history.json`**，本模块不切主写路径、不承担任务恢复、不迁移数据。

关键契约（治理期）：

- **默认关闭**：只在 `TASK_HISTORY_ENABLE=1/true/yes/on/enable/enabled` 时启用。
- **失败隔离**：任何写副本失败只发 warning，绝不 raise 到 `save_to_history` 主
  写路径；`main._history_derive` 双层 `try/except` 兜底。
- **幂等**：同 task_id / provider_task_id 二次写返回原 Task id；`ProviderTask`
  层同复用 `(provider_id, upstream_task_id)` 命中。
- **一次性 migrate**：`get_history_writer()` 首次真正调用（`_ensure_ready()`）
  时才触发 `run_migrations("head")`；未启用时零副作用。

参见：
- [[40 实施计划/任务模型与后台任务治理实施计划与PR清单]] PR-4
- [[70 开发过程跟踪/PR 状态总账/PR - 任务模型]] 任务 PR-4
"""

from __future__ import annotations

from app.task.history.writer import (
    HistoryWriter,
    get_history_writer,
    is_history_writer_enabled,
    register_history_from_task,
    reset_history_writer,
    write_history_from_task,
)

__all__ = [
    "HistoryWriter",
    "get_history_writer",
    "is_history_writer_enabled",
    "register_history_from_task",
    "reset_history_writer",
    "write_history_from_task",
]
