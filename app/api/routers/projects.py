"""Project 领域 router（PR-BE-06 · Wave 3-L 主线 B）。

抽出 `main.py` 中 `/api/projects*` 全部 4 条路由：
- `GET  /api/projects`
- `POST /api/projects`
- `POST /api/projects/{project_id}`
- `DELETE /api/projects/{project_id}`

设计与 canvas router 一致：不 `import main` · DTO 显式注入 · 命令对象组
装 → `ProjectService`。
"""

from typing import Any

from fastapi import APIRouter

from app.modules.project.commands import (
    ProjectCreateCommand,
    ProjectDeleteCommand,
    ProjectUpdateCommand,
)
from app.modules.project.service import ProjectService


def create_router(
    *,
    service: ProjectService,
    project_create_dto: type,
    project_update_dto: type,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/projects")
    async def get_projects():
        return {"projects": service.list_projects()}

    @router.post("/api/projects")
    async def create_project(payload: project_create_dto):  # type: ignore[valid-type]
        raw = _model_dump(payload)
        return {
            "project": service.create_project(
                ProjectCreateCommand(name=payload.name, raw=raw)
            )
        }

    @router.post("/api/projects/{project_id}")
    async def update_project(project_id: str, payload: project_update_dto):  # type: ignore[valid-type]
        raw = _model_dump(payload)
        cmd = ProjectUpdateCommand(
            project_id=project_id,
            name=payload.name,
            order=payload.order,
            raw=raw,
        )
        return {"project": service.update_project(cmd)}

    @router.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str):
        """删除项目：默认项目不可删除；其余项目删除后，其下画布回归默认项目（不删画布）。"""
        return service.delete_project(ProjectDeleteCommand(project_id=project_id))

    return router


def _model_dump(payload: Any) -> dict[str, Any]:
    dumper = getattr(payload, "model_dump", None)
    if callable(dumper):
        return dumper()
    dict_dumper = getattr(payload, "dict", None)
    if callable(dict_dumper):
        return dict_dumper()
    return {}
