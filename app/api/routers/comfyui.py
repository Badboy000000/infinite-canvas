"""Low-risk, read-only ComfyUI routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def create_router(get_instances_callback: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/comfyui/instances")
    def get_comfyui_instances():
        return get_instances_callback()

    return router
