"""Canvas 领域 router（PR-BE-06 · Wave 3-L 主线 B）。

抽出 `main.py` 中 `/api/canvases*` 全部 10 条路由。设计与 PR-BE-05 保持
一致：
- **不 `import main`**：DTO 类型与所有跨模块 helper 通过 `create_router`
  的显式参数注入。
- 路由函数体极薄：命令对象组装 → 调用 `CanvasService` 方法 → 装配响应。
- Router include 顺序：`/api/canvases/trash` 优先于 `/api/canvases/{canvas_id}`
  （GM-11 · 由本文件内部路由声明顺序保证）。
"""

from typing import Any

from fastapi import APIRouter

from app.modules.canvas.commands import (
    CanvasCreateCommand,
    CanvasIdCommand,
    CanvasMetaPatchCommand,
    CanvasSaveCommand,
)
from app.modules.canvas.service import CanvasService


def create_router(
    *,
    service: CanvasService,
    canvas_create_dto: type,
    canvas_meta_update_dto: type,
    canvas_save_dto: type,
) -> APIRouter:
    """构造 canvas 路由分组。

    参数刻意用 `type` 注入 DTO —— DTO 定义仍留在 `main.py`（任务书零触
    碰事实清单第 1/5 项），本模块只负责路由声明。
    """

    router = APIRouter()

    # ---- 集合 / 元信息 --------------------------------------------------

    @router.get("/api/canvases")
    async def canvases():  # noqa: D401
        return {"canvases": service.list_canvases()}

    # `/api/canvases/trash` **必须**优先于 `/api/canvases/{canvas_id}`
    # （GM-11 硬约束；路由顺序断言测试保证）。
    @router.get("/api/canvases/trash")
    async def trashed_canvases():
        return {"canvases": service.list_deleted_canvases(), "retention_days": 30}

    # ---- POST /api/canvases (create) ----------------------------------

    @router.post("/api/canvases")
    async def create_canvas(payload: canvas_create_dto):  # type: ignore[valid-type]
        raw = _model_dump(payload)
        cmd = CanvasCreateCommand(
            title=payload.title,
            icon=payload.icon,
            kind=payload.kind,
            project=payload.project,
            board_x=payload.board_x,
            board_y=payload.board_y,
            raw=raw,
        )
        return {"canvas": service.create_canvas(cmd)}

    # ---- meta 读写（顺序：GET /meta → POST /meta → GET /{id} → POST /touch）

    @router.get("/api/canvases/{canvas_id}/meta")
    async def get_canvas_meta(canvas_id: str):
        return service.load_canvas_meta(CanvasIdCommand(canvas_id=canvas_id))

    @router.post("/api/canvases/{canvas_id}/meta")
    async def update_canvas_meta(canvas_id: str, payload: canvas_meta_update_dto):  # type: ignore[valid-type]
        """更新画布的轻量元数据（标题/图标/负责人/颜色/置顶）。
        刻意不走 save_canvas（它会刷新 updated_at），以免打标签/置顶把画布顶到列表最前。"""
        raw = _model_dump(payload)
        cmd = CanvasMetaPatchCommand(
            canvas_id=canvas_id,
            title=payload.title,
            icon=payload.icon,
            owner=payload.owner,
            color=payload.color,
            pinned=payload.pinned,
            project=payload.project,
            board_x=payload.board_x,
            board_y=payload.board_y,
            raw=raw,
        )
        return {"canvas": service.update_canvas_meta(cmd)}

    @router.get("/api/canvases/{canvas_id}")
    async def get_canvas(canvas_id: str):
        return {"canvas": service.load_canvas(CanvasIdCommand(canvas_id=canvas_id))}

    @router.post("/api/canvases/{canvas_id}/touch")
    async def touch_canvas(canvas_id: str):
        return await service.touch_canvas(CanvasIdCommand(canvas_id=canvas_id))

    # ---- write / trash / restore / purge (顺序对齐 main.py 原声明) -----

    @router.put("/api/canvases/{canvas_id}")
    async def update_canvas(canvas_id: str, payload: canvas_save_dto):  # type: ignore[valid-type]
        raw = _model_dump(payload)
        cmd = CanvasSaveCommand(
            canvas_id=canvas_id,
            title=payload.title,
            icon=payload.icon,
            nodes=payload.nodes,
            connections=payload.connections,
            viewport=payload.viewport,
            logs=payload.logs,
            settings=payload.settings,
            client_id=payload.client_id,
            base_updated_at=payload.base_updated_at,
            revision=getattr(payload, "revision", None),
            raw=raw,
        )
        canvas = await service.update_canvas(cmd)
        return {"canvas": canvas}

    @router.delete("/api/canvases/{canvas_id}")
    async def delete_canvas(canvas_id: str):
        service.trash_canvas(CanvasIdCommand(canvas_id=canvas_id))
        return {"ok": True}

    @router.post("/api/canvases/{canvas_id}/restore")
    async def restore_canvas(canvas_id: str):
        canvas = service.restore_canvas(CanvasIdCommand(canvas_id=canvas_id))
        return {"canvas": canvas}

    @router.delete("/api/canvases/{canvas_id}/purge")
    async def purge_canvas(canvas_id: str):
        service.purge_canvas(CanvasIdCommand(canvas_id=canvas_id))
        return {"ok": True}

    return router


def _model_dump(payload: Any) -> dict[str, Any]:
    """兼容 pydantic v1 / v2 的 `model_dump()` 兜底。"""

    dumper = getattr(payload, "model_dump", None)
    if callable(dumper):
        return dumper()
    dict_dumper = getattr(payload, "dict", None)
    if callable(dict_dumper):
        return dict_dumper()
    return {}
