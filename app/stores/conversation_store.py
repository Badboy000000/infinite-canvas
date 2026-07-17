"""Conversation store facade — 数据模型治理 PR-0。

包裹 `main.py` 中会话 JSON 读写函数 `save_conversation` / `load_conversation`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any


def load_conversation(*args: Any, **kwargs: Any) -> Any:
    from main import load_conversation as _impl
    return _impl(*args, **kwargs)


def save_conversation(*args: Any, **kwargs: Any) -> Any:
    from main import save_conversation as _impl
    return _impl(*args, **kwargs)
