"""`app.data_import.importers.canvas` — Canvas 元数据 importer。

数据形态：`CANVAS_DIR/<canvas_id>.json`，每个文件即一个 canvas。

字段抽取（元数据 + `content_json` = 原始 JSON 完整字符串）：
- `legacy_id` = canvas `id` 字段（或文件名 stem）
- `title / kind / project_legacy_id / owner_label / pinned` 从 payload 顶层
- `content_json` = 完整原始 JSON 字符串（治理期作为 payload 的字节等价保留）
- `revision / base_updated_at / deleted_at` 从 payload 抬入独立列

**本 PR 明确不做**：只导入；不启用 shadow 双读；不切主写。
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.data_import import tables as t
from app.data_import._shared import (
    insert_if_absent,
    now_utc,
    serialize_raw_json,
)


DOMAIN = "canvas"


def _record_from_payload(
    payload: dict, raw_text: str, legacy_id: str, imported_at
) -> dict[str, Any]:
    return {
        "legacy_id": str(legacy_id),
        "title": payload.get("title") or None,
        "kind": payload.get("kind") or None,
        "project_legacy_id": (
            str(payload.get("project"))
            if payload.get("project") is not None
            else None
        ),
        "owner_label": payload.get("owner") or None,
        "pinned": bool(payload.get("pinned", False)),
        "content_json": raw_text,
        "revision": int(payload.get("revision") or 0),
        "base_updated_at": (
            str(payload.get("base_updated_at"))
            if payload.get("base_updated_at") is not None
            else None
        ),
        "deleted_at": (
            str(payload.get("deleted_at"))
            if payload.get("deleted_at") is not None
            else None
        ),
        "raw_json": serialize_raw_json(
            {
                "id": payload.get("id"),
                "title": payload.get("title"),
                "kind": payload.get("kind"),
                "revision": payload.get("revision"),
                "updated_at": payload.get("updated_at"),
                "created_at": payload.get("created_at"),
            }
        ),
        "schema_version": "v1_legacy_json",
        "imported_at": imported_at,
        "created_at": imported_at,
        "updated_at": imported_at,
    }


def _iter_canvas_files(source_dir: str | None) -> list[tuple[str, str, dict]]:
    """Return `[(legacy_id, raw_text, payload_dict), ...]` from canvas JSON files."""
    if not source_dir:
        try:
            from main import CANVAS_DIR  # type: ignore
        except Exception:  # pragma: no cover
            return []
        source_dir = CANVAS_DIR

    if not source_dir or not os.path.isdir(source_dir):
        return []

    entries: list[tuple[str, str, dict]] = []
    for path in sorted(glob.glob(os.path.join(source_dir, "*.json"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            with open(path, "rb") as fh:
                raw_bytes = fh.read()
            raw_text = raw_bytes.decode("utf-8")
            payload = json.loads(raw_text)
        except (OSError, UnicodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        legacy_id = str(payload.get("id") or stem)
        entries.append((legacy_id, raw_text, payload))
    return entries


def load_source(source_path: str | None = None) -> list[tuple[str, str, dict]]:
    """`source_path` 覆盖 CANVAS_DIR（用于测试隔离 / 手动样例）。"""
    return _iter_canvas_files(source_path)


def import_records(conn: Connection, source_path: str | None = None) -> dict:
    imported_at = now_utc()
    entries = load_source(source_path)
    records = [
        _record_from_payload(payload, raw_text, legacy_id, imported_at)
        for legacy_id, raw_text, payload in entries
    ]
    inserted, skipped = insert_if_absent(conn, t.canvases, records)
    return {
        "domain": DOMAIN,
        "source_count": len(entries),
        "candidate_count": len(records),
        "inserted": inserted,
        "skipped": skipped,
    }


def reconcile_counts(conn: Connection) -> tuple[int, int, list[str]]:
    entries = load_source(None)
    json_ids = {legacy_id for legacy_id, _, _ in entries}
    stmt = select(t.canvases.c.legacy_id)
    db_ids = {row[0] for row in conn.execute(stmt).fetchall()}
    missing = sorted(json_ids - db_ids)
    return (len(json_ids), len(db_ids), missing)


__all__ = ["DOMAIN", "import_records", "reconcile_counts", "load_source"]
