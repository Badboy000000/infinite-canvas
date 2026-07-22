"""Canvas workflows router（PR-BE-06）。

抽出 `main.py` 中 `/api/canvas-workflows*` 三条路由：
- `POST /api/canvas-workflows/export`
- `POST /api/canvas-workflows/export-to-library`
- `POST /api/canvas-workflows/import`

三条路由涉及大量 helper（`build_canvas_workflow_archive` / zip 组装 /
`make_workflow_library_item_from_bytes` / `asset_library_workflow_category`
/ `canvas_workflow_replace_strings` / `shadow_register_existing_async`），
全部通过 callback 显式注入。本文件不 `import main`。
"""

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, File, UploadFile


def create_router(
    *,
    export_canvas_workflow_callback: Callable[[Any], Awaitable[Any]],
    export_canvas_workflow_to_library_callback: Callable[[Any], Awaitable[Any]],
    import_canvas_workflow_callback: Callable[[UploadFile], Awaitable[Any]],
    canvas_workflow_export_dto: type,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/canvas-workflows/export")
    async def export_canvas_workflow(payload: canvas_workflow_export_dto):  # type: ignore[valid-type]
        return await export_canvas_workflow_callback(payload)

    @router.post("/api/canvas-workflows/export-to-library")
    async def export_canvas_workflow_to_library(payload: canvas_workflow_export_dto):  # type: ignore[valid-type]
        return await export_canvas_workflow_to_library_callback(payload)

    @router.post("/api/canvas-workflows/import")
    async def import_canvas_workflow(file: UploadFile = File(...)):
        return await import_canvas_workflow_callback(file)

    return router
