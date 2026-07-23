"""Shared folders routes (PR-BE-12 · Wave 3-N.7 Batch 4 主线 A).

Extract `main.py` 5 shared-folder routes:
- `GET    /api/shared-folders`                          — List shared folders
- `POST   /api/shared-folders`                          — Register shared folder
- `DELETE /api/shared-folders/{folder_id}`              — Unregister shared folder
- `GET    /api/shared-folders/{folder_id}/tree`         — Get folder tree
- `GET    /api/shared-folders/{folder_id}/file`         — Get file from shared folder
- `POST   /api/shared-folders/import`                   — Import files from shared folder

Design aligns with `app/api/routers/storage_files.py` pattern:
- **No `import main`**: all endpoints inject callbacks via `create_router(...)` parameters.
- Uses `add_api_route` to assemble endpoints, `name` parameter fixes `operation_id`
  to align with baseline.
- Route order: static paths (`/api/shared-folders/import`) declared before
  parameterized paths (`/api/shared-folders/{folder_id}/...`) to avoid path
  conflicts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    list_shared_folders_cb: Callable[..., Awaitable[Any]],
    register_shared_folder_cb: Callable[..., Awaitable[Any]],
    unregister_shared_folder_cb: Callable[..., Awaitable[Any]],
    get_shared_folder_tree_cb: Callable[..., Awaitable[Any]],
    get_shared_folder_file_cb: Callable[..., Awaitable[Any]],
    import_shared_folder_files_cb: Callable[..., Awaitable[Any]],
    shared_folder_register_dto: type,
    shared_folder_import_dto: type,
) -> APIRouter:
    """Construct shared-folders route group.

    Parameter naming convention: `<original_handler_name>_cb` is the legacy
    function body retained in `main.py`. Callback signatures preserve original
    FastAPI dependency injection markers; `add_api_route` resolves them correctly.
    """

    router = APIRouter()

    # -- GET /api/shared-folders -------------------------------------------------
    router.add_api_route(
        "/api/shared-folders",
        list_shared_folders_cb,
        methods=["GET"],
        name="list_shared_folders",
    )

    # -- POST /api/shared-folders ------------------------------------------------
    async def _register_shared_folder(payload: shared_folder_register_dto) -> Any:  # type: ignore[valid-type]
        return await register_shared_folder_cb(payload)

    _register_shared_folder.__annotations__["payload"] = shared_folder_register_dto
    router.add_api_route(
        "/api/shared-folders",
        _register_shared_folder,
        methods=["POST"],
        name="register_shared_folder",
    )

    # -- POST /api/shared-folders/import (static before parameterized) -----------
    async def _import_shared_folder_files(payload: shared_folder_import_dto) -> Any:  # type: ignore[valid-type]
        return await import_shared_folder_files_cb(payload)

    _import_shared_folder_files.__annotations__["payload"] = shared_folder_import_dto
    router.add_api_route(
        "/api/shared-folders/import",
        _import_shared_folder_files,
        methods=["POST"],
        name="import_shared_folder_files",
    )

    # -- DELETE /api/shared-folders/{folder_id} ----------------------------------
    router.add_api_route(
        "/api/shared-folders/{folder_id}",
        unregister_shared_folder_cb,
        methods=["DELETE"],
        name="unregister_shared_folder",
    )

    # -- GET /api/shared-folders/{folder_id}/tree --------------------------------
    router.add_api_route(
        "/api/shared-folders/{folder_id}/tree",
        get_shared_folder_tree_cb,
        methods=["GET"],
        name="get_shared_folder_tree",
    )

    # -- GET /api/shared-folders/{folder_id}/file --------------------------------
    router.add_api_route(
        "/api/shared-folders/{folder_id}/file",
        get_shared_folder_file_cb,
        methods=["GET"],
        name="get_shared_folder_file",
    )

    return router


__all__ = ["create_router"]