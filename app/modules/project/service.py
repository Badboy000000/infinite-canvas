"""Project 领域 Service（PR-BE-06）。

`ProjectService` 承接 `/api/projects*` 端点。类似 `CanvasService` 的设计
原则：显式 callback 注入 · 不 `import main`。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .commands import (
    ProjectCreateCommand,
    ProjectDeleteCommand,
    ProjectUpdateCommand,
)
from .store import ProjectStore


class ProjectService:
    def __init__(
        self,
        *,
        store: ProjectStore,
        list_projects: Callable[[], list[dict[str, Any]]],
        new_project: Callable[[str], dict[str, Any]],
        project_record: Callable[[dict[str, Any]], dict[str, Any]],
        ensure_default_project: Callable[[], list[dict[str, Any]]],
        canvas_lock: Any,
        canvas_dir: str,
        default_project_id: str,
        now_ms: Callable[[], int],
    ) -> None:
        self._store = store
        self._list_projects = list_projects
        self._new_project = new_project
        self._project_record = project_record
        self._ensure_default_project = ensure_default_project
        self._canvas_lock = canvas_lock
        self._canvas_dir = canvas_dir
        self._default_project_id = default_project_id
        self._now_ms = now_ms

    def list_projects(self) -> list[dict[str, Any]]:
        return self._list_projects()

    def create_project(self, cmd: ProjectCreateCommand) -> dict[str, Any]:
        return self._project_record(self._new_project(cmd.name))

    def update_project(self, cmd: ProjectUpdateCommand) -> dict[str, Any]:
        from fastapi import HTTPException

        projects = self._ensure_default_project()
        target = next(
            (p for p in projects if p.get("id") == cmd.project_id), None
        )
        if not target:
            raise HTTPException(status_code=404, detail="项目不存在")
        if cmd.name is not None:
            target["name"] = (
                str(cmd.name).strip() or target.get("name") or "未命名项目"
            )[:60]
        if cmd.order is not None:
            target["order"] = int(cmd.order)
        target["updated_at"] = self._now_ms()
        self._store.save_projects(projects)
        return self._project_record(target)

    def delete_project(self, cmd: ProjectDeleteCommand) -> dict[str, Any]:
        """删除项目：默认项目不可删除；其下画布回归默认项目。

        与 `main.py` 原函数 byte-equivalent。返回 `{"ok": True, "moved": N}`。
        """
        import json
        import os

        from fastapi import HTTPException

        if cmd.project_id == self._default_project_id:
            raise HTTPException(status_code=400, detail="默认项目不可删除")
        projects = self._ensure_default_project()
        if not any(p.get("id") == cmd.project_id for p in projects):
            raise HTTPException(status_code=404, detail="项目不存在")
        projects = [p for p in projects if p.get("id") != cmd.project_id]
        self._store.save_projects(projects)
        moved = 0
        with self._canvas_lock:
            for filename in os.listdir(self._canvas_dir):
                if not filename.endswith(".json"):
                    continue
                path = os.path.join(self._canvas_dir, filename)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    continue
                if str(data.get("project") or "") == cmd.project_id:
                    data["project"] = self._default_project_id
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    moved += 1
        return {"ok": True, "moved": moved}
