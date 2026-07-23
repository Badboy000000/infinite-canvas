"""Task 模块持久化 facade（PR-BE-11 · Wave 3-N.7 Batch 3 主线 A）。

PR-BE-11 将实现迁入 `app/adapters/task/in_memory.py`，本文件保留为
re-export 兼容层。所有调用方继续 `from app.modules.task.store import
TaskModuleStore` 不受影响。
"""

from __future__ import annotations

from app.adapters.task.in_memory import InMemoryTaskStore as TaskModuleStore

__all__ = ["TaskModuleStore"]
