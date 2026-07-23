"""History store facade — 数据模型治理 PR-0 + PR-12 主写分派。

包裹 `main.py` 中生成历史落盘函数 `save_to_history` + 新增 `load_history()`
读入 facade。

**数据 PR-12**（Wave 3-N.6 Batch 2 主线 B · GM-22 pattern 第 7 次复用）：
`save_to_history()` / `load_history()` 按 `HISTORY_PRIMARY_WRITE` env 分派：

- `"json"`（默认）→ 完全等价 PR-0 行为（老 `main.save_to_history` /
  `main.HISTORY_FILE` 直读）。**必须**保证不 import `app.db.history_writer`，
  不构造 DB engine，不落任何 fallback 文件（P0 硬约束 #3）。
- `"db"`（显式启用）→ `app.db.history_writer.save_history_db` DB 主写 +
  JSON 异步回写；`load_history_db()` 优先 + JSON fallback。DB 主写失败上抛
  （不 fallback 到 JSON 主写；P0 硬约束 #4）。

**本 PR 只加机制不切默认**（GM-22 硬约束）；反转默认为 `"db"` 是独立 PR。

load facade 说明（GM-16 加强版 pre-flight 已复核）：
- 上游 `main.get_history_api`（`main.py:17019`）本身直读 `HISTORY_FILE` ·
  路由 `app/api/routers/history.py` 通过 callback 依赖注入消费；本 PR **不**
  改路由 / 不改 `get_history_api`，只在 store 层新增 `load_history()` 给
  未来路由重写用（当前无 caller · 但契约存在保证 `db` 分支可读）。

`history` 域**不列入**数据 PR-4 shadow 双读范围，本 PR 也不引入
`read_shadow()` hook（与 asset_library_store 一致 · 语义分离由 P0 硬约束保证）。
"""
from __future__ import annotations

from typing import Any

from .legacy_snapshot import (
    SchemaVersion,
    build_snapshot,
    read_json_source,
)


DOMAIN = "generation_history"

# 数据 PR-12 允许值域（其他值 fail-fast）。
_PRIMARY_WRITE_ALLOWED: frozenset[str] = frozenset({"json", "db"})


def _get_primary_write_mode(domain: str) -> str:
    """读 `HISTORY_PRIMARY_WRITE` env（现读，不缓存）。

    - `None` / 空串 → `"json"`（本 PR 默认；GM-22 反转独立 PR）。
    - `"json"` / `"db"`（大小写不敏感、strip 后）→ 返回小写值。
    - 其他值 → `ValueError`（fail-fast · 与 Settings 层一致）。
    """

    if domain != DOMAIN:
        return "json"
    import os

    raw = os.environ.get("HISTORY_PRIMARY_WRITE")
    if raw is None:
        return "json"
    value = str(raw).strip().lower()
    if not value:
        return "json"
    if value not in _PRIMARY_WRITE_ALLOWED:
        raise ValueError(
            f"Invalid HISTORY_PRIMARY_WRITE {raw!r}; expected one of: "
            + ", ".join(sorted(_PRIMARY_WRITE_ALLOWED))
        )
    return value


def save_to_history(*args: Any, **kwargs: Any) -> Any:
    """`save_to_history(record)` wrapper。

    - `HISTORY_PRIMARY_WRITE=json`（默认）→ 老 `main.save_to_history`；
      **不 import** `app.db.history_writer`。
    - `HISTORY_PRIMARY_WRITE=db`（显式）→ `save_history_db` DB 主写 +
      JSON 异步回写。DB 主写失败上抛（不 fallback 到 JSON 主写）。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        record = _extract_record(args, kwargs)
        if record is None:
            # 非 dict 传入：走老 impl 让它自己抛错（保持既有语义）。
            from main import save_to_history as _impl

            return _impl(*args, **kwargs)
        # 懒 import：仅在 db 模式下才拉起 history_writer 命名空间。
        from app.db.history_writer import (
            save_history_db,
            _async_write_json_fallback,
        )

        save_history_db(record)
        _async_write_json_fallback(record)
        return None

    # 默认 mode == "json"：完全等价 PR-0 行为。
    from main import save_to_history as _impl
    return _impl(*args, **kwargs)


def load_history() -> list[dict]:
    """`load_history()` facade — 数据 PR-12 新增。

    - `HISTORY_PRIMARY_WRITE=db` → 优先 `load_history_db()`；DB 空（None）
      或异常 fallback 到 JSON 主读（参照 canvas_store.load_canvas L229-241
      pattern）。
    - `HISTORY_PRIMARY_WRITE=json`（默认）→ 直读 `HISTORY_FILE` JSON list。

    返回 list[dict]；文件缺失 / 解析失败 → `[]`（与 legacy get_history_api
    的 fallback 语义一致）。
    """

    mode = _get_primary_write_mode(DOMAIN)
    if mode == "db":
        try:
            from app.db.history_writer import load_history_db

            db_records = load_history_db()
        except Exception:
            # DB 读失败降级 JSON 主读（P0 硬约束 #4：主写路径抛错，
            # 读路径允许 fallback）。
            db_records = None
        if db_records is not None:
            return db_records

    return _load_history_from_file()


def _load_history_from_file() -> list[dict]:
    """直读 `main.HISTORY_FILE` 的 JSON list（legacy `get_history_api` 语义）。

    - 文件缺失 → `[]`。
    - 解析失败 → `[]`（不抛错 · 与 legacy `except Exception: return []` 对齐）。
    - 结果不做 type/images 过滤（那是路由层的关注点）。
    """

    import json
    import os

    from main import HISTORY_FILE

    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _extract_record(args: tuple, kwargs: dict) -> dict | None:
    """把 `save_to_history(record)` 的位置/关键字参数还原为 dict。"""

    if args:
        candidate = args[0]
    else:
        candidate = kwargs.get("record")
    if isinstance(candidate, dict):
        return candidate
    return None


def snapshot() -> dict[str, Any]:
    from main import HISTORY_FILE

    payload, raw_json = read_json_source(HISTORY_FILE, [])
    return build_snapshot(
        payload,
        raw_json=raw_json,
        schema_version=SchemaVersion.HISTORY,
        legacy_path=HISTORY_FILE,
    )


__all__ = [
    "save_to_history",
    "load_history",
    "snapshot",
]
