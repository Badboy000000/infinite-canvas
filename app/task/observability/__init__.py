"""`app.task.observability` — 任务 PR-9 · 结构化日志 + 指标骨架。

设计约束
========

1. **不改现有 logger · 新增独立 logger**:`logging.getLogger("app.task.obs")`;
   现有 `logger.info(...)` 保持不变;本 PR 只输出到独立 logger。

2. **结构化字段清单**(治理方案 §任务观测 章节):
   `task_id / node_run_id / provider_task_id / user_id / workspace_id /
   project_id / canvas_id / provider_id / model / attempt / upstream_task_id
   / status / duration_ms / error_category`

3. **指标 counter/gauge/histogram 骨架**:in-memory 累计;导出到 Prometheus
   / 内部 endpoint 由部署与安全专题承接(Issue-J)。

4. **审计事件 AuditService 接线预留**:AuditService 由权限治理专题(PR-9+)
   落地;本 PR 只暴露 emit 接口 · sink 为 no-op(打日志兜底)。

5. **指标命名前缀** `infcvs_task_*` · 与治理方案对齐:
   - `infcvs_task_submitted_total`
   - `infcvs_task_completed_total`
   - `infcvs_task_failed_total`
   - `infcvs_task_duration_ms_bucket`(简易 histogram)
   - `infcvs_task_active_gauge`

6. **P0 密钥零泄漏**:所有 emit_*() 函数只接受白名单字段 · 不吞入完整 Task 对象。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Mapping, Optional


# ---------------------------------------------------------------------------
# 独立 logger · 不污染现有 root logger
# ---------------------------------------------------------------------------

logger = logging.getLogger("app.task.obs")


# ---------------------------------------------------------------------------
# 结构化字段白名单
# ---------------------------------------------------------------------------

# 治理方案 §任务观测 章节:允许写入 log context 的字段名。
_ALLOWED_LOG_FIELDS: frozenset = frozenset({
    "task_id",
    "node_run_id",
    "provider_task_id",
    "user_id",
    "workspace_id",
    "project_id",
    "canvas_id",
    "provider_id",
    "model",
    "attempt",
    "upstream_task_id",
    "status",
    "duration_ms",
    "error_category",
    "error_code",
    "quota_bucket",
    "worker_id",
    "task_type",
})


def emit_structured(
    event: str,
    fields: Mapping[str, object],
    *,
    level: int = logging.INFO,
) -> None:
    """输出结构化日志到 app.task.obs logger。

    - `event`:事件短名(如 `"task.submitted"`,`"task.completed"`)。
    - `fields`:字段字典;未在 _ALLOWED_LOG_FIELDS 中的键会被丢弃(不 raise)。
    - 输出 JSON one-line · 便于 log aggregation 消费。
    """
    safe = {k: v for k, v in fields.items() if k in _ALLOWED_LOG_FIELDS}
    payload = {"event": event, **safe}
    try:
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        line = f"{event} {safe!r}"
    logger.log(level, line)


# ---------------------------------------------------------------------------
# 指标累加器(in-memory · 部署专题接 Prometheus)
# ---------------------------------------------------------------------------


@dataclass
class MetricRegistry:
    """线程安全的 in-memory 指标累加器。

    - counter:自增计数
    - gauge:任意时刻数值(允许增/减)
    - histogram:duration_ms 分桶累计(bucket edges: 100/500/1000/5000/30000ms)
    """

    _counters: dict = field(default_factory=dict)
    _gauges: dict = field(default_factory=dict)
    _histograms: dict = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock)

    _BUCKETS: tuple = (100.0, 500.0, 1000.0, 5000.0, 30000.0)

    def counter_inc(self, name: str, labels: Mapping[str, str] = None) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1

    def gauge_set(self, name: str, value: float, labels: Mapping[str, str] = None) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            self._gauges[key] = value

    def gauge_inc(self, name: str, delta: float = 1.0, labels: Mapping[str, str] = None) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            self._gauges[key] = self._gauges.get(key, 0.0) + delta

    def histogram_observe(
        self,
        name: str,
        value_ms: float,
        labels: Mapping[str, str] = None,
    ) -> None:
        key = (name, _label_key(labels))
        with self._lock:
            hist = self._histograms.setdefault(
                key,
                {"count": 0, "sum": 0.0, "buckets": {b: 0 for b in self._BUCKETS}},
            )
            hist["count"] += 1
            hist["sum"] += value_ms
            for bucket in self._BUCKETS:
                if value_ms <= bucket:
                    hist["buckets"][bucket] += 1

    def snapshot(self) -> dict:
        """快照当前指标 · 供 endpoint / 测试消费。"""
        with self._lock:
            return {
                "counters": {f"{n}|{lk}": v for (n, lk), v in self._counters.items()},
                "gauges": {f"{n}|{lk}": v for (n, lk), v in self._gauges.items()},
                "histograms": {
                    f"{n}|{lk}": dict(h) for (n, lk), h in self._histograms.items()
                },
            }

    def reset(self) -> None:
        """清空所有指标 · 主要用于测试隔离。"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


