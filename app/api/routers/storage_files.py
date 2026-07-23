"""Storage files 路由分组（PR-BE-10 · Wave 3-N.7 Batch 2 主线 A）。

抽出 `main.py` 中 6 文件路由：
- `GET    /api/storage-files`                                   — 列表
- `GET    /api/storage-files/{kind}/{rel_path:path}`            — 单文件
- `POST   /api/storage-files/delete`                            — 删除
- `GET    /api/media-preview`                                   — 媒体预览
- `GET    /api/view`                                            — ComfyUI 视图代理
- `GET    /api/download-output`                                 — 文件下载

设计（对齐 PR-BE-07 asset_library.py / PR-BE-09 canvas_tasks.py pattern）：
- **不 `import main`**：全部端点通过 `create_router(...)` 参数注入回调。
- 回调是 `main.py` 中保留的 legacy 函数体（`@app.` 装饰器已剥离）。
- 使用 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐。
- 路由顺序：`/api/storage-files`（静态）优先于 `/api/storage-files/{kind}/{rel_path:path}`
  （参数化），由本文件内部 `add_api_route` 声明顺序保证。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Request


def create_router(
    *,
    list_storage_files_cb: Callable[..., Awaitable[Any]],
    get_storage_file_cb: Callable[..., Awaitable[Any]],
    delete_storage_files_cb: Callable[..., Awaitable[Any]],
    media_preview_cb: Callable[..., Awaitable[Any]],
    view_image_cb: Callable[..., Any],
    download_output_cb: Callable[..., Any],
) -> APIRouter:
    """构造 storage-files / media-preview / view / download-output 路由分组。

    参数命名约定：`<original_handler_name>_cb` 是 `main.py` 中保留的 legacy
    函数体。回调签名保留原始 FastAPI 依赖注入标记，`add_api_route` 会正确解析。
    """

    router = APIRouter()

    # -- GET /api/storage-files (顺序敏感：静态优先于参数化) --------------------
    router.add_api_route(
        "/api/storage-files",
        list_storage_files_cb,
        methods=["GET"],
        name="list_storage_files",
    )

    # -- GET /api/storage-files/{kind}/{rel_path:path} -------------------------
    router.add_api_route(
        "/api/storage-files/{kind}/{rel_path:path}",
        get_storage_file_cb,
        methods=["GET"],
        name="get_storage_file",
    )

    # -- POST /api/storage-files/delete ---------------------------------------
    router.add_api_route(
        "/api/storage-files/delete",
        delete_storage_files_cb,
        methods=["POST"],
        name="delete_storage_files",
    )

    # -- GET /api/media-preview ------------------------------------------------
    router.add_api_route(
        "/api/media-preview",
        media_preview_cb,
        methods=["GET"],
        name="media_preview",
    )

    # -- GET /api/view ---------------------------------------------------------
    router.add_api_route(
        "/api/view",
        view_image_cb,
        methods=["GET"],
        name="view_image",
    )

    # -- GET /api/download-output ----------------------------------------------
    router.add_api_route(
        "/api/download-output",
        download_output_cb,
        methods=["GET"],
        name="download_output",
    )

    return router


__all__ = ["create_router"]