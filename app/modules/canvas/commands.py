"""Canvas 命令对象（PR-BE-06 · Wave 3-L 主线 B）。

命令对象承接 `main.py` 中 `/api/canvases*` 端点的入参。每个命令对象都保留
一个 `raw: dict` 字段作为宽松兜底，防止 `nodes` / `connections` 之类的宽松
JSON 字段在 Service 边界上因显式建模而丢失。

设计约束（任务书零触碰事实清单第 1、5 项）：
- **不改** `CanvasSaveRequest` / `CanvasMetaPatch` 等 Pydantic DTO 字段与默
  认值。命令对象只是从 DTO 组装出来的、供 Service 内部使用的独立轻量类
  型；请求 / 响应 shape 与错误码保持逐字节一致。
- 命令对象刻意不引入校验；校验依然在 FastAPI DTO 层完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CanvasCreateCommand:
    """`POST /api/canvases` 命令对象。"""

    title: str
    icon: str
    kind: str
    project: str | None
    board_x: float | None
    board_y: float | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanvasMetaPatchCommand:
    """`POST /api/canvases/{canvas_id}/meta` 命令对象。"""

    canvas_id: str
    title: str | None
    icon: str | None
    owner: str | None
    color: str | None
    pinned: bool | None
    project: str | None
    board_x: float | None
    board_y: float | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanvasSaveCommand:
    """`PUT /api/canvases/{canvas_id}` 命令对象。

    `raw` 兜底：完整保留调用侧原始 payload（包含 `nodes` / `connections`
    的宽松 JSON 结构），Service 内部映射失败或字段缺失时可以从 `raw` 里
    捞回原始字段。承接任务书风险 1（`nodes` 宽松 JSON 与新命令对象映射
    时字段丢失 → 命令对象保留 `raw: dict` 兜底并回写）。
    """

    canvas_id: str
    title: str
    icon: str
    nodes: list[dict[str, Any]]
    connections: list[dict[str, Any]]
    viewport: dict[str, Any]
    logs: list[dict[str, Any]]
    settings: dict[str, Any]
    client_id: str
    base_updated_at: int
    revision: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CanvasIdCommand:
    """单纯只有 canvas_id 的命令（delete / restore / purge / touch / get）。"""

    canvas_id: str
    raw: dict[str, Any] = field(default_factory=dict)
