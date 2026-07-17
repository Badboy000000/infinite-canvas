"""Low-risk, read-only system routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def create_router(app_info_callback: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/app-info")
    def app_info():
        return app_info_callback()

    return router
