"""`app.data_import.importers.prompt_library` — Prompt library importer。

数据形态（旧 JSON）：`{"libraries": [{"id", "name", "scope", "items": [...]}, ...]}`
或直接 `[{"id", ...}, ...]`。每个 library 建 `prompt_libraries` 行；
每个 `item` 建 `prompt_items` 行；幂等键 `legacy_id`。
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


DOMAIN = "prompt_library"


def _library_record(entry: dict, imported_at) -> dict[str, Any] | None:
    legacy_id = entry.get("id")
    if not legacy_id:
        return None
    return {
        "legacy_id": str(legacy_id),
        "name": entry.get("name") or None,
        "scope": entry.get("scope") or None,
        "raw_json": serialize_raw_json({k: v for k, v in entry.items() if k != "items"}),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def _item_record(item: dict, library_legacy_id: str, imported_at) -> dict[str, Any] | None:
    legacy_id = item.get("id")
    if not legacy_id:
        return None
    # 跨 library 保持唯一性：`<library_id>:<item_id>`。
    composite_legacy = f"{library_legacy_id}:{legacy_id}"
    return {
        "legacy_id": composite_legacy,
        "legacy_library_id": library_legacy_id,
        "name": item.get("name") or None,
        "kind": item.get("kind") or item.get("type") or None,
        "raw_json": serialize_raw_json(item),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def load_source(source_path: str | None = None) -> list[dict]:
    if source_path:
        from app.stores.legacy_snapshot import read_json_source

        payload, _ = read_json_source(source_path, {})
    else:
        from app.stores import prompt_library_store

        payload = prompt_library_store.snapshot()["payload"]

    if isinstance(payload, dict):
        libs = payload.get("libraries") or []
    elif isinstance(payload, list):
        libs = payload
    else:
        libs = []
    return [entry for entry in libs if isinstance(entry, dict)]


def import_records(conn: Connection, source_path: str | None = None) -> dict:
    imported_at = now_utc()
    libraries = load_source(source_path)

    lib_records = [
        rec for rec in (_library_record(lib, imported_at) for lib in libraries)
        if rec is not None
    ]
    lib_inserted, lib_skipped = insert_if_absent(conn, t.prompt_libraries, lib_records)

    # 建 library_id map（legacy -> uuid）
    if lib_records:
        legacy_ids = [rec["legacy_id"] for rec in lib_records]
        stmt = select(t.prompt_libraries.c.id, t.prompt_libraries.c.legacy_id).where(
            t.prompt_libraries.c.legacy_id.in_(legacy_ids)
        )
        id_map = {row.legacy_id: row.id for row in conn.execute(stmt).fetchall()}
    else:
        id_map = {}

    item_records: list[dict] = []
    for lib in libraries:
        lib_legacy = str(lib.get("id") or "")
        if not lib_legacy:
            continue
        items = lib.get("items") or []
        if not isinstance(items, list):
            continue
        library_uuid = id_map.get(lib_legacy)
        for item in items:
            if not isinstance(item, dict):
                continue
            rec = _item_record(item, lib_legacy, imported_at)
            if rec is None:
                continue
            rec["library_id"] = library_uuid
            item_records.append(rec)

    item_inserted, item_skipped = insert_if_absent(conn, t.prompt_items, item_records)

    return {
        "domain": DOMAIN,
        "source_count": len(libraries),
        "candidate_count": len(lib_records) + len(item_records),
        "inserted": lib_inserted + item_inserted,
        "skipped": lib_skipped + item_skipped,
        "libraries_inserted": lib_inserted,
        "items_inserted": item_inserted,
    }


def reconcile_counts(conn: Connection) -> tuple[int, int, list[str]]:
    libraries = load_source(None)
    json_ids: set[str] = set()
    for lib in libraries:
        lib_legacy = str(lib.get("id") or "")
        if lib_legacy:
            json_ids.add(lib_legacy)
        for item in lib.get("items") or []:
            if isinstance(item, dict) and item.get("id"):
                json_ids.add(f"{lib_legacy}:{item['id']}")
    lib_stmt = select(t.prompt_libraries.c.legacy_id)
    item_stmt = select(t.prompt_items.c.legacy_id)
    db_ids = {row[0] for row in conn.execute(lib_stmt).fetchall()}
    db_ids |= {row[0] for row in conn.execute(item_stmt).fetchall()}
    missing = sorted(json_ids - db_ids)
    return (len(json_ids), len(db_ids), missing)


__all__ = ["DOMAIN", "import_records", "reconcile_counts", "load_source"]
