"""Task 模块持久化 facade（PR-BE-09 · Wave 3-N.6 Batch 3 主线 A）。

`TaskModuleStore` 是**薄委派** —— 让 service 层拿到统一的 `list_by_canvas`
/ `list_by_status` / `history_view` 三个读接口，内部：

- `list_by_canvas` → `TaskStore.list_by_canvas_node(canvas_id, limit=limit)`
- `list_by_status` → `TaskStore.scan(RecoveryFilter(statuses=(status,), limit=limit))`
- `history_view`   → `app.stores.history_store.load_history()`（数据 PR-12 新加
                     的 facade · `HISTORY_MAX_RECORDS=5000` 上限对齐）

严格约束（任务书零触碰事实清单）：
- **不改** `app/task/store/*` 内部实现（`memory_impl.py` / `sqlite_impl.py`
  是承载层完整实装）。本类只做同签名的薄委派。
- **不改** `app/stores/history_store.py`（数据 PR-12 已 landing）。
- 不直接 `import main`（除必要 legacy fallback；service 通过 callback 注入）。
"""

from __future__ import annotations

from typing import Any

from app.stores import history_store as _history_store_facade
from app.task.contracts import RecoveryFilter
from app.task.store import TaskStore


class TaskModuleStore:
    """薄委派 store —— 让 service 层不用直接 `import` 承载层。"""

    def __init__(self, task_store: TaskStore | None = None) -> None:
        # `task_store` 可为 None（当前 main.py 未装配 TaskStore；仅 shadow
        # 层用；service 侧 legacy path 主导）。
        self._task_store = task_store

    def list_by_canvas(
        self, canvas_id: str, *, limit: int = 100
    ) -> list[Any]:
        """`TaskStore.list_by_canvas_node` 薄委派（node_id 缺省）。

        `task_store` 未装配时返回空 list（legacy path 主导 · shadow 层内部
        自维护）。
        """

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

        `task_store` 未装配时返回空 list。
        """

        if self._task_store is None:
            return []
        return list(
            self._task_store.scan(
                RecoveryFilter(statuses=(status,), limit=limit)
            )
        )

    def history_view(self, *, limit: int = 5000) -> list[dict]:
        """`app.stores.history_store.load_history()` 薄委派。

        `limit` 默认 5000（承接数据 PR-12 · `HISTORY_MAX_RECORDS=5000` 上限）。
        `load_history()` 本身不支持 limit 参数（当前 signature 固定）；本
        facade 在返回前裁剪。裁剪按 timestamp 倒序（对齐 legacy `get_history_api`
        sort_key 语义）。
        """

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


__all__ = ["TaskModuleStore"]