def _label_key(labels: Optional[Mapping[str, str]]) -> str:
    if not labels:
        return ""
    return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


# 全局单例 · 便于测试隔离时 reset()。
REGISTRY = MetricRegistry()


# ---------------------------------------------------------------------------
# 高层 emit_task_*() 便捷函数(结构化日志 + 指标一体)
# ---------------------------------------------------------------------------


def emit_task_submitted(
    *,
    task_id: str,
    task_type: str,
    provider_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    **extra,
) -> None:
    """任务提交事件 · 结构化日志 + counter_inc。"""
    emit_structured(
        "task.submitted",
        {
            "task_id": task_id,
            "task_type": task_type,
            "provider_id": provider_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            **extra,
        },
    )
    REGISTRY.counter_inc(
        "infcvs_task_submitted_total",
        labels={"task_type": task_type, "provider_id": provider_id or ""},
    )


def emit_task_completed(
    *,
    task_id: str,
    task_type: str,
    status: str,
    duration_ms: float,
    error_category: Optional[str] = None,
    **extra,
) -> None:
    """任务终态事件 · 结构化日志 + counter + histogram。"""
    emit_structured(
        "task.completed",
        {
            "task_id": task_id,
            "task_type": task_type,
            "status": status,
            "duration_ms": duration_ms,
            "error_category": error_category,
            **extra,
        },
    )
    if status == "succeeded":
        REGISTRY.counter_inc(
            "infcvs_task_completed_total",
            labels={"task_type": task_type, "status": status},
        )
    else:
        REGISTRY.counter_inc(
            "infcvs_task_failed_total",
            labels={
                "task_type": task_type,
                "status": status,
                "error_category": error_category or "",
            },
        )
    REGISTRY.histogram_observe(
        "infcvs_task_duration_ms",
        duration_ms,
        labels={"task_type": task_type, "status": status},
    )


def emit_task_active(
    *,
    task_type: str,
    delta: float,
) -> None:
    """活跃任务 gauge 增减 · +1 提交 / -1 完成。"""
    REGISTRY.gauge_inc(
        "infcvs_task_active_gauge",
        delta=delta,
        labels={"task_type": task_type},
    )


# ---------------------------------------------------------------------------
# 时间戳工具(不引入外部依赖)
# ---------------------------------------------------------------------------


def now_ms() -> float:
    """毫秒级时间戳 · monotonic clock 避免系统时钟跳变干扰 duration 计算。"""
    return time.monotonic() * 1000.0


__all__ = [
    "MetricRegistry",
    "REGISTRY",
    "emit_structured",
    "emit_task_active",
    "emit_task_completed",
    "emit_task_submitted",
    "logger",
    "now_ms",
]
