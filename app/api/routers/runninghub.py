"""RunningHub 路由分组（PR-BE-08 · Wave 3-N.6 Batch 2 主线 A）。

抽出 `main.py` 中 `/api/runninghub/*` 全部 12 条路由。函数体在 `main.py`
保留为 re-export 兼容层（`@app.` 装饰器剥离），本 router 通过
`router.add_api_route(...)` 用函数引用装配（"认领而非重写" pattern）。

设计原则:
- **不 `import main`**:全部端点函数通过 `create_router(...)` 参数注入。
- **不做业务级 IO**:本文件只做路由声明，业务体留在 `main.py`。
- **路由顺序断言**:`/api/runninghub/workflows/fetch` **必须在**
  `/api/runninghub/workflows/{workflow_id:path}` **之前**（GM-11 · 由本
  文件内部声明顺序保证 · 避免 `"fetch"` 被通配路径吞掉）。
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter


def create_router(
    *,
    runninghub_app_info: Callable[..., Any],
    runninghub_submit: Callable[..., Any],
    runninghub_workflow_submit: Callable[..., Any],
    runninghub_workflow_info: Callable[..., Any],
    list_runninghub_workflows: Callable[..., Any],
    fetch_runninghub_workflow: Callable[..., Any],
    get_runninghub_workflow: Callable[..., Any],
    save_runninghub_workflow: Callable[..., Any],
    delete_runninghub_workflow: Callable[..., Any],
    runninghub_query: Callable[..., Any],
    runninghub_upload_asset: Callable[..., Any],
) -> APIRouter:
    """构造 RunningHub 路由分组。

    参数刻意用 `Callable[..., Any]` 注入 —— 函数体带的 Pydantic DTO 类型
    注解由 FastAPI 直接消费，本 router 不重复建模。
    """

    router = APIRouter()

    # -- 静态路径 / 上传 前置(避免被通配吞掉) ----------------------------
    router.add_api_route(
        "/api/runninghub/app-info", runninghub_app_info, methods=["GET"]
    )
    router.add_api_route(
        "/api/runninghub/submit", runninghub_submit, methods=["POST"]
    )
    router.add_api_route(
        "/api/runninghub/workflow-submit",
        runninghub_workflow_submit,
        methods=["POST"],
    )
    router.add_api_route(
        "/api/runninghub/workflow-info",
        runninghub_workflow_info,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/runninghub/workflows",
        list_runninghub_workflows,
        methods=["GET"],
    )

    # -- workflows/fetch 前置(GM-11 · 必须在 `/workflows/{workflow_id:path}` 之前) --
    router.add_api_route(
        "/api/runninghub/workflows/fetch",
        fetch_runninghub_workflow,
        methods=["POST"],
    )

    # -- workflows/{workflow_id:path} 通配(GET / PUT / DELETE) ----------
    router.add_api_route(
        "/api/runninghub/workflows/{workflow_id:path}",
        get_runninghub_workflow,
        methods=["GET"],
    )
    router.add_api_route(
        "/api/runninghub/workflows/{workflow_id:path}",
        save_runninghub_workflow,
        methods=["PUT"],
    )
    router.add_api_route(
        "/api/runninghub/workflows/{workflow_id:path}",
        delete_runninghub_workflow,
        methods=["DELETE"],
    )

    # -- 查询 / 上传 ----------------------------------------------------
    router.add_api_route(
        "/api/runninghub/query", runninghub_query, methods=["GET"]
    )
    router.add_api_route(
        "/api/runninghub/upload-asset",
        runninghub_upload_asset,
        methods=["POST"],
    )

    return router


__all__ = ["create_router"]
