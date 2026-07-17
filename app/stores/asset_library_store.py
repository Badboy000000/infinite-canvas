"""Asset library store facade — 数据模型治理 PR-0。

包裹 `main.py` 中素材库 JSON 读写函数 `load_asset_library` / `save_asset_library`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


def load_asset_library(*args: Any, **kwargs: Any) -> Any:
    from main import load_asset_library as _impl
    return _impl(*args, **kwargs)


def save_asset_library(*args: Any, **kwargs: Any) -> Any:
    from main import save_asset_library as _impl
    return _impl(*args, **kwargs)


def snapshot() -> dict[str, Any]:
    from main import ASSET_LIBRARY_PATH

    payload, raw_json = read_json_source(ASSET_LIBRARY_PATH, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.ASSET_LIBRARY,
        legacy_path=ASSET_LIBRARY_PATH,
    )
