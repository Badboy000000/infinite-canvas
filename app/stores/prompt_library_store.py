"""Prompt library store facade — 数据模型治理 PR-0。

包裹 `main.py` 中提示词库 JSON 读写函数
`load_prompt_libraries` / `save_prompt_libraries`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any


def load_prompt_libraries(*args: Any, **kwargs: Any) -> Any:
    from main import load_prompt_libraries as _impl
    return _impl(*args, **kwargs)


def save_prompt_libraries(*args: Any, **kwargs: Any) -> Any:
    from main import save_prompt_libraries as _impl
    return _impl(*args, **kwargs)
