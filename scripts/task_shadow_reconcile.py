"""`scripts/task_shadow_reconcile.py` — 任务 PR-3 对账 CLI。

对账 `CANVAS_TASKS`（进程内 dict）与影子 SQLite Task 事实层。稳定 JSON
输出，供 CI / 手工 diff 使用。

用法：
    python scripts/task_shadow_reconcile.py [--since <hours>]

输出（键顺序稳定）：
    {
      "canvas_tasks_count": N,
      "shadow_tasks_count": M,
      "missing_shadow": [...canvas task IDs 未在影子层出现...],
      "extra_shadow": [...影子层有、但 CANVAS_TASKS 无的 idempotency_key...],
      "kind_stats": { "online-image": {"canvas": .., "shadow": ..}, ... }
    }

限制：
- 需先启动主进程（`CANVAS_TASKS` 在进程内存中）；本 CLI 通过
  `from main import CANVAS_TASKS` 拉取快照，因此 CLI 与主进程需同一
  Python 环境。用于本地对账 / e2e 校验。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _canvas_snapshot() -> dict[str, dict[str, Any]]:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import main  # noqa: WPS433 — 本 CLI 明确依赖主进程

    with main.CANVAS_TASK_LOCK:
        return {tid: dict(rec) for tid, rec in main.CANVAS_TASKS.items()}


def _shadow_snapshot():
    from app.db.engine import run_migrations
    from app.task.store import sqlite_stores

    run_migrations("head")
    task_store, _, _, _, _ = sqlite_stores()
    # 兼容 in-memory / sqlite：scan 全量（治理期规模有限）
    from app.task.contracts import RecoveryFilter

    tasks: list = []
    # scan 只覆盖 RECOVERABLE_TASK_STATUSES；此处补一个全状态遍历，
    # 治理期直接借用 store 内部会话读全量 tasks 表。
    from sqlalchemy import select

    from app.db.session import get_session
    from app.task.tables import tasks as tasks_table

    with get_session() as session:
        rows = session.execute(select(tasks_table)).mappings().all()
        for row in rows:
            tasks.append(
                {
                    "id": str(row["id"]),
                    "task_type": row["task_type"],
                    "status": row["status"],
                    "idempotency_key": row["idempotency_key"],
                    "created_at": row["created_at"],
                }
            )
    return tasks


def reconcile(since_hours: float | None = None) -> dict[str, Any]:
    canvas = _canvas_snapshot()
    shadow = _shadow_snapshot()
    threshold: datetime | None = None
    if since_hours is not None:
        threshold = datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)
        shadow = [row for row in shadow if _to_aware(row.get("created_at")) is None or _to_aware(row["created_at"]) >= threshold]

    shadow_by_key = {row["idempotency_key"]: row for row in shadow if row.get("idempotency_key")}
    missing_shadow: list[str] = []
    kind_stats_canvas: dict[str, int] = {}
    kind_stats_shadow: dict[str, int] = {}
    for tid, rec in sorted(canvas.items()):
        kind = rec.get("type") or "unknown"
        kind_stats_canvas[kind] = kind_stats_canvas.get(kind, 0) + 1
        expected_key = f"canvas_task:{tid}"
        if expected_key not in shadow_by_key:
            missing_shadow.append(tid)
    canvas_keys = {f"canvas_task:{tid}" for tid in canvas}
    extra_shadow: list[str] = []
    for row in shadow:
        key = row.get("idempotency_key") or ""
        kind = row["task_type"]
        kind_stats_shadow[kind] = kind_stats_shadow.get(kind, 0) + 1
        if key.startswith("canvas_task:") and key not in canvas_keys:
            extra_shadow.append(key)
    kinds = sorted(set(kind_stats_canvas) | set(kind_stats_shadow))
    kind_stats = {
        kind: {
            "canvas": kind_stats_canvas.get(kind, 0),
            "shadow": kind_stats_shadow.get(kind, 0),
        }
        for kind in kinds
    }
    return {
        "canvas_tasks_count": len(canvas),
        "shadow_tasks_count": len(shadow),
        "missing_shadow": sorted(missing_shadow),
        "extra_shadow": sorted(extra_shadow),
        "kind_stats": kind_stats,
    }


def _to_aware(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task PR-3 shadow reconciliation")
    parser.add_argument(
        "--since",
        type=float,
        default=None,
        help="Only compare shadow tasks created within the last <hours>",
    )
    args = parser.parse_args(argv)
    report = reconcile(args.since)
    print(json.dumps(report, ensure_ascii=False, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main_cli())
