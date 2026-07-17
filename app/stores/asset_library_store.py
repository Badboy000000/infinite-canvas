"""Asset library store facade — 数据模型治理 PR-0。

包裹 `main.py` 中素材库 JSON 读写函数 `load_asset_library` / `save_asset_library`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any


def load_asset_library(*args: Any, **kwargs: Any) -> Any:
    from main import load_asset_library as _impl
    return _impl(*args, **kwargs)


def save_asset_library(*args: Any, **kwargs: Any) -> Any:
    from main import save_asset_library as _impl
    return _impl(*args, **kwargs)
