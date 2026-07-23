"""Local assets 路由分组（PR-BE-07 · Wave 3-N.7 Batch 1 主线 A · 候选 B 完整抽出）。

抽出 `main.py` 中 `/api/local-assets*` 全部 11 条路由：
- `POST   /api/local-assets/upload`
- `POST   /api/local-assets/import-urls`
- `GET    /api/local-assets`
- `POST   /api/local-assets/folders`
- `PATCH  /api/local-assets/folders`
- `PATCH  /api/local-assets/items`
- `POST   /api/local-assets/delete`
- `POST   /api/local-assets/move`
- `POST   /api/local-assets/caption`
- `POST   /api/local-assets/classify`
- `PATCH  /api/local-assets/caption`

设计（对齐 PR-BE-09 canvas_tasks.py pattern）：
- **不 `import main`**：全部端点通过 `create_router(...)` 参数注入回调。
- 回调是 `main.py` 中保留的 legacy 函数体（`@app.` 装饰器已剥离），回调签名
  保留原始 FastAPI 依赖注入标记（`File()` / `Form()` / `Header()` / `Request`）。
- 使用 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐。

**P0 密钥零入库防线**：upload / import-urls / caption / classify 端点入参
可能透传 provider api_key / secret 字段；回调层不落地 log / 不落地 dict 副
本；sanitize 断言仅在测试路径（T443）消费。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request


def create_router(
    *,
    upload_local_assets_cb: Callable[..., Awaitable[Any]],
    import_local_assets_from_urls_cb: Callable[..., Awaitable[Any]],
    list_local_assets_cb: Callable[..., Awaitable[Any]],
    create_local_asset_folder_cb: Callable[..., Awaitable[Any]],
    rename_local_asset_folder_cb: Callable[..., Awaitable[Any]],
    rename_local_asset_item_cb: Callable[..., Awaitable[Any]],
    delete_local_assets_cb: Callable[..., Awaitable[Any]],
    move_local_assets_cb: Callable[..., Awaitable[Any]],
    caption_local_assets_cb: Callable[..., Awaitable[Any]],
    classify_local_assets_cb: Callable[..., Awaitable[Any]],
    save_local_asset_caption_cb: Callable[..., Awaitable[Any]],
) -> APIRouter:
    """构造 local-assets 路由分组。

    参数命名约定：`<original_handler_name>_cb` 是 `main.py` 中保留的 legacy
    函数体。回调签名保留原始 FastAPI 依赖注入标记（`File()` / `Form()` /
    `Request` 等），`add_api_route` 会正确解析。
    """

    router = APIRouter()

    # -- POST /api/local-assets/upload (multipart) ---------------------------
    router.add_api_route(
        "/api/local-assets/upload",
        upload_local_assets_cb,
        methods=["POST"],
        name="upload_local_assets",
    )

    # -- POST /api/local-assets/import-urls ----------------------------------
    router.add_api_route(
        "/api/local-assets/import-urls",
        import_local_assets_from_urls_cb,
        methods=["POST"],
        name="import_local_assets_from_urls",
    )

    # -- GET /api/local-assets ------------------------------------------------
    router.add_api_route(
        "/api/local-assets",
        list_local_assets_cb,
        methods=["GET"],
        name="list_local_assets",
    )

    # -- POST /api/local-assets/folders ---------------------------------------
    router.add_api_route(
        "/api/local-assets/folders",
        create_local_asset_folder_cb,
        methods=["POST"],
        name="create_local_asset_folder",
    )

    # -- PATCH /api/local-assets/folders --------------------------------------
    router.add_api_route(
        "/api/local-assets/folders",
        rename_local_asset_folder_cb,
        methods=["PATCH"],
        name="rename_local_asset_folder",
    )

    # -- PATCH /api/local-assets/items ----------------------------------------
    router.add_api_route(
        "/api/local-assets/items",
        rename_local_asset_item_cb,
        methods=["PATCH"],
        name="rename_local_asset_item",
    )

    # -- POST /api/local-assets/delete ----------------------------------------
    router.add_api_route(
        "/api/local-assets/delete",
        delete_local_assets_cb,
        methods=["POST"],
        name="delete_local_assets",
    )

    # -- POST /api/local-assets/move ------------------------------------------
    router.add_api_route(
        "/api/local-assets/move",
        move_local_assets_cb,
        methods=["POST"],
        name="move_local_assets",
    )

    # -- POST /api/local-assets/caption ---------------------------------------
    router.add_api_route(
        "/api/local-assets/caption",
        caption_local_assets_cb,
        methods=["POST"],
        name="caption_local_assets",
    )

    # -- POST /api/local-assets/classify --------------------------------------
    router.add_api_route(
        "/api/local-assets/classify",
        classify_local_assets_cb,
        methods=["POST"],
        name="classify_local_assets",
    )

    # -- PATCH /api/local-assets/caption --------------------------------------
    router.add_api_route(
        "/api/local-assets/caption",
        save_local_asset_caption_cb,
        methods=["PATCH"],
        name="save_local_asset_caption",
    )

    return router


__all__ = ["create_router"]