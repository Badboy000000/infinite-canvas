"""`app.task.history.reader` — History 读兼容层。

`GET /api/history` 读路径**不切**（仍走 `history_store.snapshot()` /
`main.get_history_api`）。本模块只提供 `read_history_compat()` 内部辅助工具，
把 `history.json` 结果与 Task/Artifact 派生副本合并生成一个统一读兼容视图，
供对账 CLI / 内部诊断使用。

关键契约：

- `TASK_HISTORY_ENABLE=false`（默认）时**只**返回 `history.json` snapshot 的
  条目，shape 与 `GET /api/history` byte-equivalent（不追加任何派生字段）。
- 开启时在原 record 上追加派生字段（`derived_task_id / derived_artifact_ids
  / node_run_id` 等），旧字段全部保留。
"""

from __future__ import annotations

import logging
from typing import Any, List, Mapping, Optional

logger = logging.getLogger(__name__)


def _augment_with_derived(records: List[dict], *, writer=None) -> List[dict]:
    """开启时在 record 上追加派生字段；关闭时原样返回。

    追加字段 shape：
    - `derived_task_id`: str | None（`Task.id.hex`；来自 idempotency_key 映射）
    - `derived_artifact_ids`: list[str]（`Artifact.id.hex`；按 image url 匹配）
    - `derived_provider_task_id`: str | None
    """

    from app.task.history.writer import (
        _canonical_record_key,
        get_history_writer,
        is_history_writer_enabled,
    )

    if not is_history_writer_enabled():
        return records
    try:
        w = writer or get_history_writer()
        if not w._ensure_ready():
            return records
        task_store = w.task_store()
        artifact_store = w.artifact_store()
    except Exception as exc:  # pragma: no cover — degraded path
        logger.warning("history reader augment init failed: %s", exc)
        return records

    for record in records:
        try:
            key = _canonical_record_key(record)
            task = task_store.get_by_idempotency_key(f"history:{key}")
            if task is None:
                continue
            record["derived_task_id"] = task.id.hex
            artifacts = artifact_store.list_by_task(task.id)
            record["derived_artifact_ids"] = [a.id.hex for a in artifacts]
        except Exception as exc:  # pragma: no cover — degraded path
            logger.warning(
                "history reader augment record failed: %s", exc,
            )
            continue
    return records


def read_history_compat(
    *,
    filter_type: Optional[str] = None,
    writer=None,
) -> List[dict]:
    """从 `history.json` snapshot 读全量 history 项；未启用派生时字段与
    `GET /api/history` byte-equivalent。

    Args:
        filter_type: 若非 None，只返回 `record["type"] == filter_type` 的项
            （沿用 `main.get_history_api` 的 `type` 过滤语义）。
        writer: 供测试注入的 HistoryWriter 实例；缺省用进程级单例。
    """

    from app.stores.history_store import snapshot

    payload = snapshot()
    raw_records = payload.get("payload") or []
    # 沿用 `main.get_history_api` 的过滤 + 排序语义（byte-equivalent shape）
    items: List[dict] = []
    for entry in raw_records:
        if not isinstance(entry, dict):
            continue
        images = entry.get("images")
        if not (isinstance(images, list) and len(images) > 0):
            continue
        if filter_type is not None:
            if entry.get("type", "zimage") != filter_type:
                continue
        items.append(dict(entry))

    def _sort_key(item: Mapping[str, Any]) -> float:
        ts = item.get("timestamp", 0)
        if isinstance(ts, (int, float)):
            return float(ts)
        return 0.0

    items.sort(key=_sort_key, reverse=True)
    return _augment_with_derived(items, writer=writer)


__all__ = ["read_history_compat"]
