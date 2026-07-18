"""`app.data_import._shared` — importer 共享工具（时间戳 / raw_json / 插入）。

- `now_utc()`：tz-aware UTC 当前时间。
- `serialize_raw_json(payload)`：确定性 JSON 序列化（保序 + `ensure_ascii=False`）。
- `insert_if_absent(conn, table, records, legacy_id_field='legacy_id')`：
  幂等插入；SQLite `INSERT OR IGNORE ON <legacy_id>`；返回 `(inserted, skipped)`。
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Iterable, Mapping

from sqlalchemy import Table, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection


def now_utc() -> _dt.datetime:
    """tz-aware UTC 当前时间；SQLite 侧统一 ISO 字符串存储。"""
    return _dt.datetime.now(_dt.timezone.utc)


def serialize_raw_json(payload: Any) -> str:
    """确定性 JSON 序列化。缺失/无法序列化时返回空对象。"""
    try:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=False, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return "{}"


def _existing_legacy_ids(
    conn: Connection, table: Table, legacy_ids: Iterable[str]
) -> set[str]:
    """一次性查已存在的 legacy_id。"""
    legacy_ids = list({str(x) for x in legacy_ids if x is not None})
    if not legacy_ids:
        return set()
    stmt = select(table.c.legacy_id).where(table.c.legacy_id.in_(legacy_ids))
    return {row[0] for row in conn.execute(stmt).fetchall()}


def insert_if_absent(
    conn: Connection,
    table: Table,
    records: list[Mapping[str, Any]],
) -> tuple[int, int]:
    """幂等插入。对已存在 `legacy_id` 的记录忽略；不产生副本。

    走 SQLAlchemy dialect `insert().on_conflict_do_nothing(index_elements=
    ['legacy_id'])`；此路径在 SQLite 与 PostgreSQL 均可用（PG 走 pg dialect）。
    治理期只用 SQLite，暂固定走 `sqlite_insert`。

    返回 `(inserted, skipped)`。
    """
    if not records:
        return (0, 0)
    legacy_ids = [str(rec.get("legacy_id")) for rec in records if rec.get("legacy_id")]
    existing = _existing_legacy_ids(conn, table, legacy_ids)

    to_insert = [
        dict(rec)
        for rec in records
        if rec.get("legacy_id") is not None
        and str(rec["legacy_id"]) not in existing
    ]
    skipped = len(records) - len(to_insert)
    if to_insert:
        stmt = sqlite_insert(table).on_conflict_do_nothing(
            index_elements=["legacy_id"]
        )
        conn.execute(stmt, to_insert)
    return (len(to_insert), skipped)


__all__ = ["now_utc", "serialize_raw_json", "insert_if_absent"]
