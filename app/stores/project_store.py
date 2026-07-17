"""Project store facade — 数据模型治理 PR-0。

包裹 `main.py` 中项目列表 JSON 读写函数 `load_projects` / `save_projects`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any


def load_projects(*args: Any, **kwargs: Any) -> Any:
    from main import load_projects as _impl
    return _impl(*args, **kwargs)


def save_projects(*args: Any, **kwargs: Any) -> Any:
    from main import save_projects as _impl
    return _impl(*args, **kwargs)
