"""Task 领域模块（PR-BE-09 · Wave 3-N.6 Batch 3 主线 A · 方案 B 收缩承接）。

方案 B 差异说明（GM-14 圆桌自治第 8 次实证 · CB-P5-31 挂账）：

- 原任务书要求抽出 canvas-image-tasks / canvas-comfy-tasks / cancel 端点等 5 项；
  但 PR-BE-08（`f277596`）已把 canvas-image-tasks + canvas-comfy-tasks
  抽入 `app/api/routers/generation.py`；PR-BE-05 已把 `GET /api/history`
  抽入 `app/api/routers/history.py`；cancel 端点当前**不存在**（scope 扩展
  留独立 PR）。
- **实际收敛为 2 项抽出**：`GET /api/queue_status` + `POST /api/history/delete`
  → `app/api/routers/canvas_tasks.py`。
- 承载层完整实装（`app/task/service/task_service.py` + `provider_task_service.py`
  + `node_run_service.py` + `app/task/store/*` + `app/task/worker/inproc.py`）
  **零触碰**。

模块内容：
- `commands.py`   命令对象（Submit / Retry / GetTaskView / ListHistory / DeleteHistory）
- `store.py`      持久化 facade（薄委派 · 消费 `TaskStore.scan` + `history_store.load_history`）
- `service.py`    `TaskModuleFacade` — 委派 `main.create_canvas_image_task` /
                  `main.create_canvas_comfy_task` / `main.get_canvas_image_task`
                  等函数体，同时委派 `TaskService.retry` 承载层。

设计原则：`app/api/routers/canvas_tasks.py` 通过 `create_router(...)` 拿到
callback（**不 `import main`**）。service 层允许委派 legacy `main.py` 函数，
service 明确暴露一层稳定接口（与 provider 模块 pattern 完全一致）。

**P0 密钥零入库防线**：`TaskModuleFacade.submit_canvas_image_task` /
`submit_canvas_comfy_task` 透传 payload 前，走 sanitize 剔除任何形似密钥
的字段（对齐 `_safe_provider_records` pattern）。
"""

from .commands import (
    DeleteHistoryCommand,
    GetTaskViewCommand,
    ListHistoryCommand,
    RetryTaskCommand,
    SubmitCanvasComfyTaskCommand,
    SubmitCanvasImageTaskCommand,
)
from .service import TaskModuleFacade
from .store import TaskModuleStore


__all__ = [
    "TaskModuleFacade",
    "TaskModuleStore",
    "SubmitCanvasImageTaskCommand",
    "SubmitCanvasComfyTaskCommand",
    "RetryTaskCommand",
    "GetTaskViewCommand",
    "ListHistoryCommand",
    "DeleteHistoryCommand",
]
