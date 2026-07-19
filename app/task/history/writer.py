"""`app.task.history.writer` — 任务 PR-4 History writer 实现。

从 Task 终态 `save_to_history(record)` 主写路径**旁边**派生写入 Task /
Artifact 副本到 SQLite 事实层；`history.json` 主写路径完全不变。

设计约束：

- 不依赖 FastAPI / 路由；只依赖 `app.task.service` + `app.task.store`。
- feature flag `TASK_HISTORY_ENABLE`（默认 `false`；`{1, true, yes, on,
  enable, enabled}` truthy 集合，与 `TASK_SHADOW_ENABLE` 对齐）。
- 惰性构造 SQLite Store 五件套 + 三个 Service；构造前 `run_migrations("head")`
  兜底 baseline 5 张任务表 + 9 张 baseline 表。
- 幂等：`record["task_id"]` 若命中现存 Task（`idempotency_key=history:<hash>`
  / 缓存映射）则复用；`ProviderTask` 副本走 `(provider_id, upstream_task_id)`
  复用；`Artifact` 每个 image URL 一条，重入按 URL 集合去重（缓存映射）。
- 失败隔离：任何异常仅 warning，绝不 raise 到 `save_to_history` 主路径。
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from typing import Any, Iterable, Mapping, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


_TRUTHY = frozenset({"1", "true", "yes", "on", "enable", "enabled"})


def is_history_writer_enabled() -> bool:
    """读取 `TASK_HISTORY_ENABLE` env；默认关闭。"""

    value = os.environ.get("TASK_HISTORY_ENABLE", "")
    return value.strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# 派生字段抽取器
# ---------------------------------------------------------------------------

# `history.json` record 主 kind 到治理方案 `task_type` 的映射。history record
# 的 `type` 字段字面量取自 `main.py` 3 处派生挂钩点上下文：
#   - `build_online_image_result` → "online"
#   - `query_image_task` (RunningHub 成功分支) → "online"
#   - `query_image_task` (通用 image 分支) → "online"
# 治理方案侧对应 `online-image` 任务类型。未映射字面量走 fallback
# `task_type=record["type"]` 直接透传（string 已 canonical）。
_HISTORY_TYPE_TO_TASK_TYPE: Mapping[str, str] = {
    "online": "online-image",
    "angle": "online-image",
    "zimage": "comfy-workflow",
    "runninghub": "runninghub-workflow",
    "video": "online-video",
}


def _derive_task_type(record: Mapping[str, Any]) -> str:
    kind = str(record.get("type") or "").strip() or "unknown"
    return _HISTORY_TYPE_TO_TASK_TYPE.get(kind, kind)


def _iter_image_items(record: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    """从 history record 抽取 image items（含 url / mime 等元数据）。"""

    items = record.get("image_items")
    if isinstance(items, list) and items:
        for entry in items:
            if isinstance(entry, dict) and entry.get("url"):
                yield entry
        return
    images = record.get("images")
    if isinstance(images, list):
        for url in images:
            if url:
                yield {"url": url}


def _canonical_record_key(record: Mapping[str, Any]) -> str:
    """稳定摘要 key —— 用于二次写幂等命中缓存映射。"""

    upstream_task_id = record.get("task_id")
    request_id = record.get("request_id")
    ts = record.get("timestamp")
    ident = "|".join(str(x) for x in (upstream_task_id, request_id, ts))
    return hashlib.sha1(ident.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class HistoryWriter:
    """惰性初始化的 History 派生写副本器。构造失败退化为 no-op。"""

    def __init__(self) -> None:
        self._task_service = None
        self._node_run_service = None
        self._task_store = None
        self._event_store = None
        self._provider_task_store = None
        self._provider_task_service = None
        self._artifact_store = None
        self._by_record_key: dict[str, UUID] = {}
        self._lock = threading.RLock()
        self._initialised = False
        self._broken = False

    # ---- lazy init ----
    def _ensure_ready(self) -> bool:
        if self._initialised:
            return not self._broken
        with self._lock:
            if self._initialised:
                return not self._broken
            try:
                from app.db.engine import run_migrations
                from app.task.service import (
                    NodeRunService,
                    ProviderTaskService,
                    TaskService,
                )
                from app.task.store import sqlite_stores

                run_migrations("head")
                (
                    task_store,
                    node_run_store,
                    provider_task_store,
                    event_store,
                    artifact_store,
                ) = sqlite_stores()
                self._task_store = task_store
                self._event_store = event_store
                self._provider_task_store = provider_task_store
                self._artifact_store = artifact_store
                self._task_service = TaskService(task_store, event_store)
                self._provider_task_service = ProviderTaskService(
                    task_store, provider_task_store, event_store
                )
                self._node_run_service = NodeRunService(
                    task_store, node_run_store, event_store
                )
                self._broken = False
            except Exception as exc:  # pragma: no cover — degraded path
                logger.warning(
                    "history writer init failed; disabling history writes: %s",
                    exc,
                )
                self._broken = True
            self._initialised = True
            return not self._broken

    # ---- write API ----
    def write_from_task(
        self,
        task_snapshot: Any = None,
        artifacts: Optional[Iterable[Any]] = None,
        *,
        source_record: Optional[Mapping[str, Any]] = None,
    ) -> Optional[UUID]:
        """从 Task 终态派生 History 副本；`source_record` 是 `history.json`
        主写路径正在写入的 `record` dict。

        返回派生 Task UUID；未启用 / 失败 / 空 record 返回 `None`。
        **幂等**：`source_record` 二次进入返回缓存的 Task id。
        """

        if not is_history_writer_enabled():
            return None
        try:
            if not self._ensure_ready():
                return None
            if source_record is None:
                # 无 record 时不做任何事（主要接口是从 save_to_history
                # 主写路径旁挂钩，record 必然存在）。
                return None
            return self._write_derived(source_record)
        except Exception as exc:
            logger.warning(
                "history write_from_task failed: %s", exc,
            )
            return None

    # ---- internal ----
    def _write_derived(self, record: Mapping[str, Any]) -> Optional[UUID]:
        from app.task.contracts import (
            ArtifactDraft,
            ProviderTaskDraft,
            TaskDraft,
        )

        key = _canonical_record_key(record)
        with self._lock:
            cached = self._by_record_key.get(key)
            if cached is not None:
                return cached

            provider_id = record.get("provider_id")
            model = record.get("model")
            task_type = _derive_task_type(record)
            input_snapshot: dict[str, Any] = {}
            if isinstance(record.get("prompt"), str) and record["prompt"]:
                input_snapshot["prompt"] = record["prompt"]
            params = record.get("params")
            if isinstance(params, Mapping):
                input_snapshot["params"] = dict(params)

            # Task 影子副本：直接 create 已完成的 succeeded Task（treated as
            # 补写；不参与 worker/lease；不合成事件序列——治理期 History 副本
            # 表达"用户可见结果流水"，不表达任务时间线）。
            draft = TaskDraft(
                task_type=str(task_type),
                status="succeeded",
                idempotency_key=f"history:{key}",
                provider_id=str(provider_id) if provider_id else None,
                model=str(model) if model else None,
                input_snapshot=input_snapshot,
            )
            # 幂等：`idempotency_key` 冲突时 store 会 CAS 冲突或直接命中现存
            existing = self._task_store.get_by_idempotency_key(draft.idempotency_key)
            if existing is not None:
                self._by_record_key[key] = existing.id
                return existing.id
            task = self._task_store.create(draft)
            task_id = task.id
            self._by_record_key[key] = task_id

            # 派生 ProviderTask 副本（若 record 提供了 upstream task_id）
            upstream_task_id = record.get("task_id")
            if provider_id and upstream_task_id:
                try:
                    pt_existing = self._provider_task_store.find_by_upstream(
                        str(provider_id), str(upstream_task_id)
                    )
                    if pt_existing is None:
                        self._provider_task_store.create(
                            ProviderTaskDraft(
                                task_id=task_id,
                                provider_id=str(provider_id),
                                provider_protocol="legacy-history",
                                upstream_task_id=str(upstream_task_id),
                                upstream_task_kind="history_derived",
                                status="succeeded",
                            )
                        )
                except Exception as exc:  # pragma: no cover — degraded path
                    logger.warning(
                        "history write ProviderTask failed (task_id=%s): %s",
                        upstream_task_id,
                        exc,
                    )

            # 派生 Artifact 副本（每个 image url 一条）
            for entry in _iter_image_items(record):
                url = entry.get("url")
                if not url:
                    continue
                try:
                    self._artifact_store.create(
                        ArtifactDraft(
                            kind=str(entry.get("kind") or "image"),
                            task_id=task_id,
                            url=str(url),
                            mime_type=entry.get("mime_type") or entry.get("mime"),
                            name=entry.get("name"),
                            legacy_url=str(url),
                        )
                    )
                except Exception as exc:  # pragma: no cover — degraded path
                    logger.warning(
                        "history write Artifact failed (url=%s): %s", url, exc,
                    )
            return task_id

    # ---- 只读入口（对账 CLI 使用）----
    def task_store(self):
        return self._task_store

    def artifact_store(self):
        return self._artifact_store


# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------

_writer_lock = threading.Lock()
_writer: Optional[HistoryWriter] = None


def get_history_writer() -> HistoryWriter:
    """返回进程级单例 writer。同一进程只 migrate 一次。"""

    global _writer
    if _writer is not None:
        return _writer
    with _writer_lock:
        if _writer is None:
            _writer = HistoryWriter()
    return _writer


def reset_history_writer() -> None:
    """测试 hook：重置进程级 writer。"""

    global _writer
    with _writer_lock:
        _writer = None


# ---------------------------------------------------------------------------
# 顶层 helper（供 `main._history_derive` 转发；测试也能直接调用）
# ---------------------------------------------------------------------------


def write_history_from_task(
    *args: Any,
    record: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> Optional[UUID]:
    """`main._history_derive("write_from_result", record=<record>)` 后端。

    与 `HistoryWriter.write_from_task` 同签名；额外接受 `record=` 关键字，
    转发到 `source_record=`。
    """

    writer = get_history_writer()
    return writer.write_from_task(source_record=record, *args, **kwargs)


def register_history_from_task(*args: Any, **kwargs: Any) -> Optional[UUID]:
    """`write_history_from_task` 别名 —— 保持与 shadow registry 命名对齐。"""

    return write_history_from_task(*args, **kwargs)


__all__ = [
    "HistoryWriter",
    "get_history_writer",
    "is_history_writer_enabled",
    "register_history_from_task",
    "reset_history_writer",
    "write_history_from_task",
]
