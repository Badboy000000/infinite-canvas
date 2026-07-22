"""Project 命令对象（PR-BE-06 · Wave 3-L 主线 B）。

见 `app.modules.canvas.commands` 头部说明。`raw` 字段兜底同样保留。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProjectCreateCommand:
    """`POST /api/projects` 命令对象。"""

    name: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectUpdateCommand:
    """`POST /api/projects/{project_id}` 命令对象。"""

    project_id: str
    name: str | None
    order: int | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectDeleteCommand:
    """`DELETE /api/projects/{project_id}` 命令对象。"""

    project_id: str
    raw: dict[str, Any] = field(default_factory=dict)
