"""`app.task.shadow.register` — 影子登记 façade。

暴露一组小 helper（`register_submit` / `register_transition` /
`register_provider_task` / `register_node_run` / `register_release`），
`main.py` 的 6 处 `CANVAS_TASKS` 交互点调用即可完成影子写入。每个入口都
包 `try/except`，把异常吞掉记 `logger.warning`，不再向调用方冒泡。

设计约束：

- 不依赖 FastAPI / 路由；只依赖 `app.task.service` + `app.task.store`。
- feature flag 检查 `TASK_SHADOW_ENABLE`（默认 `false`），检查失败或未启用
  时 helper 全部快速返回 `None`。
- `_ShadowRegistry` 惰性构造 SQLite Store 五件套 + 三个 Service；构造前
  统一 `run_migrations("head")` 确保 5 张任务表 + 9 张 baseline 表就位。
  失败降级：迁移抛异常时 registry 视为 disabled 但保留 warning 记录。
- 幂等：`register_submit` 使用 `canvas_task_id` 作为 `idempotency_key`，
  重复调用返回旧 Task；`register_provider_task` 使用 `find_by_upstream`
  去重同一 `(provider_id, upstream_task_id)` 组合。

参见 [[40 实施计划/任务模型与后台任务治理实施计划与PR清单]] PR-3。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Mapping, Optional
from uuid import UUID

logger = logging.getLogger(__name__)


_TRUTHY = frozenset({"1", "true", "yes", "on", "enable", "enabled"})


def is_shadow_enabled() -> bool:
    """读取 `TASK_SHADOW_ENABLE` env；默认关闭。"""

    value = os.environ.get("TASK_SHADOW_ENABLE", "")
    return value.strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ShadowRegistry:
    """惰性初始化的影子登记器。构造失败退化为 no-op。"""

    def __init__(self) -> None:
        self._task_service = None
        self._provider_task_service = None
        self._node_run_service = None
        self._task_store = None
        self._event_store = None
        self._provider_task_store = None
        self._node_run_store = None
        self._by_canvas_task: dict[str, UUID] = {}
        self._by_canvas_node_run: dict[tuple[str, str], UUID] = {}
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
                task_store, node_run_store, provider_task_store, event_store, _ = (
                    sqlite_stores()
                )
                self._task_store = task_store
                self._event_store = event_store
                self._provider_task_store = provider_task_store
                self._node_run_store = node_run_store
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
                    "shadow registry init failed; disabling shadow writes: %s", exc
                )
                self._broken = True
            self._initialised = True
            return not self._broken

    # ---- 6 处挂钩点入口 ----
    def register_submit(
        self,
        canvas_task_id: str,
        *,
        task_type: str,
        canvas_id: Optional[str] = None,
        node_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
        workflow_id: Optional[str] = None,
        input_snapshot: Optional[Mapping[str, Any]] = None,
    ) -> Optional[UUID]:
        """`POST /api/canvas-*-tasks` 提交时的影子副本写。

        返回 shadow Task UUID；失败或未启用返回 `None`。
        """

        if not is_shadow_enabled():
            return None
        try:
            if not self._ensure_ready():
                return None
            from app.task.contracts import TaskDraft

            with self._lock:
                cached = self._by_canvas_task.get(canvas_task_id)
                if cached is not None:
                    return cached
                draft = TaskDraft(
                    task_type=task_type,
                    status="queued",
                    idempotency_key=f"canvas_task:{canvas_task_id}",
                    canvas_id=canvas_id,
                    node_id=node_id,
                    provider_id=provider_id,
                    model=model,
                    workflow_id=workflow_id,
                    input_snapshot=dict(input_snapshot or {}),
                )
                task = self._task_service.submit(draft)
                self._by_canvas_task[canvas_task_id] = task.id
                return task.id
        except Exception as exc:
            logger.warning(
                "shadow register_submit failed (canvas_task_id=%s): %s",
                canvas_task_id,
                exc,
            )
            return None

    def register_transition(
        self,
        canvas_task_id: str,
        *,
        status: str,
        event_payload: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """轮询驱动的状态跃迁副本；未知 status / 非法转移 warning 隔离。

        影子层不启动 worker，但 Task 状态机严格要求 `queued → leased → running`；
        因此本方法遇到 `running` 目标时先合成一次 `SHADOW_OWNER` 的 lease，
        再切 `running`。终态迁移见 `register_release`。
        """

        if not is_shadow_enabled():
            return
        try:
            if not self._ensure_ready():
                return
            with self._lock:
                task_uuid = self._by_canvas_task.get(canvas_task_id)
                if task_uuid is None:
                    return
                mapped = _CANVAS_TO_TASK_STATUS.get(status)
                if mapped is None:
                    return
                current = self._task_service.query(task_uuid)
                if current.status == mapped:
                    return
                try:
                    self._advance(current, mapped, event_payload=event_payload)
                except Exception as exc:
                    logger.warning(
                        "shadow register_transition rejected (canvas_task_id=%s"
                        " %s->%s): %s",
                        canvas_task_id,
                        current.status,
                        mapped,
                        exc,
                    )
        except Exception as exc:
            logger.warning(
                "shadow register_transition failed (canvas_task_id=%s): %s",
                canvas_task_id,
                exc,
            )

    def register_provider_task(
        self,
        canvas_task_id: str,
        *,
        provider_id: str,
        provider_protocol: str,
        upstream_task_id: str,
        upstream_task_kind: Optional[str] = None,
        capability: Optional[str] = None,
        operation: Optional[str] = None,
        adapter_kind: Optional[str] = None,
    ) -> Optional[UUID]:
        """Provider 侧远端 task ID 可用时登记副本。幂等：
        `(provider_id, upstream_task_id)` 命中现存则复用。
        """

        if not is_shadow_enabled():
            return None
        try:
            if not self._ensure_ready():
                return None
            from app.task.contracts import ProviderTaskDraft

            with self._lock:
                task_uuid = self._by_canvas_task.get(canvas_task_id)
                if task_uuid is None or not upstream_task_id:
                    return None
                existing = self._provider_task_store.find_by_upstream(
                    provider_id, upstream_task_id
                )
                if existing is not None:
                    return existing.id
                draft = ProviderTaskDraft(
                    task_id=task_uuid,
                    provider_id=provider_id,
                    provider_protocol=provider_protocol,
                    upstream_task_id=upstream_task_id,
                    upstream_task_kind=upstream_task_kind,
                    capability=capability,
                    operation=operation,
                    adapter_kind=adapter_kind,
                    status="submitted",
                )
                pt = self._provider_task_service.submit(draft)
                return pt.id
        except Exception as exc:
            logger.warning(
                "shadow register_provider_task failed (canvas_task_id=%s"
                " provider=%s upstream=%s): %s",
                canvas_task_id,
                provider_id,
                upstream_task_id,
                exc,
            )
            return None

    def register_node_run(
        self,
        canvas_task_id: str,
        *,
        canvas_id: str,
        node_id: str,
        node_type: str,
    ) -> Optional[UUID]:
        """节点已在 CANVAS_TASKS 记录时同步登记 NodeRun 副本并 attach。"""

        if not is_shadow_enabled():
            return None
        try:
            if not self._ensure_ready():
                return None
            from app.task.contracts import NodeRunDraft

            with self._lock:
                task_uuid = self._by_canvas_task.get(canvas_task_id)
                if task_uuid is None:
                    return None
                key = (canvas_id, node_id)
                run_id = self._by_canvas_node_run.get(key)
                if run_id is None:
                    run = self._node_run_service.create(
                        NodeRunDraft(
                            canvas_id=canvas_id,
                            node_id=node_id,
                            node_type=node_type,
                        )
                    )
                    run_id = run.id
                    self._by_canvas_node_run[key] = run_id
                self._node_run_service.attach(run_id, [task_uuid])
                return run_id
        except Exception as exc:
            logger.warning(
                "shadow register_node_run failed (canvas_task_id=%s canvas=%s"
                " node=%s): %s",
                canvas_task_id,
                canvas_id,
                node_id,
                exc,
            )
            return None

    def register_release(
        self,
        canvas_task_id: str,
        *,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """完成 / 失败 / 取消时的收尾影子写。

        `TaskService.release` 要求持有租约；此处不启用 worker，直接调
        `_advance` 兼容影子期语义（PR-8 之后再切 lease-owned release）。
        """

        if not is_shadow_enabled():
            return
        target = _CANVAS_TERMINAL_TO_TASK_STATUS.get(status)
        if target is None:
            return
        payload: dict[str, object] = {}
        if error_message:
            payload["error"] = error_message
        try:
            if not self._ensure_ready():
                return
            with self._lock:
                task_uuid = self._by_canvas_task.get(canvas_task_id)
                if task_uuid is None:
                    return
                current = self._task_service.query(task_uuid)
                if current.status == target:
                    return
                if target == "cancelled":
                    # cancel 走 TaskService.cancel（承载 cancel_requested 中间态）
                    self._task_service.cancel(task_uuid)
                    return
                updates: Optional[dict[str, object]] = None
                if error_message:
                    updates = {"error_message": error_message}
                try:
                    self._advance(
                        current, target, updates=updates, event_payload=payload
                    )
                except Exception as exc:
                    logger.warning(
                        "shadow register_release rejected (canvas_task_id=%s"
                        " %s->%s): %s",
                        canvas_task_id,
                        current.status,
                        target,
                        exc,
                    )
        except Exception as exc:
            logger.warning(
                "shadow register_release failed (canvas_task_id=%s): %s",
                canvas_task_id,
                exc,
            )

    # ---- 内部：多步 advance ----
    def _advance(
        self,
        current,
        target: str,
        *,
        updates: Optional[Mapping[str, object]] = None,
        event_payload: Optional[Mapping[str, Any]] = None,
    ):
        """按状态机语义把 `current.status` 推到 `target`。

        影子层没有真实 worker/lease，因此按需合成一次
        `_SHADOW_LEASE_OWNER` 的租约；`running/succeeded/failed` 都以本
        owner 走完全部合法跃迁。
        """

        path = _shortest_path(current.status, target)
        if not path:
            raise TaskShadowTransitionError(
                f"no legal shadow transition path {current.status}->{target}"
            )
        task_uuid = current.id
        for step in path:
            if step == "leased":
                # 合成一次 lease；attempt +1 由 lease() 内部处理。max_attempts
                # 影子期先给个宽松上限，避免 attempt exhaustion。
                if current.max_attempts <= current.attempt:
                    # 抬高 max_attempts（乐观锁 CAS 期望本轮 status）
                    self._task_store.update_with_expected(
                        task_uuid,
                        {"max_attempts": current.attempt + 5},
                        expected={"status": current.status},
                    )
                current = self._task_service.lease(
                    task_uuid, _SHADOW_LEASE_OWNER, ttl_sec=3600
                )
                continue
            step_updates = updates if step == target else None
            step_payload = event_payload if step == target else None
            current = self._task_service.transition(
                task_uuid,
                step,
                updates=step_updates,
                event_payload=step_payload,
            )
        return current

    # ---- 对账工具用到的只读入口 ----
    def snapshot_canvas_task_map(self) -> Mapping[str, UUID]:
        with self._lock:
            return dict(self._by_canvas_task)

    def task_store(self):
        return self._task_store


# ---------------------------------------------------------------------------
# CANVAS_TASKS 状态 → Task 状态映射
# ---------------------------------------------------------------------------

# 现有 CANVAS_TASKS 字典的 `status` 字段字面量取自 `main.py` 6 处交互点。
# 治理期只覆盖影子端可稳定 map 到治理方案 14 态的字面量；未覆盖字面量
# （如 `jimeng_pending`）当前不写副本，PR-4/PR-5 承接。
_CANVAS_TO_TASK_STATUS: Mapping[str, str] = {
    "queued": "queued",
    "running": "running",
    "waiting_upstream": "waiting_upstream",
    "downloading": "downloading",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "cancel_requested": "cancel_requested",
}

_CANVAS_TERMINAL_TO_TASK_STATUS: Mapping[str, str] = {
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}


# 影子层合成的 lease owner；PR-8 之后由真实 worker 名字替换。
_SHADOW_LEASE_OWNER = "shadow-registry@pr3"


class TaskShadowTransitionError(RuntimeError):
    """影子层内部无法找到从 `current` 到 `target` 的合法跃迁路径。"""


def _shortest_path(start: str, goal: str) -> list[str]:
    """BFS：在治理方案状态机上找一条从 `start` 到 `goal` 的最短跃迁序列。

    返回不含 `start` 的目标序列（含 `goal`）。找不到返回空。
    """

    from app.task.service.state_machine import TASK_TRANSITIONS

    if start == goal:
        return []
    frontier: list[tuple[str, list[str]]] = [(start, [])]
    visited = {start}
    while frontier:
        node, trail = frontier.pop(0)
        for nxt in TASK_TRANSITIONS.get(node, frozenset()):
            if nxt in visited:
                continue
            new_trail = trail + [nxt]
            if nxt == goal:
                return new_trail
            visited.add(nxt)
            frontier.append((nxt, new_trail))
    return []


# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------

_registry_lock = threading.Lock()
_registry: Optional[ShadowRegistry] = None


def get_shadow_registry() -> ShadowRegistry:
    """返回进程级单例 registry。同一进程只 migrate 一次。"""

    global _registry
    if _registry is not None:
        return _registry
    with _registry_lock:
        if _registry is None:
            _registry = ShadowRegistry()
    return _registry


def reset_shadow_registry() -> None:
    """测试 hook：重置进程级 registry。"""

    global _registry
    with _registry_lock:
        _registry = None


__all__ = [
    "ShadowRegistry",
    "get_shadow_registry",
    "is_shadow_enabled",
    "reset_shadow_registry",
]
