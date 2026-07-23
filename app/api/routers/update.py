"""Update / connectivity 路由分组（PR-BE-11 · Wave 3-N.7 Batch 3 主线 A）。

抽出 `main.py` 中 6 更新路由：
- `GET    /api/update-connectivity/probe`  — 单目标连通性检测
- `GET    /api/update-connectivity`         — 全量连通性检测
- `GET    /api/check-update`                — 版本检测
- `POST   /api/update-from-github`          — 更新应用
- `GET    /api/update-backups`              — 备份列表
- `POST   /api/update-rollback`             — 回滚

设计对齐 `app/api/routers/storage_files.py` pattern：
- **不 `import main`**：全部端点通过 `create_router(...)` 参数注入回调。
- 使用 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    update_connectivity_probe_cb: Callable[..., Any],
    update_connectivity_cb: Callable[..., Any],
    check_update_cb: Callable[..., Any],
    update_from_github_cb: Callable[..., Any],
    get_update_backups_cb: Callable[..., Any],
    rollback_update_cb: Callable[..., Any],
    update_request_dto: type,
    rollback_request_dto: type,
) -> APIRouter:
    """构造 update / connectivity 路由分组。

    参数命名约定：`<original_handler_name>_cb` 是 `main.py` 中保留的 legacy
    函数体。回调签名保留原始 FastAPI 依赖注入标记，`add_api_route` 会正确解析。
    """

    router = APIRouter()

    # -- GET /api/update-connectivity/probe ---------------------------------
    router.add_api_route(
        "/api/update-connectivity/probe",
        update_connectivity_probe_cb,
        methods=["GET"],
        name="update_connectivity_probe",
    )

    # -- GET /api/update-connectivity ---------------------------------------
    router.add_api_route(
        "/api/update-connectivity",
        update_connectivity_cb,
        methods=["GET"],
        name="update_connectivity",
    )

    # -- GET /api/check-update ----------------------------------------------
    router.add_api_route(
        "/api/check-update",
        check_update_cb,
        methods=["GET"],
        name="check_update",
    )

    # -- POST /api/update-from-github ---------------------------------------
    async def _update_from_github(req: update_request_dto):  # type: ignore[valid-type]
        return await update_from_github_cb(req)

    _update_from_github.__annotations__["req"] = update_request_dto
    router.add_api_route(
        "/api/update-from-github",
        _update_from_github,
        methods=["POST"],
        name="update_from_github",
    )

    # -- GET /api/update-backups --------------------------------------------
    router.add_api_route(
        "/api/update-backups",
        get_update_backups_cb,
        methods=["GET"],
        name="get_update_backups",
    )

    # -- POST /api/update-rollback ------------------------------------------
    async def _rollback_update(req: rollback_request_dto):  # type: ignore[valid-type]
        return await rollback_update_cb(req)

    _rollback_update.__annotations__["req"] = rollback_request_dto
    router.add_api_route(
        "/api/update-rollback",
        _rollback_update,
        methods=["POST"],
        name="rollback_update",
    )

    return router


__all__ = ["create_router"]