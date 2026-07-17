"""Conversation store facade — 数据模型治理 PR-0。

包裹 `main.py` 中会话 JSON 读写函数 `save_conversation` / `load_conversation`。
签名与原函数一一对应，仅做委派，不改行为。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


def load_conversation(*args: Any, **kwargs: Any) -> Any:
    from main import load_conversation as _impl
    return _impl(*args, **kwargs)


def save_conversation(*args: Any, **kwargs: Any) -> Any:
    from main import save_conversation as _impl
    return _impl(*args, **kwargs)


def snapshot(user_id: str, conversation_id: str) -> dict[str, Any]:
    from main import conversation_path

    path = conversation_path(user_id, conversation_id)
    payload, raw_json = read_json_source(path, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.CONVERSATION,
        legacy_id=str(payload.get("id") or conversation_id),
        legacy_path=path,
        legacy_owner_label=user_id,
    )
