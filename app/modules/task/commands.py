"""Task 命令对象（PR-BE-09 · Wave 3-N.6 Batch 3 主线 A · 方案 B 收缩承接）。

命令对象承接 `main.py` 中 canvas image / comfy task + history-delete 端点
的入参。每个命令对象都保留一个 `raw: dict` 字段作为宽松兜底，防止 legacy
宽松 JSON 字段在 Service 边界上因显式建模而丢失（参照 PR-BE-06 canvas
commands + PR-BE-08 provider commands 硬约束）。

设计约束（任务书零触碰事实清单）：
- **不改** `OnlineImageRequest` / `GenerateRequest` / `DeleteHistoryRequest`
  等 Pydantic DTO 字段与默认值。命令对象只是从 DTO 组装出来的、供 Service
  内部使用的独立轻量类型；请求 / 响应 shape 与错误码保持逐字节一致。
- 命令对象刻意不引入校验；校验依然在 FastAPI DTO 层完成。
- **P0 密钥字段**（如 payload 里可能透传的 api_key / secret 字段）走
  `raw: dict` 承接，Service 层在委派 `main.create_canvas_image_task` 之前
  会执行 sanitize（参照 `_safe_provider_records` pattern）。

方案 B 硬约束：
- **不含** `CancelTaskCommand`（cancel 端点当前不存在 · 独立 PR 承接）。
- **不含** legacy `_cancel_canvas_task` 相关命令（保 P0 密钥零入库防线）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class SubmitCanvasImageTaskCommand:
    """`POST /api/canvas-image-tasks` 命令对象。

    `payload` 直接持有 `OnlineImageRequest` DTO 实例（保 legacy 字段
    形状）。`raw: dict` 兜底保留调用侧原始 payload 字典。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubmitCanvasComfyTaskCommand:
    """`POST /api/canvas-comfy-tasks` 命令对象。

    `payload` 直接持有 `GenerateRequest` DTO 实例。
    """

    payload: Any
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetryTaskCommand:
    """任务重试命令对象（委派 `TaskService.retry`）。

    仅承载 `TaskService.retry` 的状态机契约（只允许 failed / timed_out /
    cancelled）。当前无路由入口消费；保留公开签名以对齐任务书 §1，方便
    下一批 PR 的细粒度 API 扩展直接消费。
    """

    task_id: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GetTaskViewCommand:
    """`GET /api/canvas-image-tasks/{task_id}` / `GET /api/canvas-comfy-tasks/{task_id}`
    命令对象。

    `kind` 参数化 image / comfy，避免重复建模；Service 内部按 kind 委派
    到对应 legacy `main.get_canvas_image_task` / `main.get_canvas_comfy_task`。
    """

    task_id: str
    kind: Literal["image", "comfy"]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ListHistoryCommand:
    """`GET /api/history`（PR-BE-05 已挂 · 路由层不动 · 本 store 内部消费）。

    `limit` 默认 5000（承接数据 PR-12 · `load_history_db` 的 `HISTORY_MAX_RECORDS`
    上限；load_history() facade 内部裁剪一致）。
    """

    limit: int = 5000
    type_filter: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeleteHistoryCommand:
    """`POST /api/history/delete` 命令对象。

    承接 `DeleteHistoryRequest`（`timestamp: float`）。Service 层通过
    callback 委派回 legacy `main.delete_history` 函数体。
    """

    timestamp: float
    raw: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "SubmitCanvasImageTaskCommand",
    "SubmitCanvasComfyTaskCommand",
    "RetryTaskCommand",
    "GetTaskViewCommand",
    "ListHistoryCommand",
    "DeleteHistoryCommand",
]
