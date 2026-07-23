"""Smart Canvas routes (PR-BE-12 · Wave 3-N.7 Batch 4 主线 A).

Extract `main.py` 2 smart-canvas routes:
- `GET    /api/smart-canvas/prompt-templates`  — List prompt templates
- `POST   /api/smart-canvas/group-export`      — Export smart canvas group

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
    prompt_templates_cb: Callable[..., Awaitable[Any]],
    group_export_cb: Callable[..., Awaitable[Any]],
    group_export_dto: type,
) -> APIRouter:
    """Construct smart-canvas route group.

    Parameter naming convention: `<original_handler_name>_cb` is the legacy
    function body retained in `main.py`. Callback signatures preserve original
    FastAPI dependency injection markers; `add_api_route` resolves them correctly.
    """

    router = APIRouter()

    # -- GET /api/smart-canvas/prompt-templates ----------------------------------
    router.add_api_route(
        "/api/smart-canvas/prompt-templates",
        prompt_templates_cb,
        methods=["GET"],
        name="smart_canvas_prompt_templates",
    )

    # -- POST /api/smart-canvas/group-export -------------------------------------
    async def _export_smart_canvas_group(payload: group_export_dto) -> Any:  # type: ignore[valid-type]
        return await group_export_cb(payload)

    _export_smart_canvas_group.__annotations__["payload"] = group_export_dto
    router.add_api_route(
        "/api/smart-canvas/group-export",
        _export_smart_canvas_group,
        methods=["POST"],
        name="export_smart_canvas_group",
    )

    return router


__all__ = ["create_router"]