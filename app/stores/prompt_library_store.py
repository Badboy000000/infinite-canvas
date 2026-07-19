"""Prompt library store facade — 数据模型治理 PR-0 + PR-4 shadow 双读。

包裹 `main.py` 中提示词库 JSON 读写函数
`load_prompt_libraries` / `save_prompt_libraries`。
签名与原函数一一对应，仅做委派，不改行为。

**数据 PR-4**（Wave 3-C）：`load_prompt_libraries()` 在 JSON 读成功后惰性触发
`read_shadow()`；`SHADOW_READ_PROMPT_LIBRARY=false`（默认）时零开销 return。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "prompt_library"


def load_prompt_libraries(*args: Any, **kwargs: Any) -> Any:
    from main import load_prompt_libraries as _impl
    result = _impl(*args, **kwargs)
    read_shadow(result)
    return result


def save_prompt_libraries(*args: Any, **kwargs: Any) -> Any:
    from main import save_prompt_libraries as _impl
    return _impl(*args, **kwargs)


def read_shadow(json_snapshot: Any, *, request_id: str | None = None) -> None:
    """Shadow-read entry；`load_prompt_libraries` 读成功后调用。"""

    from app.shadow_read.runner import is_shadow_read_enabled, run_shadow_read

    if not is_shadow_read_enabled(DOMAIN):
        return
    run_shadow_read(DOMAIN, json_snapshot, request_id=request_id)


def snapshot() -> dict[str, Any]:
    from main import PROMPT_LIBRARY_PATH

    payload, raw_json = read_json_source(PROMPT_LIBRARY_PATH, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.PROMPT_LIBRARY,
        legacy_path=PROMPT_LIBRARY_PATH,
    )
