"""Canvas LLM routes (PR-BE-12 · Wave 3-N.7 Batch 4 主线 A).

Extract `main.py` 1 canvas-llm route:
- `POST   /api/canvas-llm`  — Canvas LLM chat completion

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
    canvas_llm_cb: Callable[..., Awaitable[Any]],
    canvas_llm_dto: type,
) -> APIRouter:
    """Construct canvas-llm route group.

    Parameter naming convention: `<original_handler_name>_cb` is the legacy
    function body retained in `main.py`. Callback signatures preserve original
    FastAPI dependency injection markers; `add_api_route` resolves them correctly.
    """

    router = APIRouter()

    # -- POST /api/canvas-llm ----------------------------------------------------
    async def _canvas_llm(payload: canvas_llm_dto) -> Any:  # type: ignore[valid-type]
        return await canvas_llm_cb(payload)

    _canvas_llm.__annotations__["payload"] = canvas_llm_dto
    router.add_api_route(
        "/api/canvas-llm",
        _canvas_llm,
        methods=["POST"],
        name="canvas_llm",
    )

    return router


__all__ = ["create_router"]