"""Prompt libraries 路由分组（PR-BE-07 · Wave 3-N.7 Batch 1 主线 A · 候选 B 完整抽出）。

抽出 `main.py` 中 `/api/prompt-libraries*` 全部 11 条路由：
- `GET    /api/prompt-libraries`
- `POST   /api/prompt-libraries`
- `PATCH  /api/prompt-libraries/{library_id}`
- `DELETE /api/prompt-libraries/{library_id}`
- `POST   /api/prompt-libraries/items`
- `PATCH  /api/prompt-libraries/items/{item_id}`
- `DELETE /api/prompt-libraries/items/{item_id}`
- `POST   /api/prompt-libraries/items/delete`
- `POST   /api/prompt-libraries/categories`
- `PATCH  /api/prompt-libraries/categories/{category_id}`
- `DELETE /api/prompt-libraries/categories/{category_id}`

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
    get_prompt_libraries_cb: Callable[..., Awaitable[Any]],
    create_prompt_library_cb: Callable[..., Awaitable[Any]],
    rename_prompt_library_cb: Callable[..., Awaitable[Any]],
    delete_prompt_library_cb: Callable[..., Awaitable[Any]],
    add_prompt_library_item_cb: Callable[..., Awaitable[Any]],
    update_prompt_library_item_cb: Callable[..., Awaitable[Any]],
    delete_prompt_library_item_cb: Callable[..., Awaitable[Any]],
    batch_delete_prompt_library_items_cb: Callable[..., Awaitable[Any]],
    add_prompt_library_category_cb: Callable[..., Awaitable[Any]],
    rename_prompt_library_category_cb: Callable[..., Awaitable[Any]],
    delete_prompt_library_category_cb: Callable[..., Awaitable[Any]],
) -> APIRouter:
    """构造 prompt-libraries 路由分组。

    参数命名约定：`<original_handler_name>_cb` 是 `main.py` 中保留的 legacy
    函数体。回调签名保留原始 FastAPI 依赖注入标记，`add_api_route` 会正确解析。
    """

    router = APIRouter()

    # -- GET /api/prompt-libraries --------------------------------------------
    router.add_api_route(
        "/api/prompt-libraries",
        get_prompt_libraries_cb,
        methods=["GET"],
        name="get_prompt_libraries",
    )

    # -- POST /api/prompt-libraries -------------------------------------------
    router.add_api_route(
        "/api/prompt-libraries",
        create_prompt_library_cb,
        methods=["POST"],
        name="create_prompt_library",
    )

    # -- PATCH /api/prompt-libraries/{library_id} ------------------------------
    router.add_api_route(
        "/api/prompt-libraries/{library_id}",
        rename_prompt_library_cb,
        methods=["PATCH"],
        name="rename_prompt_library",
    )

    # -- DELETE /api/prompt-libraries/{library_id} -----------------------------
    router.add_api_route(
        "/api/prompt-libraries/{library_id}",
        delete_prompt_library_cb,
        methods=["DELETE"],
        name="delete_prompt_library",
    )

    # -- POST /api/prompt-libraries/items -------------------------------------
    router.add_api_route(
        "/api/prompt-libraries/items",
        add_prompt_library_item_cb,
        methods=["POST"],
        name="add_prompt_library_item",
    )

    # -- PATCH /api/prompt-libraries/items/{item_id} ---------------------------
    router.add_api_route(
        "/api/prompt-libraries/items/{item_id}",
        update_prompt_library_item_cb,
        methods=["PATCH"],
        name="update_prompt_library_item",
    )

    # -- DELETE /api/prompt-libraries/items/{item_id} --------------------------
    router.add_api_route(
        "/api/prompt-libraries/items/{item_id}",
        delete_prompt_library_item_cb,
        methods=["DELETE"],
        name="delete_prompt_library_item",
    )

    # -- POST /api/prompt-libraries/items/delete ------------------------------
    router.add_api_route(
        "/api/prompt-libraries/items/delete",
        batch_delete_prompt_library_items_cb,
        methods=["POST"],
        name="batch_delete_prompt_library_items",
    )

    # -- POST /api/prompt-libraries/categories --------------------------------
    router.add_api_route(
        "/api/prompt-libraries/categories",
        add_prompt_library_category_cb,
        methods=["POST"],
        name="add_prompt_library_category",
    )

    # -- PATCH /api/prompt-libraries/categories/{category_id} ------------------
    router.add_api_route(
        "/api/prompt-libraries/categories/{category_id}",
        rename_prompt_library_category_cb,
        methods=["PATCH"],
        name="rename_prompt_library_category",
    )

    # -- DELETE /api/prompt-libraries/categories/{category_id} -----------------
    router.add_api_route(
        "/api/prompt-libraries/categories/{category_id}",
        delete_prompt_library_category_cb,
        methods=["DELETE"],
        name="delete_prompt_library_category",
    )

    return router


__all__ = ["create_router"]