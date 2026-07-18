"""`app.data_import.importers.workflow_definition` — Workflow metadata importer。

只承接 workflow **元数据**；图本体仍在 `workflows/*.json`。数据源来自
`app.stores.workflow_store.snapshot()`（RunningHub workflow store），
以及 `workflows/` 目录下的内置工作流文件。

**幂等键**：`legacy_id`：
- 对 RunningHub store `apps` / `workflows`：`rh:<provider_id>:<workflow_id>`
- 对内置 `workflows/*.json`：`file:<basename>`
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.data_import import tables as t
from app.data_import._shared import (
    insert_if_absent,
    now_utc,
    serialize_raw_json,
)


DOMAIN = "workflow_definition"


def _rh_records(rh_store: dict, imported_at) -> Iterable[dict[str, Any]]:
    providers = rh_store.get("providers") if isinstance(rh_store, dict) else None
    if isinstance(providers, list):
        for provider in providers:
            if not isinstance(provider, dict):
                continue
            provider_id = str(provider.get("provider_id") or provider.get("id") or "")
            if not provider_id:
                continue
            for kind_key in ("workflows", "apps"):
                items = provider.get(kind_key) or []
                if not isinstance(items, list):
                    continue
                for wf in items:
                    if not isinstance(wf, dict):
                        continue
                    wf_id = str(wf.get("id") or wf.get("workflow_id") or wf.get("app_id") or "")
                    if not wf_id:
                        continue
                    yield {
                        "legacy_id": f"rh:{provider_id}:{kind_key}:{wf_id}",
                        "name": wf.get("name") or None,
                        "provider_id": provider_id,
                        "kind": kind_key.rstrip("s"),
                        "legacy_path": None,
                        "raw_json": serialize_raw_json(wf),
                        "schema_version": "v1_legacy_json",
                        "imported_at": imported_at,
                        "created_at": imported_at,
                        "updated_at": imported_at,
                    }


def _builtin_records(workflows_dir: str, imported_at) -> Iterable[dict[str, Any]]:
    if not workflows_dir or not os.path.isdir(workflows_dir):
        return
    for name in sorted(os.listdir(workflows_dir)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(workflows_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        yield {
            "legacy_id": f"file:{name}",
            "name": name.rsplit(".", 1)[0],
            "provider_id": None,
            "kind": "builtin",
            "legacy_path": path,
            "raw_json": serialize_raw_json({"file": name, "size": size}),
            "schema_version": "v1_legacy_json",
            "imported_at": imported_at,
            "created_at": imported_at,
            "updated_at": imported_at,
        }


def load_source(source_path: str | None = None) -> tuple[dict, str]:
    """Return `(rh_store_payload, workflows_dir)`。`source_path` 覆盖 RH store。"""
    if source_path:
        from app.stores.legacy_snapshot import read_json_source

        payload, _ = read_json_source(source_path, {})
    else:
        from app.stores import workflow_store

        payload = workflow_store.snapshot()["payload"]

    from app.shared.settings import get_settings

    settings = get_settings()
    # 保持稳定：从 main 的 WORKFLOW_DIR 常量导入；此处懒 import 避免循环。
    try:
        from main import WORKFLOW_DIR  # type: ignore
    except Exception:  # pragma: no cover
        WORKFLOW_DIR = os.path.join(settings.base_dir, "workflows") if hasattr(settings, "base_dir") else "workflows"

    return payload if isinstance(payload, dict) else {}, WORKFLOW_DIR


def import_records(conn: Connection, source_path: str | None = None) -> dict:
    imported_at = now_utc()
    rh_payload, wf_dir = load_source(source_path)
    records: list[dict[str, Any]] = list(_rh_records(rh_payload, imported_at))
    records.extend(list(_builtin_records(wf_dir, imported_at)))

    inserted, skipped = insert_if_absent(conn, t.workflow_definitions, records)

    return {
        "domain": DOMAIN,
        "source_count": len(records),
        "candidate_count": len(records),
        "inserted": inserted,
        "skipped": skipped,
    }


def reconcile_counts(conn: Connection) -> tuple[int, int, list[str]]:
    imported_at = now_utc()  # sentinel; timestamps don't matter for counting
    rh_payload, wf_dir = load_source(None)
    json_ids = {rec["legacy_id"] for rec in _rh_records(rh_payload, imported_at)}
    json_ids |= {rec["legacy_id"] for rec in _builtin_records(wf_dir, imported_at)}
    stmt = select(t.workflow_definitions.c.legacy_id)
    db_ids = {row[0] for row in conn.execute(stmt).fetchall()}
    missing = sorted(json_ids - db_ids)
    return (len(json_ids), len(db_ids), missing)


__all__ = ["DOMAIN", "import_records", "reconcile_counts", "load_source"]
