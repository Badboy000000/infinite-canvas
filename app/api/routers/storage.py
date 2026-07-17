"""Low-risk, read-only runtime configuration routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    ai_config_callback: Callable[[], Awaitable[Any]],
    ai_models_callback: Callable[[], Awaitable[Any]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/config")
    async def ai_config():
        return await ai_config_callback()

    @router.get("/api/models")
    async def ai_models():
        return await ai_models_callback()

    return router
