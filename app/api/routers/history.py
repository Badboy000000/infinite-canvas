"""Low-risk, read-only history routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    get_history_callback: Callable[[str | None], Awaitable[Any]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/history")
    async def get_history_api(type: str = None):
        return await get_history_callback(type)

    return router
