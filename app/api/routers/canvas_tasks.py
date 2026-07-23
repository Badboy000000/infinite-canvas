"""Canvas tasks 路由分组（PR-BE-09 · Wave 3-N.6 Batch 3 主线 A · 方案 B）。

方案 B 硬约束：仅承载**唯二可抽装饰器**：
- `GET /api/queue_status`
- `POST /api/history/delete`

（canvas-image-tasks + canvas-comfy-tasks 已在 PR-BE-08 抽入 generation.py；
`GET /api/history` 已在 PR-BE-05 抽入 history.py；cancel 端点当前不存在）。

设计原则：
- **不 `import main`**：全部端点函数通过 `create_router(...)` 参数注入
  callback（对齐 PR-BE-05/06/08 硬约束）。
- 请求 / 响应 shape 与错误码保持逐字节一致。
- 通过 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐（`get_queue_status` / `delete_history`）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    get_queue_status_callback: Callable[[str], Awaitable[Any]],
    delete_history_callback: Callable[[Any], Awaitable[Any]],
    delete_history_dto: type,
) -> APIRouter:
    """构造 canvas tasks 路由分组。

    参数：
    - `get_queue_status_callback`：`(client_id: str) -> Awaitable[dict]` ·
      委派 legacy `main.get_queue_status` 函数体。
    - `delete_history_callback`：`(req: DeleteHistoryRequest) -> Awaitable[dict]`
      · 委派 legacy `main.delete_history` 函数体。
    - `delete_history_dto`：`DeleteHistoryRequest` Pydantic DTO 类型 · FastAPI
      在 request body 上做 schema 校验。
    """

    router = APIRouter()

    # `name="get_queue_status"` 让 FastAPI 生成 `operationId =
    # get_queue_status_api_queue_status_get`,与 baseline byte-equivalent。
    router.add_api_route(
        "/api/queue_status",
        get_queue_status_callback,
        methods=["GET"],
        name="get_queue_status",
    )

    async def delete_history(req: delete_history_dto):  # type: ignore[valid-type]
        return await delete_history_callback(req)

    # 显式把 DTO 类型写回函数注解,让 FastAPI 的 `get_typed_return_annotation`
    # 能在闭包外求值命中(闭包变量对 `inspect.signature(eval_str=True)` 不可
    # 见);`add_api_route` 会读取该注解注入 request body schema。
    delete_history.__annotations__["req"] = delete_history_dto
    # `name="delete_history"` → `operationId = delete_history_api_history_delete_post`,
    # 与 baseline byte-equivalent。
    router.add_api_route(
        "/api/history/delete",
        delete_history,
        methods=["POST"],
        name="delete_history",
    )

    return router


__all__ = ["create_router"]
