"""Workflow store facade — 数据模型治理 PR-0 + PR-4 shadow 双读 + PR-8 主写分派。

包裹 `main.py` 中 RunningHub 工作流存储读写函数
`load_runninghub_workflow_store` / `save_runninghub_workflow_store`。
签名与原函数一一对应，仅做委派，不改行为。

**数据 PR-4**（Wave 3-C）：`load_runninghub_workflow_store()` 在 JSON 读
成功后惰性触发 `read_shadow()`；`SHADOW_READ_WORKFLOW_DEFINITION=false`
（默认）时零开销 return。

**数据 PR-8**（Wave 3-G）：`save_runninghub_workflow_store()` 按
`WORKFLOW_DEFINITION_PRIMARY_WRITE` env 分派：
- `"json"`（默认）→ 完全等价 PR-4 行为。**必须**保证不 import
  `app.db.workflow_writer`，不构造 DB engine，不落 fallback 文件。
- `"db"`（显式启用）→ `save_runninghub_workflow_store_db` DB 主写（含 P0
  密钥剪枝）+ JSON 异步回写。DB 主写失败上抛（不 fallback）。
  `prune_runninghub_workflow_store_for_provider` 语义自动等价（`main.py`
  通过 store facade 调用；wrapper 分派内自动接管）。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "workflow_definition"

_PRIMARY_WRITE_ALLOWED: frozenset[str] = frozenset({"json", "db"})


def _get_primary_write_mode(domain: str) -> str:
    """读 `WORKFLOW_DEFINITION_PRIMARY_WRITE` env（现读，不缓存）。"""

    if domain != DOMAIN:
        return "json"
    import os

    raw = os.environ.get("WORKFLOW_DEFINITION_PRIMARY_WRITE")
    if raw is None:
        return "json"
    value = str(raw).strip().lower()
    if not value:
        return "json"
    if value not in _PRIMARY_WRITE_ALLOWED:
        raise ValueError(
            f"Invalid WORKFLOW_DEFINITION_PRIMARY_WRITE {raw!r}; expected one of: "
            + ", ".join(sorted(_PRIMARY_WRITE_ALLOWED))
        )
    return value


def load_runninghub_workflow_store(*args: Any, **kwargs: Any) -> Any:
    from main import load_runninghub_workflow_store as _impl
    result = _impl(*args, **kwargs)
    read_shadow(result)
    return result


def save_runninghub_workflow_store(*args: Any, **kwargs: Any) -> Any:
    """`save_runninghub_workflow_store(store)` wrapper。

    - `WORKFLOW_DEFINITION_PRIMARY_WRITE=json`（默认）→ 老 `main.save_runninghub_workflow_store`；
      **不 import** `app.db.workflow_writer`。
    - `WORKFLOW_DEFINITION_PRIMARY_WRITE=db` → `save_runninghub_workflow_store_db` DB 主写
      + JSON 异步回写。
      `prune_runninghub_workflow_store_for_provider`（在 `main.py` 内）通过
      本 facade 调用，因此 prune 语义在 db 模式下自动等价（DELETE 集合级事务
      会清除不在 payload 中的 rh workflow 行）。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        store = _extract_store(args, kwargs)
        if store is None:
            from main import save_runninghub_workflow_store as _impl

            return _impl(*args, **kwargs)
        # 懒 import：仅在 db 模式下才拉起 workflow_writer 命名空间。
        from app.db.workflow_writer import (
            save_runninghub_workflow_store_db,
            _async_write_json_fallback,
        )

        save_runninghub_workflow_store_db(store)
        _async_write_json_fallback(store)
        return None

    # 默认 mode == "json"：完全等价 PR-4 行为。
    from main import save_runninghub_workflow_store as _impl
    return _impl(*args, **kwargs)


def _extract_store(args: tuple, kwargs: dict) -> dict | None:
    if args:
        candidate = args[0]
    else:
        candidate = kwargs.get("store")
    if isinstance(candidate, dict):
        return candidate
    return None


def read_shadow(json_snapshot: Any, *, request_id: str | None = None) -> None:
    """Shadow-read entry；`load_runninghub_workflow_store` 读成功后调用。"""

    from app.shadow_read.runner import is_shadow_read_enabled, run_shadow_read

    if not is_shadow_read_enabled(DOMAIN):
        return
    run_shadow_read(DOMAIN, json_snapshot, request_id=request_id)


def snapshot() -> dict[str, Any]:
    from main import RUNNINGHUB_WORKFLOW_STORE_FILE

    payload, raw_json = read_json_source(RUNNINGHUB_WORKFLOW_STORE_FILE, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.WORKFLOW,
        legacy_path=RUNNINGHUB_WORKFLOW_STORE_FILE,
    )
