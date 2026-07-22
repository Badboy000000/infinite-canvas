"""Canvas 领域 Service（PR-BE-06）。

`CanvasService` 承接 `/api/canvases*` 全部端点的业务动作。当前阶段
service 通过显式 callback 委派回 `main.py` 中的原函数体（保留兼容层），
**不 `import main`**；下一批 PR 会把函数体逐步迁入本模块。

Wave 3-L 主线 B 硬约束（任务书零触碰事实清单）：
- 不改 `CanvasSaveRequest` / `CanvasMetaPatch` DTO shape
- 不改 409 语义 + `base_updated_at` compare-and-swap
- 不合并经典 / 智能画布 shape
- 不改回收站行为
- 不改 5 个 save 函数 byte-identical
- 不动 `app/stores/canvas_store.py` 内部实现（主线 A 目标文件）

设计：命令对象在方法边界上使用；service 内部使用与 `main.py` 原函数
相同的调用形式（避免形状漂移）。命令对象里的 `raw: dict` 字段承接
`nodes` / `connections` 宽松 JSON 兜底。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .commands import (
    CanvasCreateCommand,
    CanvasIdCommand,
    CanvasMetaPatchCommand,
    CanvasSaveCommand,
)
from .store import CanvasStore


class CanvasService:
    """Canvas 业务动作 service。所有跨模块副作用通过 callback 显式注入。"""

    def __init__(
        self,
        *,
        store: CanvasStore,
        list_canvases: Callable[[], list[dict[str, Any]]],
        list_deleted_canvases: Callable[[], list[dict[str, Any]]],
        new_canvas: Callable[..., dict[str, Any]],
        canvas_record: Callable[[dict[str, Any]], dict[str, Any]],
        canvas_path: Callable[[str], str],
        load_canvas_any: Callable[[str], dict[str, Any]],
        normalize_canvas_kind: Callable[[Any], str],
        normalize_canvas_color: Callable[[Any], Any],
        canvas_lock: Any,
        default_project_id: str,
        broadcast_canvas_updated: Callable[[str, int, str], Awaitable[None]],
        now_ms: Callable[[], int],
    ) -> None:
        self._store = store
        self._list_canvases = list_canvases
        self._list_deleted_canvases = list_deleted_canvases
        self._new_canvas = new_canvas
        self._canvas_record = canvas_record
        self._canvas_path = canvas_path
        self._load_canvas_any = load_canvas_any
        self._normalize_canvas_kind = normalize_canvas_kind
        self._normalize_canvas_color = normalize_canvas_color
        self._canvas_lock = canvas_lock
        self._default_project_id = default_project_id
        self._broadcast_canvas_updated = broadcast_canvas_updated
        self._now_ms = now_ms

    # ---- read paths -----------------------------------------------------

    def list_canvases(self) -> list[dict[str, Any]]:
        return self._list_canvases()

    def list_deleted_canvases(self) -> list[dict[str, Any]]:
        return self._list_deleted_canvases()

    def load_canvas(self, cmd: CanvasIdCommand) -> dict[str, Any]:
        return self._store.load_canvas(cmd.canvas_id)

    def load_canvas_meta(self, cmd: CanvasIdCommand) -> dict[str, Any]:
        canvas = self._store.load_canvas(cmd.canvas_id)
        return {
            "id": canvas.get("id"),
            "updated_at": canvas.get("updated_at", 0),
            "title": canvas.get("title", "未命名画布"),
            "icon": canvas.get("icon", "layers"),
            "kind": self._normalize_canvas_kind(canvas.get("kind")),
        }

    # ---- write paths ----------------------------------------------------

    def create_canvas(self, cmd: CanvasCreateCommand) -> dict[str, Any]:
        return self._new_canvas(
            cmd.title,
            cmd.icon,
            cmd.kind,
            cmd.project,
            cmd.board_x,
            cmd.board_y,
        )

    def update_canvas_meta(self, cmd: CanvasMetaPatchCommand) -> dict[str, Any]:
        """更新画布轻量元数据（title/icon/owner/color/pinned/project/board_*).

        刻意不走 `save_canvas`（它会刷新 `updated_at`），以免打标签 / 置顶
        把画布顶到列表最前。与 `main.py` 原函数 byte-equivalent。
        """
        import json

        canvas = self._store.load_canvas(cmd.canvas_id)
        if cmd.title is not None:
            canvas["title"] = (cmd.title or canvas.get("title") or "未命名画布")[:80]
        if cmd.icon is not None:
            canvas["icon"] = (cmd.icon or "layers")[:32]
        if cmd.owner is not None:
            canvas["owner"] = str(cmd.owner).strip()[:40]
        if cmd.color is not None:
            canvas["color"] = self._normalize_canvas_color(cmd.color)
        if cmd.pinned is not None:
            canvas["pinned"] = bool(cmd.pinned)
        if cmd.project is not None:
            canvas["project"] = str(cmd.project).strip() or self._default_project_id
        if cmd.board_x is not None:
            canvas["board_x"] = float(cmd.board_x)
        if cmd.board_y is not None:
            canvas["board_y"] = float(cmd.board_y)
        with self._canvas_lock:
            with open(self._canvas_path(canvas["id"]), "w", encoding="utf-8") as f:
                json.dump(canvas, f, ensure_ascii=False, indent=2)
        return self._canvas_record(canvas)

    async def touch_canvas(self, cmd: CanvasIdCommand) -> dict[str, Any]:
        canvas = self._store.load_canvas(cmd.canvas_id)
        self._store.save_canvas(canvas)
        return {
            "canvas": self._canvas_record(canvas),
            "updated_at": canvas.get("updated_at", 0),
        }

    async def update_canvas(self, cmd: CanvasSaveCommand) -> dict[str, Any]:
        """`PUT /api/canvases/{canvas_id}` 主写路径。

        乐观锁双维度契约(CB-P5-17 + CB-P5-18 承接 · 数据 PR-19):

        - `base_updated_at` compare-and-swap:严格 `!=` 语义(与 Store 层
          `canvas_writer.py::save_canvas_db` 保持一致 · older `<` +
          newer `>` 反向漂移都拦截)。
        - `revision` compare-and-swap:独立锁维度 · 当 `cmd.revision` 显
          式提供时启用(老前端不上报 → 保持向后兼容 · 单维度语义不变)。

        409 响应 shape 与 `main.py` 逐字节一致(`{"message", "canvas",
        "updated_at"}`)· revision 分支复用同一 shape,避免破坏前端 409
        兼容读。
        """
        from fastapi import HTTPException

        canvas = self._store.load_canvas(cmd.canvas_id)
        current_updated_at = int(canvas.get("updated_at") or 0)
        if (
            cmd.base_updated_at
            and current_updated_at
            and int(cmd.base_updated_at) != current_updated_at
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "画布已被其他页面更新，已拒绝旧版本覆盖。",
                    "canvas": canvas,
                    "updated_at": current_updated_at,
                },
            )
        if cmd.revision is not None:
            current_revision = int(canvas.get("revision") or 0)
            if int(cmd.revision) != current_revision:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "画布已被其他页面更新，已拒绝旧版本覆盖。",
                        "canvas": canvas,
                        "updated_at": current_updated_at,
                    },
                )
        elif "revision" in cmd.raw:
            # `raw` 兜底(与 CanvasCreateCommand / CanvasMetaPatchCommand 一
            # 致的宽松 JSON 承接语义 · commands.py:57 注释):当调用侧未
            # 走 router DTO 投影(如老前端 payload 直接构造命令时),仍
            # 从 raw dict 里捞回 revision 维度。
            current_revision = int(canvas.get("revision") or 0)
            try:
                cmd_revision = int(cmd.raw["revision"])
            except (TypeError, ValueError):
                cmd_revision = None
            if cmd_revision is not None and cmd_revision != current_revision:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "画布已被其他页面更新，已拒绝旧版本覆盖。",
                        "canvas": canvas,
                        "updated_at": current_updated_at,
                    },
                )
        canvas["title"] = (cmd.title or canvas.get("title") or "未命名画布")[:80]
        canvas["icon"] = (cmd.icon or canvas.get("icon") or "layers")[:32]
        canvas["kind"] = self._normalize_canvas_kind(canvas.get("kind"))
        # `nodes` / `connections` 保持宽松 JSON 结构；命令对象已经把整
        # payload 存在 `cmd.raw` 里作为兜底（防止字段丢失）。
        canvas["nodes"] = cmd.nodes if cmd.nodes is not None else cmd.raw.get(
            "nodes", []
        )
        canvas["connections"] = (
            cmd.connections
            if cmd.connections is not None
            else cmd.raw.get("connections", [])
        )
        if canvas["kind"] == "smart":
            canvas["viewport"] = cmd.viewport
        else:
            canvas["viewport"] = canvas.get("viewport") or {"x": 0, "y": 0, "scale": 1}
        canvas["logs"] = cmd.logs[-500:]
        canvas["settings"] = cmd.settings or {}
        self._store.save_canvas(canvas)
        await self._broadcast_canvas_updated(
            cmd.canvas_id,
            int(canvas.get("updated_at") or self._now_ms()),
            cmd.client_id,
        )
        return canvas

    def trash_canvas(self, cmd: CanvasIdCommand) -> None:
        canvas = self._load_canvas_any(cmd.canvas_id)
        if not canvas.get("deleted_at"):
            canvas["deleted_at"] = self._now_ms()
            self._store.save_canvas(canvas)

    def restore_canvas(self, cmd: CanvasIdCommand) -> dict[str, Any]:
        canvas = self._load_canvas_any(cmd.canvas_id)
        if canvas.get("deleted_at"):
            canvas.pop("deleted_at", None)
            self._store.save_canvas(canvas)
        return canvas

    def purge_canvas(self, cmd: CanvasIdCommand) -> None:
        import os

        path = self._canvas_path(cmd.canvas_id)
        if os.path.exists(path):
            os.remove(path)
