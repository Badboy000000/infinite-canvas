"""History store facade — 数据模型治理 PR-0。

包裹 `main.py` 中生成历史落盘函数 `save_to_history`。

注：`main.py` 内目前没有独立的 `load_history` helper——`/api/history` 路由
（`get_history_api`，`main.py:16260`）直接读取 `HISTORY_DIR` 下文件，
未走单独 helper。本 PR 只包裹已存在的 helper；分页 / 读入相关 helper
将在数据 PR-1 拆出 `HistoryService` 时统一抽出，届时补入本 facade。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import (
    SchemaVersion,
    build_snapshot,
    read_json_source,
)


def save_to_history(*args: Any, **kwargs: Any) -> Any:
    from main import save_to_history as _impl
    return _impl(*args, **kwargs)


def snapshot() -> dict[str, Any]:
    from main import HISTORY_FILE

    payload, raw_json = read_json_source(HISTORY_FILE, [])
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.HISTORY,
        legacy_path=HISTORY_FILE,
    )
