"""Project store facade — 数据模型治理 PR-0 + PR-4 shadow 双读。

包裹 `main.py` 中项目列表 JSON 读写函数 `load_projects` / `save_projects`。
签名与原函数一一对应，仅做委派，不改行为。

**数据 PR-4**（Wave 3-C）：`load_projects()` 在 JSON 读成功后惰性触发
`read_shadow()`；`SHADOW_READ_PROJECT=false`（默认）时零开销直接 return，
不 import DB 层、不构造 engine、不落盘任何 diff 文件。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "project"


def load_projects(*args: Any, **kwargs: Any) -> Any:
    from main import load_projects as _impl
    result = _impl(*args, **kwargs)
    # 数据 PR-4 shadow read hook；env 关闭时零开销 return。
    read_shadow(result)
    return result


def save_projects(*args: Any, **kwargs: Any) -> Any:
    from main import save_projects as _impl
    return _impl(*args, **kwargs)


def read_shadow(json_snapshot: Any, *, request_id: str | None = None) -> None:
    """Shadow-read entry；JSON 主读成功后调用。

    - 门禁：`SHADOW_READ_PROJECT` env truthy 才继续。
    - 结果永不进入 HTTP 响应；只影响 `data/shadow_diff/project/*.jsonl` 落盘。
    - 失败隔离：任何异常仅记 warning。
    """

    # 零开销 short-circuit：只 import runner 命名空间，不触发 DB 层。
    from app.shadow_read.runner import is_shadow_read_enabled, run_shadow_read

    if not is_shadow_read_enabled(DOMAIN):
        return
    run_shadow_read(DOMAIN, json_snapshot, request_id=request_id)


def snapshot() -> dict[str, Any]:
    from main import PROJECTS_PATH

    payload, raw_json = read_json_source(PROJECTS_PATH, [])
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.PROJECT,
        legacy_path=PROJECTS_PATH,
    )
