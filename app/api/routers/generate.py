"""Generate / ModelScope cloud generation routes (PR-BE-12 · Wave 3-N.7 Batch 4 主线 A).

Extract `main.py` 3 generate routes:
- `POST   /generate`              — ModelScope Z-Image cloud generation
- `POST   /api/ms/generate`       — ModelScope general image generation
- `POST   /api/generate`          — Local ComfyUI generation

Design aligns with `app/api/routers/angle.py` pattern:
- **No `import main`**: all endpoints inject callbacks via `create_router(...)` parameters.
- Uses `add_api_route` to assemble endpoints, `name` parameter fixes `operation_id`
  to align with baseline.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    *,
    generate_cloud_cb: Callable[..., Awaitable[Any]],
    ms_generate_cb: Callable[..., Awaitable[Any]],
    generate_cb: Callable[..., Any],
    cloud_gen_dto: type,
    ms_generate_dto: type,
    generate_dto: type,
) -> APIRouter:
    """Construct generate / cloud generation route group.

    Parameter naming convention: `<original_handler_name>_cb` is the legacy
    function body retained in `main.py`. Callback signatures preserve original
    FastAPI dependency injection markers; `add_api_route` resolves them correctly.
    """

    router = APIRouter()

    # -- POST /generate (ModelScope Z-Image) ------------------------------------
    async def _generate_cloud(req: cloud_gen_dto) -> Any:  # type: ignore[valid-type]
        return await generate_cloud_cb(req)

    _generate_cloud.__annotations__["req"] = cloud_gen_dto
    router.add_api_route(
        "/generate",
        _generate_cloud,
        methods=["POST"],
        name="generate_cloud",
    )

    # -- POST /api/ms/generate (ModelScope general) -----------------------------
    async def _ms_generate(req: ms_generate_dto) -> Any:  # type: ignore[valid-type]
        return await ms_generate_cb(req)

    _ms_generate.__annotations__["req"] = ms_generate_dto
    router.add_api_route(
        "/api/ms/generate",
        _ms_generate,
        methods=["POST"],
        name="ms_generate",
    )

    # -- POST /api/generate (local ComfyUI) -------------------------------------
    def _generate(req: generate_dto) -> Any:  # type: ignore[valid-type]
        return generate_cb(req)

    _generate.__annotations__["req"] = generate_dto
    router.add_api_route(
        "/api/generate",
        _generate,
        methods=["POST"],
        name="generate",
    )

    return router


__all__ = ["create_router"]