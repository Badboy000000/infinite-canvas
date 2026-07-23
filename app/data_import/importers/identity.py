"""`app.data_import.importers.identity` — 资源归属回填 importer（幂等 · 可重跑）。

扫描现有业务表，补 `workspace_id` = default system workspace id、`legacy_owner_label` =
旧 `owner` 字符串（若字段在表定义中不存在则跳过）。

**幂等保证**：UPDATE 只对 `workspace_id IS NULL` 的行执行；再次运行不影响已填的行。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.data_import._shared import now_utc, serialize_raw_json


DOMAIN = "identity"


# 需要回填的 business 表 + 对应的 owner 字段名
_BUSINESS_TABLES = (
    "projects",
    "provider_configs",
    "prompt_libraries",
    "prompt_items",
    "workflow_definitions",
    "asset_libraries",
    "asset_categories",
    "canvases",
    "generation_history",
)


def _get_system_workspace_id(conn: Connection) -> str | None:
    """查 system workspace 的 id。"""
    row = conn.execute(
        text("SELECT id FROM workspace WHERE name = 'system' AND kind = 'system' LIMIT 1")
    ).fetchone()
    return str(row[0]) if row else None


def _get_default_project_id(conn: Connection) -> str | None:
    """查 default project 的 id。"""
    row = conn.execute(
        text("SELECT id FROM projects WHERE legacy_id = '__default__' LIMIT 1")
    ).fetchone()
    return str(row[0]) if row else None


def _column_exists(conn: Connection, table: str, column: str) -> bool:
    """检查 SQLite 表中某个列是否存在。"""
    rows = conn.execute(
        text(f"PRAGMA table_info({table})")
    ).fetchall()
    return any(row[1] == column for row in rows)


def import_records(conn: Connection, source_path: str | None = None) -> dict:
    """幂等回填：为所有业务表补 workspace_id + legacy_owner_label。

    - `source_path` 参数存在但不使用（identity 不依赖外部源文件）。
    - 返回统计信息。
    """
    workspace_id = _get_system_workspace_id(conn)
    project_id = _get_default_project_id(conn)

    total_updated = 0
    total_owner_updated = 0
    tables_skipped = []
    tables_owner_skipped = []

    for table_name in _BUSINESS_TABLES:
        has_ws = _column_exists(conn, table_name, "workspace_id")
        has_owner = _column_exists(conn, table_name, "legacy_owner_label")

        # 回填 workspace_id
        if has_ws and workspace_id:
            result = conn.execute(
                text(
                    f"UPDATE {table_name} SET workspace_id = :ws_id "
                    f"WHERE workspace_id IS NULL"
                ).bindparams(ws_id=workspace_id)
            )
            total_updated += result.rowcount
        elif not has_ws:
            tables_skipped.append(table_name)

        # 回填 legacy_owner_label（从 owner_label / owner 字段）
        if has_owner:
            # 尝试多种可能的旧 owner 字段名
            owner_col = None
            for candidate in ("owner_label", "owner", "legacy_owner_label"):
                if _column_exists(conn, table_name, candidate):
                    owner_col = candidate
                    break
            if owner_col:
                result = conn.execute(
                    text(
                        f"UPDATE {table_name} SET legacy_owner_label = {owner_col} "
                        f"WHERE legacy_owner_label IS NULL AND {owner_col} IS NOT NULL"
                    )
                )
                total_owner_updated += result.rowcount
            else:
                tables_owner_skipped.append(table_name)
        else:
            tables_owner_skipped.append(table_name)

    return {
        "domain": DOMAIN,
        "source_count": 0,
        "candidate_count": len(_BUSINESS_TABLES),
        "inserted": total_updated,
        "skipped": 0,
        "extras": {
            "owner_label_updated": total_owner_updated,
            "workspace_id_skipped_tables": tables_skipped,
            "owner_label_skipped_tables": tables_owner_skipped,
        },
    }


def reconcile_counts(conn: Connection) -> tuple[int, int, list[str]]:
    """JSON vs DB 对账（identity 无外部 JSON 源，返回空报告）。"""
    return (0, 0, [])


def load_source(source_path: str | None = None) -> list[dict]:
    """identity importer 无外部源文件。"""
    return []


__all__ = ["DOMAIN", "import_records", "reconcile_counts", "load_source"]