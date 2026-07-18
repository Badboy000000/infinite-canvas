"""`app.data_import.importers.project` — Project importer。

从 `app.stores.project_store.snapshot()` 拿 payload，按每个 project 建
`projects` 行；幂等键 `legacy_id` = 旧 `id`。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.data_import import tables as t
from app.data_import._shared import (
    insert_if_absent,
    now_utc,
    serialize_raw_json,
)


DOMAIN = "project"


def _record(entry: dict, imported_at) -> dict[str, Any] | None:
    legacy_id = entry.get("id")
    if not legacy_id:
        return None
    return {
        "legacy_id": str(legacy_id),
        "name": entry.get("name") or None,
        "order_index": int(entry.get("order") or 0),
        "raw_json": serialize_raw_json(entry),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def load_source(source_path: str | None = None) -> list[dict]:
    """从 Store snapshot 或指定路径读取原始 project 列表。"""
    if source_path:
        from app.stores.legacy_snapshot import read_json_source

        payload, _ = read_json_source(source_path, [])
    else:
        from app.stores import project_store

        payload = project_store.snapshot()["payload"]

    if isinstance(payload, dict):
        payload = payload.get("projects") or []
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def import_records(conn: Connection, source_path: str | None = None) -> dict:
    imported_at = now_utc()
    entries = load_source(source_path)
    records = [
        rec for rec in (_record(entry, imported_at) for entry in entries)
        if rec is not None
    ]
    inserted, skipped = insert_if_absent(conn, t.projects, records)
    return {
        "domain": DOMAIN,
        "source_count": len(entries),
        "candidate_count": len(records),
        "inserted": inserted,
        "skipped": skipped,
    }


def reconcile_counts(conn: Connection) -> tuple[int, int, list[str]]:
    entries = load_source(None)
    json_ids = {str(entry.get("id")) for entry in entries if entry.get("id")}
    stmt = select(t.projects.c.legacy_id)
    db_ids = {row[0] for row in conn.execute(stmt).fetchall()}
    missing = sorted(json_ids - db_ids)
    return (len(json_ids), len(db_ids), missing)


__all__ = ["DOMAIN", "import_records", "reconcile_counts", "load_source"]
