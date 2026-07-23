"""InMemoryTaskStore — TaskStore 接口的内存实现。

从 `app/modules/task/store.py` `TaskModuleStore` 迁入（PR-BE-11 · Wave
3-N.7 Batch 3 主线 A）。原文件保留为 re-export 兼容层。
"""

from __future__ import annotations

from typing import Any

from app.adapters.task import TaskStore
from app.stores import history_store as _history_store_facade
from app.task.contracts import RecoveryFilter
from app.task.store import TaskStore as _TaskStoreProtocol


class InMemoryTaskStore(TaskStore):
    """薄委派 store —— 让 service 层不用直接 `import main`。

    构造参数 `task_store` 接受 `app.task.store.TaskStore` Protocol 实现
    （可为 None，此时 list_by_canvas / list_by_status 返回空列表）。
    """

    def __init__(self, task_store: _TaskStoreProtocol | None = None) -> None:
        self._task_store = task_store

    def list_by_canvas(
        self, canvas_id: str, *, limit: int = 100
    ) -> list[Any]:
        """`TaskStore.list_by_canvas_node` 薄委派（node_id 缺省）。"""

        if self._task_store is None:
            return []
        return list(
            self._task_store.list_by_canvas_node(canvas_id, limit=limit)
        )

    def list_by_status(
        self, status: str, *, limit: int = 100
    ) -> list[Any]:
        """`TaskStore.scan(RecoveryFilter(statuses=(status,), limit=limit))`
        薄委派。
        """

        if self._task_store is None:
            return []
        return list(
            self._task_store.scan(
                RecoveryFilter(statuses=(status,), limit=limit)
            )
        )

    def history_view(self, *, limit: int = 5000) -> list[dict]:
        """`app.stores.history_store.load_history()` 薄委派。"""

        records = _history_store_facade.load_history()
        if not isinstance(records, list):
            return []

        def _sort_key(item: dict) -> float:
            ts = item.get("timestamp", 0) if isinstance(item, dict) else 0
            if isinstance(ts, (int, float)):
                return float(ts)
            return 0.0

        sorted_records = sorted(records, key=_sort_key, reverse=True)
        if limit > 0:
            return sorted_records[:limit]
        return sorted_records


__all__ = ["InMemoryTaskStore"]