"""ComfyUI 路由分组（PR-BE-11 · Wave 3-N.7 Batch 3 主线 A）。

抽出 `main.py` 中 3 ComfyUI 路由：
- `GET    /api/comfyui/instances`        — 实例列表
- `POST   /api/comfyui/upload-base64`    — base64 上传
- `PUT    /api/comfyui/instances`        — 保存实例

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
    get_instances_callback: Callable[[], Any],
    *,
    upload_comfyui_base64_cb: Callable[..., Awaitable[Any]] | None = None,
    save_comfyui_instances_cb: Callable[..., Any] | None = None,
    base64_upload_dto: type | None = None,
    comfy_instances_dto: type | None = None,
) -> APIRouter:
    """构造 ComfyUI 路由分组。

    向后兼容：原有 `create_router(get_instances_callback)` 单参数签名仍然
    可用（新参数为关键字可选）。PR-BE-11 追加的 2 路由通过关键字参数注入。
    """

    router = APIRouter()

    # -- GET /api/comfyui/instances -----------------------------------------
    @router.get("/api/comfyui/instances")
    def get_comfyui_instances():
        return get_instances_callback()

    # -- POST /api/comfyui/upload-base64 (PR-BE-11) -------------------------
    if upload_comfyui_base64_cb is not None and base64_upload_dto is not None:

        async def _upload_comfyui_base64(payload: base64_upload_dto):  # type: ignore[valid-type]
            return await upload_comfyui_base64_cb(payload)

        _upload_comfyui_base64.__annotations__["payload"] = base64_upload_dto
        router.add_api_route(
            "/api/comfyui/upload-base64",
            _upload_comfyui_base64,
            methods=["POST"],
            name="upload_comfyui_base64",
        )

    # -- PUT /api/comfyui/instances (PR-BE-11) ------------------------------
    if save_comfyui_instances_cb is not None and comfy_instances_dto is not None:

        async def _save_comfyui_instances(payload: comfy_instances_dto):  # type: ignore[valid-type]
            return await save_comfyui_instances_cb(payload)

        _save_comfyui_instances.__annotations__["payload"] = comfy_instances_dto
        router.add_api_route(
            "/api/comfyui/instances",
            _save_comfyui_instances,
            methods=["PUT"],
            name="save_comfyui_instances",
        )

    return router
