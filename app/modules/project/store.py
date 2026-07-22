"""Project 持久化 facade（PR-BE-06）。

薄委派到 `app.stores.project_store`。见 canvas store 模块头部说明。
"""

from __future__ import annotations

from typing import Any

from app.stores import project_store as _project_store_facade


class ProjectStore:
    """薄委派 store。"""

    def load_projects(self) -> list[dict[str, Any]]:
        return _project_store_facade.load_projects()

    def save_projects(self, projects: list[dict[str, Any]]) -> Any:
        return _project_store_facade.save_projects(projects)
