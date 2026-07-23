"""Generation 路由分组（PR-BE-08 · Wave 3-N.6 Batch 2 主线 A）。

抽出 `main.py` 中 provider 调用入口 / 生图 / 生视频 / 参数拉取 / 任务查
询相关的路由。函数体在 `main.py` 保留为 re-export 兼容层。

抽出范围(GM-14 pattern 优先自决 · 保守裁决):
- `POST /api/online-image`
- `POST /api/image-task-query`
- `POST /api/canvas-image-tasks`
- `GET  /api/canvas-image-tasks/{task_id}`
- `POST /api/canvas-comfy-tasks`
- `GET  /api/canvas-comfy-tasks/{task_id}`
- `GET  /api/image-params`
- `POST /api/canvas-video`

**不抽出**(保守 · 后续 PR 处理):
- `POST /api/generate` / `POST /generate` / `POST /api/ms/generate`(1000+
  行函数 · 多分支 heavy 耦合 · 单独 PR 处理更安全)
- `POST /api/canvas-llm`(chat 语义 · 不属 provider 调用入口的图/视频域)
- `POST /api/angle/generate` / `POST /api/angle/poll_status`(angle 域不属
  provider 域)

设计原则:
- **不 `import main`**:全部端点函数通过 `create_router(...)` 参数注入。
- **路径优先声明**:`/api/canvas-image-tasks/{task_id}` 在
  `/api/canvas-image-tasks` 之后声明是安全的(POST vs GET · 无路径歧义)·
  但 FastAPI 按顺序匹配 · 保持源代码可读顺序。
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter


def create_router(
    *,
    online_image: Callable[..., Any],
    query_image_task: Callable[..., Any],
    create_canvas_image_task: Callable[..., Any],
    get_canvas_image_task: Callable[..., Any],
    create_canvas_comfy_task: Callable[..., Any],
    get_canvas_comfy_task: Callable[..., Any],
    image_params: Callable[..., Any],
    canvas_video: Callable[..., Any],
) -> APIRouter:
    """构造生图 / 生视频路由分组。"""

    router = APIRouter()

    # -- 生图入口 / 结果查询 --
    router.add_api_route(
        "/api/online-image", online_image, methods=["POST"]
    )
    router.add_api_route(
        "/api/image-task-query", query_image_task, methods=["POST"]
    )

    # -- Canvas 图像任务(create + get_by_id) --
    router.add_api_route(
        "/api/canvas-image-tasks", create_canvas_image_task, methods=["POST"]
    )
    router.add_api_route(
        "/api/canvas-image-tasks/{task_id}",
        get_canvas_image_task,
        methods=["GET"],
    )

    # -- Canvas Comfy 任务(create + get_by_id) --
    router.add_api_route(
        "/api/canvas-comfy-tasks", create_canvas_comfy_task, methods=["POST"]
    )
    router.add_api_route(
        "/api/canvas-comfy-tasks/{task_id}",
        get_canvas_comfy_task,
        methods=["GET"],
    )

    # -- 图像参数拉取 --
    router.add_api_route(
        "/api/image-params", image_params, methods=["GET"]
    )

    # -- 视频生成 --
    router.add_api_route(
        "/api/canvas-video", canvas_video, methods=["POST"]
    )

    return router


__all__ = ["create_router"]
