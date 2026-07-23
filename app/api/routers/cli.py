"""CLI 路由分组（PR-BE-08 · Wave 3-N.6 Batch 2 主线 A）。

抽出 `main.py` 中 CLI provider(codex / gemini-cli / jimeng) 相关的 12 条
路由。函数体在 `main.py` 保留为 re-export 兼容层。

设计原则:
- **不 `import main`**:全部端点函数通过 `create_router(...)` 参数注入。
- **`/api/jimeng/login/status`** 必须在 `/api/jimeng/login/start` 之后
  声明(FastAPI 精确匹配 · 无路径参数冲突 · 无 GM-11 风险 · 但保持代码
  可读顺序一致)。
- CLI 是 provider 特殊形态：`is_codex_provider()` / `is_gemini_cli_provider()`
  等 legacy 分支硬约束保留在 `main.py`(本 router 不重实现)。
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter


def create_router(
    *,
    codex_status: Callable[..., Any],
    codex_help: Callable[..., Any],
    gemini_cli_status: Callable[..., Any],
    gemini_cli_help: Callable[..., Any],
    jimeng_status: Callable[..., Any],
    jimeng_credit: Callable[..., Any],
    jimeng_logout: Callable[..., Any],
    jimeng_login_start: Callable[..., Any],
    jimeng_login_status: Callable[..., Any],
    jimeng_help: Callable[..., Any],
    jimeng_query_media: Callable[..., Any],
) -> APIRouter:
    """构造 CLI 路由分组。"""

    router = APIRouter()

    # -- codex --
    router.add_api_route(
        "/api/codex/status", codex_status, methods=["GET"]
    )
    router.add_api_route(
        "/api/codex/help", codex_help, methods=["POST"]
    )

    # -- gemini-cli --
    router.add_api_route(
        "/api/gemini-cli/status", gemini_cli_status, methods=["GET"]
    )
    router.add_api_route(
        "/api/gemini-cli/help", gemini_cli_help, methods=["POST"]
    )

    # -- jimeng --
    router.add_api_route(
        "/api/jimeng/status", jimeng_status, methods=["GET"]
    )
    router.add_api_route(
        "/api/jimeng/credit", jimeng_credit, methods=["GET"]
    )
    router.add_api_route(
        "/api/jimeng/logout", jimeng_logout, methods=["POST"]
    )
    router.add_api_route(
        "/api/jimeng/login/start", jimeng_login_start, methods=["POST"]
    )
    router.add_api_route(
        "/api/jimeng/login/status", jimeng_login_status, methods=["GET"]
    )
    router.add_api_route(
        "/api/jimeng/help", jimeng_help, methods=["POST"]
    )
    router.add_api_route(
        "/api/jimeng/query-media", jimeng_query_media, methods=["POST"]
    )

    return router


__all__ = ["create_router"]
