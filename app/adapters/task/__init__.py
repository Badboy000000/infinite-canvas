"""Task adapter 接口（PR-BE-11 · Wave 3-N.7 Batch 3 主线 A）。

定义 `TaskStore` 抽象契约 —— 轻量级任务存储接口，供路由层和 service
层统一消费，不依赖 `app/task/store/` 承载层 Protocol。

Layout 对齐 `app/adapters/storage/` 模式：
- `__init__.py` — 接口定义
- `in_memory.py` — 内存实现
"""

from __future__ import annotations

import abc
from typing import Any, Optional


class TaskStore(abc.ABC):
    """轻量任务存储接口。

    三个读方法对齐 `app.modules.task.store.TaskModuleStore` 的薄委派 facade
    签名。不要求 ACID / 乐观锁 —— 适配层只做读封装。
    """

    @abc.abstractmethod
    def list_by_canvas(
        self, canvas_id: str, *, limit: int = 100
    ) -> list[Any]:
        """按画布 ID 列出关联任务。"""
        raise NotImplementedError

    @abc.abstractmethod
    def list_by_status(
        self, status: str, *, limit: int = 100
    ) -> list[Any]:
        """按状态列出任务。"""
        raise NotImplementedError

    @abc.abstractmethod
    def history_view(self, *, limit: int = 5000) -> list[dict]:
        """返回历史记录快照。"""
        raise NotImplementedError


__all__ = ["TaskStore"]