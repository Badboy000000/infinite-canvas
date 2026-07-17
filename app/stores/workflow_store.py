"""Workflow store facade — 数据模型治理 PR-0。

包裹 `main.py` 中 RunningHub 工作流存储读写函数
`load_runninghub_workflow_store` / `save_runninghub_workflow_store`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any


def load_runninghub_workflow_store(*args: Any, **kwargs: Any) -> Any:
    from main import load_runninghub_workflow_store as _impl
    return _impl(*args, **kwargs)


def save_runninghub_workflow_store(*args: Any, **kwargs: Any) -> Any:
    from main import save_runninghub_workflow_store as _impl
    return _impl(*args, **kwargs)
