"""Storage settings store facade — 数据模型治理 PR-0。

包裹 `main.py` 中存储目录设置读函数 `load_storage_settings`。

`save_storage_settings` 与 `apply_storage_settings` 属于文件对象治理 PR-0
的窗口（`main.py:298-305` 相关逻辑），本 facade 不包裹写入侧，避免与
文件组 PR 的编辑窗口冲突。写入 facade 由文件对象治理落地后再补齐。
"""
from __future__ import annotations

from typing import Any


def load_storage_settings(*args: Any, **kwargs: Any) -> Any:
    from main import load_storage_settings as _impl
    return _impl(*args, **kwargs)
