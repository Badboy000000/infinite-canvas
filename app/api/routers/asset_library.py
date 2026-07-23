"""Asset library 路由分组（PR-BE-07 · Wave 3-N.7 Batch 1 主线 A · 候选 B 完整抽出）。

抽出 `main.py` 中 `/api/asset-library*` 全部 18 条路由：
- `POST   /api/asset-library/workflows/upload`
- `GET    /api/asset-library`
- `POST   /api/asset-library/libraries`
- `PATCH  /api/asset-library/libraries/{library_id}`
- `DELETE /api/asset-library/libraries/{library_id}`
- `POST   /api/asset-library/categories`
- `PATCH  /api/asset-library/categories/{category_id}`
- `DELETE /api/asset-library/categories/{category_id}`
- `POST   /api/asset-library/items`
- `POST   /api/asset-library/items/batch`
- `PATCH  /api/asset-library/items/{item_id}`
- `POST   /api/asset-library/items/classify`
- `POST   /api/asset-library/items/{item_id}/register-avatar`
- `POST   /api/asset-library/items/{item_id}/avatar-status`
- `DELETE /api/asset-library/items/{item_id}`
- `POST   /api/asset-library/items/delete`
- `POST   /api/asset-library/items/move`
- `POST   /api/asset-library/items/crop`

设计（对齐 PR-BE-09 canvas_tasks.py pattern）：
- **不 `import main`**：全部端点通过 `create_router(...)` 参数注入回调。
- 回调是 `main.py` 中保留的 legacy 函数体（`@app.` 装饰器已剥离）。
- 使用 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    upload_asset_library_workflows_cb: Callable[..., Awaitable[Any]],
    get_asset_library_cb: Callable[..., Awaitable[Any]],
    create_asset_library_cb: Callable[..., Awaitable[Any]],
    rename_asset_library_cb: Callable[..., Awaitable[Any]],
    delete_asset_library_cb: Callable[..., Awaitable[Any]],
    create_asset_library_category_cb: Callable[..., Awaitable[Any]],
    rename_asset_library_category_cb: Callable[..., Awaitable[Any]],
    delete_asset_library_category_cb: Callable[..., Awaitable[Any]],
    add_asset_library_item_cb: Callable[..., Awaitable[Any]],
    batch_add_asset_library_items_cb: Callable[..., Awaitable[Any]],
    rename_asset_library_item_cb: Callable[..., Awaitable[Any]],
    classify_asset_library_items_cb: Callable[..., Awaitable[Any]],
    register_asset_library_avatar_cb: Callable[..., Awaitable[Any]],
    check_asset_library_avatar_cb: Callable[..., Awaitable[Any]],
    delete_asset_library_item_cb: Callable[..., Awaitable[Any]],
    batch_delete_asset_library_items_cb: Callable[..., Awaitable[Any]],
    batch_move_asset_library_items_cb: Callable[..., Awaitable[Any]],
    batch_crop_asset_library_items_cb: Callable[..., Awaitable[Any]],
) -> APIRouter:
    """构造 asset-library 路由分组。

    参数命名约定：`<original_handler_name>_cb` 是 `main.py` 中保留的 legacy
    函数体。回调签名保留原始 FastAPI 依赖注入标记，`add_api_route` 会正确解析。
    """

    router = APIRouter()

    # -- POST /api/asset-library/workflows/upload (multipart) ----------------
    router.add_api_route(
        "/api/asset-library/workflows/upload",
        upload_asset_library_workflows_cb,
        methods=["POST"],
        name="upload_asset_library_workflows",
    )

    # -- GET /api/asset-library ----------------------------------------------
    router.add_api_route(
        "/api/asset-library",
        get_asset_library_cb,
        methods=["GET"],
        name="get_asset_library",
    )

    # -- POST /api/asset-library/libraries -----------------------------------
    router.add_api_route(
        "/api/asset-library/libraries",
        create_asset_library_cb,
        methods=["POST"],
        name="create_asset_library",
    )

    # -- PATCH /api/asset-library/libraries/{library_id} ----------------------
    router.add_api_route(
        "/api/asset-library/libraries/{library_id}",
        rename_asset_library_cb,
        methods=["PATCH"],
        name="rename_asset_library",
    )

    # -- DELETE /api/asset-library/libraries/{library_id} ---------------------
    router.add_api_route(
        "/api/asset-library/libraries/{library_id}",
        delete_asset_library_cb,
        methods=["DELETE"],
        name="delete_asset_library",
    )

    # -- POST /api/asset-library/categories ----------------------------------
    router.add_api_route(
        "/api/asset-library/categories",
        create_asset_library_category_cb,
        methods=["POST"],
        name="create_asset_library_category",
    )

    # -- PATCH /api/asset-library/categories/{category_id} --------------------
    router.add_api_route(
        "/api/asset-library/categories/{category_id}",
        rename_asset_library_category_cb,
        methods=["PATCH"],
        name="rename_asset_library_category",
    )

    # -- DELETE /api/asset-library/categories/{category_id} -------------------
    router.add_api_route(
        "/api/asset-library/categories/{category_id}",
        delete_asset_library_category_cb,
        methods=["DELETE"],
        name="delete_asset_library_category",
    )

    # -- POST /api/asset-library/items ---------------------------------------
    router.add_api_route(
        "/api/asset-library/items",
        add_asset_library_item_cb,
        methods=["POST"],
        name="add_asset_library_item",
    )

    # -- POST /api/asset-library/items/batch ---------------------------------
    router.add_api_route(
        "/api/asset-library/items/batch",
        batch_add_asset_library_items_cb,
        methods=["POST"],
        name="batch_add_asset_library_items",
    )

    # -- PATCH /api/asset-library/items/{item_id} -----------------------------
    router.add_api_route(
        "/api/asset-library/items/{item_id}",
        rename_asset_library_item_cb,
        methods=["PATCH"],
        name="rename_asset_library_item",
    )

    # -- POST /api/asset-library/items/classify ------------------------------
    router.add_api_route(
        "/api/asset-library/items/classify",
        classify_asset_library_items_cb,
        methods=["POST"],
        name="classify_asset_library_items",
    )

    # -- POST /api/asset-library/items/{item_id}/register-avatar -------------
    router.add_api_route(
        "/api/asset-library/items/{item_id}/register-avatar",
        register_asset_library_avatar_cb,
        methods=["POST"],
        name="register_asset_library_avatar",
    )

    # -- POST /api/asset-library/items/{item_id}/avatar-status ---------------
    router.add_api_route(
        "/api/asset-library/items/{item_id}/avatar-status",
        check_asset_library_avatar_cb,
        methods=["POST"],
        name="check_asset_library_avatar",
    )

    # -- DELETE /api/asset-library/items/{item_id} ----------------------------
    router.add_api_route(
        "/api/asset-library/items/{item_id}",
        delete_asset_library_item_cb,
        methods=["DELETE"],
        name="delete_asset_library_item",
    )

    # -- POST /api/asset-library/items/delete --------------------------------
    router.add_api_route(
        "/api/asset-library/items/delete",
        batch_delete_asset_library_items_cb,
        methods=["POST"],
        name="batch_delete_asset_library_items",
    )

    # -- POST /api/asset-library/items/move ----------------------------------
    router.add_api_route(
        "/api/asset-library/items/move",
        batch_move_asset_library_items_cb,
        methods=["POST"],
        name="batch_move_asset_library_items",
    )

    # -- POST /api/asset-library/items/crop ----------------------------------
    router.add_api_route(
        "/api/asset-library/items/crop",
        batch_crop_asset_library_items_cb,
        methods=["POST"],
        name="batch_crop_asset_library_items",
    )

    return router


__all__ = ["create_router"]