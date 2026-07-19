"""`scripts/task_history_reconcile.py` — 任务 PR-4 History 派生对账 CLI。

对账 `history.json`（进程外 JSON snapshot）与影子 SQLite Task 事实层的 History
派生副本（`Task.idempotency_key` 以 `history:` 前缀命名）。稳定 JSON 输出，
供 CI / 手工 diff 使用。

用法：
    python scripts/task_history_reconcile.py [--since <hours>]

输出（键顺序稳定）：
    {
      "history_json_count": N,
      "derived_count": M,
      "missing_derived": [...history record 摘要 key 未在事实层出现...],
      "extra_derived": [...事实层有、但 history.json 无的 idempotency_key...],
      "kind_stats": { "online-image": {"json": .., "derived": ..}, ... }
    }

限制：
- 需先执行至少一次 `run_migrations("head")`（本 CLI 自动执行）；也需要
  与主进程共用同一 `history.json` 路径（`from main import HISTORY_FILE`）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _json_snapshot():
    """从 `history.json` 拉全量 record snapshot（复用 `history_store.snapshot`）。"""

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app.stores.history_store import snapshot

    payload = snapshot()
    return payload.get("payload") or []


def _derived_snapshot():
    from app.db.engine import run_migrations
    from app.task.store import sqlite_stores

    run_migrations("head")
    task_store, _, _, _, _ = sqlite_stores()

    from sqlalchemy import select

    from app.db.session import get_session
    from app.task.tables import tasks as tasks_table

    rows_out: list = []
    with get_session() as session:
        rows = session.execute(select(tasks_table)).mappings().all()
        for row in rows:
            key = row["idempotency_key"]
            if not key or not key.startswith("history:"):
                continue
            rows_out.append(
                {
                    "id": str(row["id"]),
                    "task_type": row["task_type"],
                    "status": row["status"],
                    "idempotency_key": key,
                    "created_at": row["created_at"],
                }
            )
    return rows_out


def _to_aware(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _canonical_key(record: dict) -> str:
    from app.task.history.writer import _canonical_record_key

    return _canonical_record_key(record)


def reconcile(since_hours: float | None = None) -> dict[str, Any]:
    json_records = _json_snapshot()
    derived = _derived_snapshot()
    if since_hours is not None:
        threshold = datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)
        derived = [
            row
            for row in derived
            if _to_aware(row.get("created_at")) is None
            or _to_aware(row["created_at"]) >= threshold
        ]

    derived_by_key = {row["idempotency_key"]: row for row in derived}
    missing_derived: list[str] = []
    kind_stats_json: dict[str, int] = {}
    kind_stats_derived: dict[str, int] = {}

    from app.task.history.writer import _derive_task_type

    valid_json_keys: set[str] = set()
    for record in json_records:
        if not isinstance(record, dict):
            continue
        # 沿用主写路径 "images 非空" 语义（`main.get_history_api` 过滤同款）
        images = record.get("images")
        if not (isinstance(images, list) and len(images) > 0):
            continue
        task_type = _derive_task_type(record)
        kind_stats_json[task_type] = kind_stats_json.get(task_type, 0) + 1
        key = f"history:{_canonical_key(record)}"
        valid_json_keys.add(key)
        if key not in derived_by_key:
            missing_derived.append(key)
    extra_derived: list[str] = []
    for row in derived:
        key = row.get("idempotency_key") or ""
        kind = row["task_type"]
        kind_stats_derived[kind] = kind_stats_derived.get(kind, 0) + 1
        if key not in valid_json_keys:
            extra_derived.append(key)

    kinds = sorted(set(kind_stats_json) | set(kind_stats_derived))
    kind_stats = {
        kind: {
            "json": kind_stats_json.get(kind, 0),
            "derived": kind_stats_derived.get(kind, 0),
        }
        for kind in kinds
    }
    return {
        "history_json_count": len(valid_json_keys),
        "derived_count": len(derived),
        "missing_derived": sorted(missing_derived),
        "extra_derived": sorted(extra_derived),
        "kind_stats": kind_stats,
    }


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task PR-4 history reconciliation")
    parser.add_argument(
        "--since",
        type=float,
        default=None,
        help="Only compare derived tasks created within the last <hours>",
    )
    args = parser.parse_args(argv)
    report = reconcile(args.since)
    print(json.dumps(report, ensure_ascii=False, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
