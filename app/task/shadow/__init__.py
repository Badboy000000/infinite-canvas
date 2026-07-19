"""`app.task.shadow` — 任务 PR-3 影子登记辅助模块。

在 `main.py` 现有 `CANVAS_TASKS` 交互点旁挂钩，把新事实层（TaskService /
ProviderTaskService / NodeRunService）副本写入 SQLite 后端。**读路径不
切**，`CANVAS_TASKS` 仍是事实源。

关键契约（治理期）：

- **默认关闭**：只在 `TASK_SHADOW_ENABLE=1/true/yes/on` 时启用。
- **失败隔离**：任何写副本失败只发 warning，绝不 raise 到旧路径。
- **幂等**：同一 `canvas_task_id` 多次进入 register / transition，副本按
  `idempotency_key` (submit 侧) 与 `(provider_id, upstream_task_id)`
  (ProviderTask 侧) 去重。
- **一次性 migrate**：`get_shadow_registry()` 首次调用触发
  `run_migrations("head")`；之后返回同一 registry。

参见：
- `40 实施计划/任务模型与后台任务治理实施计划与PR清单.md` PR-3
- `70 开发过程跟踪/PR 状态总账/PR - 任务模型.md` 任务 PR-3
"""

from __future__ import annotations

from app.task.shadow.register import (
    ShadowRegistry,
    get_shadow_registry,
    is_shadow_enabled,
    reset_shadow_registry,
)

__all__ = [
    "ShadowRegistry",
    "get_shadow_registry",
    "is_shadow_enabled",
    "reset_shadow_registry",
]
