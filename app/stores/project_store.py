"""Project store facade — 数据模型治理 PR-0。

包裹 `main.py` 中项目列表 JSON 读写函数 `load_projects` / `save_projects`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


def load_projects(*args: Any, **kwargs: Any) -> Any:
    from main import load_projects as _impl
    return _impl(*args, **kwargs)


def save_projects(*args: Any, **kwargs: Any) -> Any:
    from main import save_projects as _impl
    return _impl(*args, **kwargs)


def snapshot() -> dict[str, Any]:
    from main import PROJECTS_PATH

    payload, raw_json = read_json_source(PROJECTS_PATH, [])
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.PROJECT,
        legacy_path=PROJECTS_PATH,
    )
