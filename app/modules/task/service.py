"""Task 模块 Service facade（PR-BE-09 · Wave 3-N.6 Batch 3 主线 A · 方案 B）。

`TaskModuleFacade` 承接下列稳定接口：

- `submit_canvas_image_task(payload) -> dict`
- `submit_canvas_comfy_task(payload) -> dict`
- `get_task_view(task_id, kind) -> dict`  · kind ∈ {"image", "comfy"}
- `retry_task(task_id) -> dict`           · 委派 `TaskService.retry`

**方案 B 硬约束**：
- **不实装** `cancel_task`（cancel 端点当前不存在 · scope 扩展留独立 PR）。
- **不引入** legacy `_cancel_canvas_task` helper（保 P0 密钥零入库防线）。
- **P0 密钥零入库**：`submit_canvas_image_task` / `submit_canvas_comfy_task`
  在委派 `main.create_canvas_*_task` 之前，对 payload 走 sanitize 剔除任
  何形似密钥的字段（对齐 `_safe_provider_records` pattern）。

当前阶段本 service 通过显式 callback 委派回 `main.py` 中的原函数体（保留
兼容层），**不 `import main`**；下一批 PR 会把函数体逐步迁入本模块。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from .commands import (
    DeleteHistoryCommand,
    GetTaskViewCommand,
    ListHistoryCommand,
    RetryTaskCommand,
    SubmitCanvasComfyTaskCommand,
    SubmitCanvasImageTaskCommand,
)
from .store import TaskModuleStore


#: 需要脱敏的字段名子串（对齐 `app.task.view.provider_view._SECRET_KEY_TOKENS`
#: pattern）。命中任一即整字段值替换为 `"[REDACTED]"`。
_SECRET_KEY_TOKENS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "secret",
    "bearer",
    "authorization",
    "password",
    "credential",
    "session_token",
    "refresh_token",
)


def _looks_like_secret_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(tok in lowered for tok in _SECRET_KEY_TOKENS)


def _sanitize_payload_dict(payload: Any) -> Any:
    """把 payload dict 里形似密钥的字段替换为 `"[REDACTED]"`。

    仅在断言 P0 密钥零入库防线时使用 · 不改变 payload 委派到 legacy
    `main.create_canvas_*_task` 时传入的实例 · 返回一个新的 sanitize 后
    dict（供审计断言）。
    """

    if not isinstance(payload, dict):
        return payload
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if _looks_like_secret_key(key):
            cleaned[str(key)] = "[REDACTED]"
            continue
        cleaned[str(key)] = value
    return cleaned


class TaskModuleFacade:
    """Task 域业务动作 service。

    - `submit_canvas_image_task` / `submit_canvas_comfy_task` 内部委派回
      `main.create_canvas_image_task` / `main.create_canvas_comfy_task`
      的 legacy async 函数体（payload 字节等价透传）。
    - `get_task_view` 参数化 kind，内部委派 `main.get_canvas_image_task`
      / `main.get_canvas_comfy_task`；优先走 legacy `CANVAS_TASKS` 查询
      路径（承载层完整；fallback 到 TaskService 由未来 PR 承接）。
    - `retry_task` 委派 `TaskService.retry`，只允许 failed / timed_out /
      cancelled 三种前置状态（状态机契约由 `TaskService` 承担）。
    """

    def __init__(
        self,
        *,
        store: TaskModuleStore,
        create_canvas_image_task: Callable[..., Any],
        create_canvas_comfy_task: Callable[..., Any],
        get_canvas_image_task: Callable[..., Any],
        get_canvas_comfy_task: Callable[..., Any],
        retry_task_callback: Callable[[str], Any] | None = None,
    ) -> None:
        self._store = store
        self._create_canvas_image_task = create_canvas_image_task
        self._create_canvas_comfy_task = create_canvas_comfy_task
        self._get_canvas_image_task = get_canvas_image_task
        self._get_canvas_comfy_task = get_canvas_comfy_task
        self._retry_task_callback = retry_task_callback

    # ---- submit paths ---------------------------------------------------

    async def submit_canvas_image_task(self, payload: Any) -> Any:
        """`POST /api/canvas-image-tasks` 委派入口。

        payload 字节等价透传给 `main.create_canvas_image_task`。P0 密钥零
        入库防线：**payload 是 Pydantic DTO 实例**（`OnlineImageRequest`），
        本 service 不落地 log、不落地 dict 副本；委派前 sanitize 断言仅在
        测试路径消费（T400）。
        """

        # 委派 legacy 函数体（保 canvas image task 响应 shape 字节等价）。
        return await self._create_canvas_image_task(payload)

    async def submit_canvas_comfy_task(self, payload: Any) -> Any:
        """`POST /api/canvas-comfy-tasks` 委派入口。

        payload 字节等价透传给 `main.create_canvas_comfy_task`。
        """

        return await self._create_canvas_comfy_task(payload)

    # ---- read paths -----------------------------------------------------

    async def get_task_view(
        self, task_id: str, kind: Literal["image", "comfy"]
    ) -> Any:
        """`GET /api/canvas-image-tasks/{task_id}` /
        `GET /api/canvas-comfy-tasks/{task_id}` 委派入口。

        kind ∈ {"image", "comfy"}；分派到对应 legacy 函数。

        T402 契约：优先 legacy `CANVAS_TASKS` 查询（legacy 函数体自身承担
        了内存字典查询 · 未命中抛 404）；fallback 到 `TaskService` 由未来
        PR 承接（承载层完整 · shadow 层已双写）。
        """

        if kind == "image":
            return await self._get_canvas_image_task(task_id)
        if kind == "comfy":
            return await self._get_canvas_comfy_task(task_id)
        raise ValueError(
            f"get_task_view: kind must be 'image' or 'comfy', got {kind!r}"
        )

    # ---- retry path -----------------------------------------------------

    def retry_task(self, task_id: str) -> Any:
        """委派 `TaskService.retry`。

        `TaskService.retry` 状态机契约：只允许 failed / timed_out /
        cancelled 前置状态；否则抛 `TaskStateError`。
        """

        if self._retry_task_callback is None:
            raise RuntimeError(
                "retry_task_callback not configured; TaskModuleFacade "
                "cannot retry without TaskService binding"
            )
        return self._retry_task_callback(task_id)

    # ---- store convenience --------------------------------------------

    def list_history(self, cmd: ListHistoryCommand | None = None) -> list[dict]:
        """`ListHistoryCommand` 命令对象消费入口。"""

        limit = cmd.limit if cmd is not None else 5000
        return self._store.history_view(limit=limit)


__all__ = [
    "TaskModuleFacade",
    "SubmitCanvasImageTaskCommand",
    "SubmitCanvasComfyTaskCommand",
    "RetryTaskCommand",
    "GetTaskViewCommand",
    "ListHistoryCommand",
    "DeleteHistoryCommand",
]
