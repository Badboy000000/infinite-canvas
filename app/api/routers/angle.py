"""Angle / ModelScope 角度控制路由分组（PR-BE-11 · Wave 3-N.7 Batch 3 主线 A）。

抽出 `main.py` 中 2 角度控制路由：
- `POST   /api/angle/poll_status`  — 轮询角度任务状态
- `POST   /api/angle/generate`     — 生成角度图

设计对齐 `app/api/routers/storage_files.py` pattern：
- **不 `import main`**：全部端点通过 `create_router(...)` 参数注入回调。
- 使用 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    poll_angle_cloud_cb: Callable[..., Awaitable[Any]],
    generate_angle_cloud_cb: Callable[..., Awaitable[Any]],
    cloud_poll_dto: type,
    cloud_gen_dto: type,
) -> APIRouter:
    """构造 angle 路由分组。"""

    router = APIRouter()

    # -- POST /api/angle/poll_status ----------------------------------------
    async def _poll_angle_cloud(req: cloud_poll_dto):  # type: ignore[valid-type]
        return await poll_angle_cloud_cb(req)

    _poll_angle_cloud.__annotations__["req"] = cloud_poll_dto
    router.add_api_route(
        "/api/angle/poll_status",
        _poll_angle_cloud,
        methods=["POST"],
        name="poll_angle_cloud",
    )

    # -- POST /api/angle/generate -------------------------------------------
    async def _generate_angle_cloud(req: cloud_gen_dto):  # type: ignore[valid-type]
        return await generate_angle_cloud_cb(req)

    _generate_angle_cloud.__annotations__["req"] = cloud_gen_dto
    router.add_api_route(
        "/api/angle/generate",
        _generate_angle_cloud,
        methods=["POST"],
        name="generate_angle_cloud",
    )

    return router


__all__ = ["create_router"]