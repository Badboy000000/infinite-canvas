"""Low-risk, read-only workflow routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def create_router(list_workflows_callback: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    @router.get("/api/workflows")
    def list_workflows():
        return list_workflows_callback()

    return router
