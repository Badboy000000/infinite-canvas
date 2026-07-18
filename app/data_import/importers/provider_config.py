"""`app.data_import.importers.provider_config` — Provider config importer。

**硬约束**：调用 `app.stores.provider_config_store._safe_provider_records()`
做深层脱敏；密钥字段（`api_key` / `authorization` / `secret` / ...）**永不**
进 DB，也不进入 `raw_json` 列。

导入字段限定于 `_PROVIDER_SNAPSHOT_FIELD_ORDER` 白名单。
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


DOMAIN = "provider_config"


def _record(entry: dict, imported_at) -> dict[str, Any] | None:
    legacy_id = entry.get("id") or entry.get("name")
    if not legacy_id:
        return None
    return {
        "legacy_id": str(legacy_id),
        "name": entry.get("name") or None,
        "protocol": entry.get("protocol") or None,
        "base_url": entry.get("base_url") or None,
        "enabled": bool(entry.get("enabled", True)),
        "primary_flag": bool(entry.get("primary", False)),
        "image_request_mode": entry.get("image_request_mode") or None,
        "raw_json": serialize_raw_json(entry),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def load_source(source_path: str | None = None) -> list[dict]:
    """走 Store 深层脱敏路径，返回已脱敏的白名单字段列表。"""
    from app.stores import provider_config_store

    if source_path:
        from app.stores.legacy_snapshot import read_json_source

        raw_payload, _ = read_json_source(source_path, [])
        return provider_config_store._safe_provider_records(raw_payload)

    # 通过 store snapshot()，其内部已调 `_safe_provider_records`。
    payload = provider_config_store.snapshot()["payload"]
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
    inserted, skipped = insert_if_absent(conn, t.provider_configs, records)
    return {
        "domain": DOMAIN,
        "source_count": len(entries),
        "candidate_count": len(records),
        "inserted": inserted,
        "skipped": skipped,
    }


def reconcile_counts(conn: Connection) -> tuple[int, int, list[str]]:
    entries = load_source(None)
    json_ids = {
        str(entry.get("id") or entry.get("name"))
        for entry in entries
        if (entry.get("id") or entry.get("name"))
    }
    stmt = select(t.provider_configs.c.legacy_id)
    db_ids = {row[0] for row in conn.execute(stmt).fetchall()}
    missing = sorted(json_ids - db_ids)
    return (len(json_ids), len(db_ids), missing)


__all__ = ["DOMAIN", "import_records", "reconcile_counts", "load_source"]
