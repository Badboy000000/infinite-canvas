"""Canvas assets router（PR-BE-06）。

抽出 `main.py` 中 `/api/canvas-assets*` 三条路由：
- `GET  /api/canvas-assets`
- `POST /api/canvas-assets/check`
- `POST /api/canvas-assets/download`

保活契约（任务书零触碰 · 兼容契约）：请求 / 响应 shape / 错误码 / 字段
逐字节一致。下载路由涉及多 helper（`output_file_from_url` / 远端拉取 /
zip 打包 / sanitize_export_filename），全部通过 callback 显式注入，本文
件不 `import main`。
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    list_canvas_assets_callback: Callable[[], Awaitable[Any]],
    check_canvas_assets_callback: Callable[[Any], Any],
    download_canvas_assets_callback: Callable[[Any], Awaitable[Any]],
    canvas_asset_check_dto: type,
    canvas_asset_download_dto: type,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/canvas-assets")
    async def list_canvas_assets():
        return await list_canvas_assets_callback()

    @router.post("/api/canvas-assets/check")
    async def check_canvas_assets(payload: canvas_asset_check_dto):  # type: ignore[valid-type]
        return check_canvas_assets_callback(payload)

    @router.post("/api/canvas-assets/download")
    async def download_canvas_assets(payload: canvas_asset_download_dto):  # type: ignore[valid-type]
        return await download_canvas_assets_callback(payload)

    return router
