"""Workflow 路由分组（PR-BE-11 · Wave 3-N.7 Batch 3 主线 A）。

抽出 `main.py` 中 7 工作流路由：
- `GET    /api/workflows`                    — 列表
- `GET    /api/workflows/{name:path}`        — 单工作流
- `POST   /api/workflows`                    — 上传
- `PUT    /api/workflows/{name:path}/config` — 保存配置
- `DELETE /api/workflows/{name:path}`        — 删除
- `POST   /api/workflows/{name:path}/run`    — 运行
- `GET    /api/config/token`                 — 全局 token

设计对齐 `app/api/routers/storage_files.py` pattern：
- **不 `import main`**：全部端点通过 `create_router(...)` 参数注入回调。
- 使用 `add_api_route` 装配端点，`name` 参数固定 `operation_id` 与 baseline
  完全对齐。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter


def create_router(
    list_workflows_callback: Callable[[], Any],
    *,
    get_workflow_cb: Callable[..., Any] | None = None,
    upload_workflow_cb: Callable[..., Any] | None = None,
    save_workflow_config_cb: Callable[..., Any] | None = None,
    delete_workflow_cb: Callable[..., Any] | None = None,
    run_workflow_cb: Callable[..., Any] | None = None,
    get_global_token_cb: Callable[..., Awaitable[Any]] | None = None,
    workflow_upload_dto: type | None = None,
    workflow_config_dto: type | None = None,
    workflow_run_dto: type | None = None,
) -> APIRouter:
    """构造 workflow 路由分组。

    向后兼容：原有 `create_router(list_workflows_callback)` 单参数签名仍然
    可用（新参数为关键字可选）。PR-BE-11 追加的 6 路由通过关键字参数注入。
    """

    router = APIRouter()

    # -- GET /api/workflows --------------------------------------------------
    @router.get("/api/workflows")
    def list_workflows():
        return list_workflows_callback()

    # -- GET /api/workflows/{name:path} (PR-BE-11) --------------------------
    if get_workflow_cb is not None:
        router.add_api_route(
            "/api/workflows/{name:path}",
            get_workflow_cb,
            methods=["GET"],
            name="get_workflow",
        )

    # -- POST /api/workflows (PR-BE-11) -------------------------------------
    if upload_workflow_cb is not None and workflow_upload_dto is not None:

        async def _upload_workflow(payload: workflow_upload_dto):  # type: ignore[valid-type]
            return await upload_workflow_cb(payload)

        _upload_workflow.__annotations__["payload"] = workflow_upload_dto
        router.add_api_route(
            "/api/workflows",
            _upload_workflow,
            methods=["POST"],
            name="upload_workflow",
        )

    # -- PUT /api/workflows/{name:path}/config (PR-BE-11) --------------------
    if save_workflow_config_cb is not None and workflow_config_dto is not None:

        async def _save_workflow_config(name: str, payload: workflow_config_dto):  # type: ignore[valid-type]
            return await save_workflow_config_cb(name, payload)

        _save_workflow_config.__annotations__["payload"] = workflow_config_dto
        router.add_api_route(
            "/api/workflows/{name:path}/config",
            _save_workflow_config,
            methods=["PUT"],
            name="save_workflow_config",
        )

    # -- DELETE /api/workflows/{name:path} (PR-BE-11) -----------------------
    if delete_workflow_cb is not None:
        router.add_api_route(
            "/api/workflows/{name:path}",
            delete_workflow_cb,
            methods=["DELETE"],
            name="delete_workflow",
        )

    # -- POST /api/workflows/{name:path}/run (PR-BE-11) ---------------------
    if run_workflow_cb is not None and workflow_run_dto is not None:

        async def _run_workflow(name: str, payload: workflow_run_dto):  # type: ignore[valid-type]
            return await run_workflow_cb(name, payload)

        _run_workflow.__annotations__["payload"] = workflow_run_dto
        router.add_api_route(
            "/api/workflows/{name:path}/run",
            _run_workflow,
            methods=["POST"],
            name="run_workflow",
        )

    # -- GET /api/config/token (PR-BE-11) ------------------------------------
    if get_global_token_cb is not None:
        router.add_api_route(
            "/api/config/token",
            get_global_token_cb,
            methods=["GET"],
            name="get_global_token",
        )

    return router
