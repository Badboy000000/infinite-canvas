"""`app.data_import.importers.asset_library` — Asset library / category / item importer。

数据形态（旧 JSON）：`{"active_library_id", "libraries": [{"id", "name",
"categories": [{"id", "items": [...]}, ...]}, ...]}`。

分别写入 `asset_libraries` / `asset_categories` / `asset_items`；
每张表的 `legacy_id` 是幂等键：
- library：`<lib_id>`
- category：`<lib_id>:<cat_id>`
- item：`<lib_id>:<cat_id>:<item_id>`

**本 PR 明确不做**：
- 不启用 `file_ref`（列只是占位）。
- 不迁移文件本体（`asset_items.file_ref` 留空）。
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.data_import import tables as t
from app.data_import._shared import (
    insert_if_absent,
    now_utc,
    serialize_raw_json,
)


DOMAIN = "asset_library"


def _library_record(entry: dict, imported_at) -> dict[str, Any] | None:
    legacy_id = entry.get("id")
    if not legacy_id:
        return None
    return {
        "legacy_id": str(legacy_id),
        "name": entry.get("name") or None,
        "kind": entry.get("type") or entry.get("kind") or None,
        "raw_json": serialize_raw_json(
            {k: v for k, v in entry.items() if k != "categories"}
        ),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def _category_record(
    cat: dict, lib_legacy_id: str, imported_at
) -> dict[str, Any] | None:
    legacy_id = cat.get("id")
    if not legacy_id:
        return None
    composite = f"{lib_legacy_id}:{legacy_id}"
    return {
        "legacy_id": composite,
        "legacy_library_id": lib_legacy_id,
        "name": cat.get("name") or None,
        "kind": cat.get("type") or cat.get("kind") or None,
        "raw_json": serialize_raw_json(
            {k: v for k, v in cat.items() if k != "items"}
        ),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def _item_record(
    item: dict, cat_legacy_composite: str, imported_at
) -> dict[str, Any] | None:
    legacy_id = item.get("id")
    if not legacy_id:
        return None
    return {
        "legacy_id": f"{cat_legacy_composite}:{legacy_id}",
        "legacy_category_id": cat_legacy_composite,
        "name": item.get("name") or None,
        "kind": item.get("kind") or item.get("type") or None,
        "file_ref": None,  # 文件对象专题预留；本 PR 不启用
        "legacy_url": item.get("url") or None,
        "source_url": item.get("source_url") or item.get("originalUrl") or None,
        "workspace_id": None,
        "project_id": None,
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
        from app.stores import asset_library_store

        payload = asset_library_store.snapshot()["payload"]

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
        rec for rec in (_library_record(l, imported_at) for l in libraries)
        if rec is not None
    ]
    lib_inserted, lib_skipped = insert_if_absent(conn, t.asset_libraries, lib_records)

    # library uuid map
    if lib_records:
        legacy_ids = [rec["legacy_id"] for rec in lib_records]
        stmt = select(t.asset_libraries.c.id, t.asset_libraries.c.legacy_id).where(
            t.asset_libraries.c.legacy_id.in_(legacy_ids)
        )
        lib_uuid_map = {row.legacy_id: row.id for row in conn.execute(stmt).fetchall()}
    else:
        lib_uuid_map = {}

    cat_records: list[dict] = []
    item_records_pending: list[tuple[dict, str]] = []  # (record_dict_without_cat_id, cat_composite_legacy)

    for lib in libraries:
        lib_legacy = str(lib.get("id") or "")
        if not lib_legacy:
            continue
        lib_uuid = lib_uuid_map.get(lib_legacy)
        cats = lib.get("categories") or []
        if not isinstance(cats, list):
            continue
        for cat in cats:
            if not isinstance(cat, dict):
                continue
            cat_rec = _category_record(cat, lib_legacy, imported_at)
            if cat_rec is None:
                continue
            cat_rec["library_id"] = lib_uuid
            cat_records.append(cat_rec)

            items = cat.get("items") or []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_rec = _item_record(item, cat_rec["legacy_id"], imported_at)
                if item_rec is None:
                    continue
                item_records_pending.append((item_rec, cat_rec["legacy_id"]))

    cat_inserted, cat_skipped = insert_if_absent(conn, t.asset_categories, cat_records)

    # 建 category uuid map（针对**所有**已存在 legacy 的行，含刚插入 + 已存在）
    if cat_records:
        legacy_ids = [rec["legacy_id"] for rec in cat_records]
        stmt = select(t.asset_categories.c.id, t.asset_categories.c.legacy_id).where(
            t.asset_categories.c.legacy_id.in_(legacy_ids)
        )
        cat_uuid_map = {row.legacy_id: row.id for row in conn.execute(stmt).fetchall()}
    else:
        cat_uuid_map = {}

    item_records: list[dict] = []
    for item_rec, cat_composite in item_records_pending:
        item_rec["category_id"] = cat_uuid_map.get(cat_composite)
        item_records.append(item_rec)

    item_inserted, item_skipped = insert_if_absent(conn, t.asset_items, item_records)

    return {
        "domain": DOMAIN,
        "source_count": len(libraries),
        "candidate_count": len(lib_records) + len(cat_records) + len(item_records),
        "inserted": lib_inserted + cat_inserted + item_inserted,
        "skipped": lib_skipped + cat_skipped + item_skipped,
        "libraries_inserted": lib_inserted,
        "categories_inserted": cat_inserted,
        "items_inserted": item_inserted,
    }


def reconcile_counts(conn: Connection) -> tuple[int, int, list[str]]:
    libraries = load_source(None)
    json_ids: set[str] = set()
    for lib in libraries:
        lib_legacy = str(lib.get("id") or "")
        if not lib_legacy:
            continue
        json_ids.add(lib_legacy)
        for cat in lib.get("categories") or []:
            if not isinstance(cat, dict) or not cat.get("id"):
                continue
            cat_composite = f"{lib_legacy}:{cat['id']}"
            json_ids.add(cat_composite)
            for item in cat.get("items") or []:
                if isinstance(item, dict) and item.get("id"):
                    json_ids.add(f"{cat_composite}:{item['id']}")
    lib_stmt = select(t.asset_libraries.c.legacy_id)
    cat_stmt = select(t.asset_categories.c.legacy_id)
    item_stmt = select(t.asset_items.c.legacy_id)
    db_ids: set[str] = set()
    for stmt in (lib_stmt, cat_stmt, item_stmt):
        db_ids |= {row[0] for row in conn.execute(stmt).fetchall()}
    missing = sorted(json_ids - db_ids)
    return (len(json_ids), len(db_ids), missing)


__all__ = ["DOMAIN", "import_records", "reconcile_counts", "load_source"]
