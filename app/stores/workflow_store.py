"""Workflow store facade — 数据模型治理 PR-0。

包裹 `main.py` 中 RunningHub 工作流存储读写函数
`load_runninghub_workflow_store` / `save_runninghub_workflow_store`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


def load_runninghub_workflow_store(*args: Any, **kwargs: Any) -> Any:
    from main import load_runninghub_workflow_store as _impl
    return _impl(*args, **kwargs)


def save_runninghub_workflow_store(*args: Any, **kwargs: Any) -> Any:
    from main import save_runninghub_workflow_store as _impl
    return _impl(*args, **kwargs)


def snapshot() -> dict[str, Any]:
    from main import RUNNINGHUB_WORKFLOW_STORE_FILE

    payload, raw_json = read_json_source(RUNNINGHUB_WORKFLOW_STORE_FILE, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.WORKFLOW,
        legacy_path=RUNNINGHUB_WORKFLOW_STORE_FILE,
    )
