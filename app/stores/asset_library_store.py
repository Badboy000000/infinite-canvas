"""Asset library store facade — 数据模型治理 PR-0 + PR-9 主写分派。

包裹 `main.py` 中素材库 JSON 读写函数
`load_asset_library` / `save_asset_library`。签名与原函数一一对应，仅做委派，
不改行为。

**数据 PR-9**（Wave 3-H）：`save_asset_library()` / `load_asset_library()`
按 `ASSET_LIBRARY_PRIMARY_WRITE` env 分派：

- `"json"`（默认）→ 完全等价 PR-0 行为（老 `main.save_asset_library`
  / `main.load_asset_library`）。**必须**保证不 import
  `app.db.asset_library_writer`，不构造 DB engine，不落任何 fallback 文件
  （P0 硬约束 #3）。
- `"db"`（显式启用）→ `app.db.asset_library_writer.save_asset_library_db`
  DB 主写 + JSON 异步回写；`load_asset_library_db()` 优先 + JSON fallback。
  DB 主写失败上抛（不 fallback 到 JSON 主写；P0 硬约束 #4）。

AssetLibrary 域**不列入**数据 PR-4 shadow 双读范围，本 PR 也不引入
`read_shadow()` hook（区别于 project_store / prompt_library_store /
workflow_store 三条 PR-8 wrapper）。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import SchemaVersion, build_snapshot, read_json_source


DOMAIN = "asset_library"

# 数据 PR-9 允许值域（其他值 fail-fast）。
_PRIMARY_WRITE_ALLOWED: frozenset[str] = frozenset({"json", "db"})


def _get_primary_write_mode(domain: str) -> str:
    """读 `ASSET_LIBRARY_PRIMARY_WRITE` env（现读，不缓存）。"""

    if domain != DOMAIN:
        return "json"
    import os

    raw = os.environ.get("ASSET_LIBRARY_PRIMARY_WRITE")
    if raw is None:
        return "json"
    value = str(raw).strip().lower()
    if not value:
        return "json"
    if value not in _PRIMARY_WRITE_ALLOWED:
        raise ValueError(
            f"Invalid ASSET_LIBRARY_PRIMARY_WRITE {raw!r}; expected one of: "
            + ", ".join(sorted(_PRIMARY_WRITE_ALLOWED))
        )
    return value


def load_asset_library(*args: Any, **kwargs: Any) -> Any:
    """`load_asset_library()` wrapper。

    - `ASSET_LIBRARY_PRIMARY_WRITE=json`（默认）→ 老 `main.load_asset_library`。
    - `ASSET_LIBRARY_PRIMARY_WRITE=db` → 优先 `load_asset_library_db()`；
      DB 空（`None`）时 fallback 到 JSON 主读，保持首次冷启语义。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        # 懒 import：仅在 db 模式下才拉起 asset_library_writer 命名空间。
        from app.db.asset_library_writer import load_asset_library_db

        db_payload = load_asset_library_db()
        if db_payload is not None:
            # 复用老实现的 normalize，保证下游代码看到的 shape 与 JSON
            # 主读路径完全一致（categories/libraries 结构补齐等）。
            from main import normalize_asset_library

            return normalize_asset_library(db_payload)

    from main import load_asset_library as _impl
    return _impl(*args, **kwargs)


def save_asset_library(*args: Any, **kwargs: Any) -> Any:
    """`save_asset_library(lib)` wrapper。

    - `ASSET_LIBRARY_PRIMARY_WRITE=json`（默认）→ 老 `main.save_asset_library`；
      **不 import** `app.db.asset_library_writer`。
    - `ASSET_LIBRARY_PRIMARY_WRITE=db` → `save_asset_library_db` DB 主写 +
      JSON 异步回写。DB 主写失败上抛（不 fallback 到 JSON 主写）。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        lib = _extract_lib(args, kwargs)
        if lib is None:
            # 非 dict 传入：走老 impl 让它自己抛错（保持既有语义）。
            from main import save_asset_library as _impl

            return _impl(*args, **kwargs)
        # 懒 import：仅在 db 模式下才拉起 asset_library_writer 命名空间。
        from app.db.asset_library_writer import (
            save_asset_library_db,
            _async_write_json_fallback,
        )

        save_asset_library_db(lib)
        _async_write_json_fallback(lib)
        return None

    # 默认 mode == "json"：完全等价 PR-0 行为。
    from main import save_asset_library as _impl
    return _impl(*args, **kwargs)


def _extract_lib(args: tuple, kwargs: dict) -> dict | None:
    """把 `save_asset_library(lib)` 的位置/关键字参数还原为 dict。"""

    if args:
        candidate = args[0]
    else:
        candidate = kwargs.get("lib")
    if isinstance(candidate, dict):
        return candidate
    return None


def snapshot() -> dict[str, Any]:
    from main import ASSET_LIBRARY_PATH

    payload, raw_json = read_json_source(ASSET_LIBRARY_PATH, {})
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.ASSET_LIBRARY,
        legacy_path=ASSET_LIBRARY_PATH,
    )
