"""`app.task.policy` — 任务 PR-7 · RetryPolicy + CostPolicy 骨架。

设计约束
========

1. **默认关闭 · 不接入调用点**:PR-7 只交付纯函数骨架 · 不改 TaskService /
   InProcessWorker · 不改任何 main.py 路由 · retry_decision(...) 默认返回
   `allow=False`(等价"不自动重试")。

2. **RetryPolicy 输入契约**:`(task_context, error, attempt, cost_estimate)` →
   `RetryDecision(next_after, next_attempt, allow, reason)`

3. **CostPolicy 输入契约**:`(task_context, cost_estimate)` →
   `CostCheckResult(allow, remaining_budget, reason)`

4. **策略等价"不自动重试"** · 图片类默认 max_attempts=1(单次)· 视频/CLI/高价
   模型 max_attempts=1 · 未来通过 feature flag 逐 provider 开启。

5. **TaskErrorCategory 映射到 retryable** · 按治理方案 [[任务模型与后台任务治理方案]]
   §错误分类章节 · category → default_retry_allowed 派生。

治理沉淀
========

- **GM-16 pre-flight 通过**:`RetryPolicy / CostPolicy / RetryDecision /
  CostCheckResult` 均为新公共符号 · codegraph 已确认 zero conflict。
- **KNOWN LIMITATION**:cost_estimate 单位与 quota_bucket 定义归 Issue-C 立项
  评审 · 本 PR 只定义字段 · 不做 cost 计算逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

from app.task.view.error_category import TaskErrorCategory


# ---------------------------------------------------------------------------
# TaskErrorCategory → default retryable 派生
# ---------------------------------------------------------------------------

# 治理方案 §错误分类章节:
# - rate_limit / timeout / upstream_5xx / network_error / unknown_recoverable
#   → 默认可重试(需 policy 允许 + attempt 未耗尽)
# - invalid_credential / invalid_input / quota_exceeded / content_moderation
#   / resource_not_found / cancelled_by_user / cancelled_by_upstream
#   / partial_success / unknown_terminal → 默认不可重试
_RETRYABLE_CATEGORIES: frozenset = frozenset({
    TaskErrorCategory.rate_limit,
    TaskErrorCategory.timeout,
    TaskErrorCategory.upstream_5xx,
    TaskErrorCategory.network_error,
    TaskErrorCategory.unknown_recoverable,
})


def category_default_retryable(category: Optional[TaskErrorCategory]) -> bool:
    """按 TaskErrorCategory 派生默认 retryable 布尔。

    - 未知 category(None)→ False(保守兜底)
    - 未来通过 provider-specific 覆盖(如 jimeng CLI 特殊)
    """
    if category is None:
        return False
    return category in _RETRYABLE_CATEGORIES


# ---------------------------------------------------------------------------
# RetryPolicy 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskContext:
    """RetryPolicy / CostPolicy 输入上下文快照。

    - 不包含 Task 对象本体(避免循环 import)· 只带查询决策所需字段。
    - workspace_id / project_id / user_id 为未来预算配额准备(Issue-C 承接)。
    """

    task_id: str
    task_type: str
    provider_id: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    quota_bucket: Optional[str] = None


@dataclass(frozen=True)
class TaskError:
    """RetryPolicy 输入错误信息。

    - category 复用 [[app.task.view.error_category.TaskErrorCategory]] 14 值。
    - retry_after_hint 上游明确 `Retry-After` 头时置为具体秒数;None 表示无提示。
    """

    category: Optional[TaskErrorCategory]
    code: Optional[str] = None
    message: Optional[str] = None
    retry_after_hint_sec: Optional[float] = None


@dataclass(frozen=True)
class RetryDecision:
    """RetryPolicy 决策输出。

    - allow=True 时 next_after / next_attempt 必须有效。
    - allow=False 时(默认路径)next_after=None / next_attempt=当前 attempt。
    - reason 供审计事件 payload_json 记录。
    """

    allow: bool
    next_after: Optional[datetime] = None
    next_attempt: int = 0
    reason: str = ""


@dataclass(frozen=True)
class RetryPolicy:
    """RetryPolicy 主入口。

    默认行为 = "不自动重试" · 所有 provider 走 max_attempts=1。
    未来通过 feature flag(env 或 task_type 白名单)开启逐 provider 重试。

    - `enabled_task_types`:允许自动重试的 task_type 集合(如 {"image","comfy"})
    - `max_attempts_by_type`:按 task_type 覆盖 max_attempts(如 image=2, video=1)
    - `base_backoff_sec` / `max_backoff_sec`:指数退避基础/上限。
    """

    enabled_task_types: frozenset = field(default_factory=frozenset)
    max_attempts_by_type: Mapping[str, int] = field(default_factory=dict)
    base_backoff_sec: float = 5.0
    max_backoff_sec: float = 300.0

    def decide(
        self,
        context: TaskContext,
        error: TaskError,
        attempt: int,
    ) -> RetryDecision:
        """按 (context, error, attempt) 决策是否重试。

        默认路径:allow=False(等价旧行为)。
        """
        if context.task_type not in self.enabled_task_types:
            return RetryDecision(
                allow=False,
                next_attempt=attempt,
                reason=f"task_type {context.task_type!r} not in enabled set",
            )

        max_attempts = self.max_attempts_by_type.get(context.task_type, 1)
        if attempt >= max_attempts:
            return RetryDecision(
                allow=False,
                next_attempt=attempt,
                reason=f"attempts exhausted ({attempt}/{max_attempts})",
            )

        if not category_default_retryable(error.category):
            return RetryDecision(
                allow=False,
                next_attempt=attempt,
                reason=f"category {error.category!r} not retryable by default",
            )

        # 上游 Retry-After 提示优先;否则指数退避 min(base * 2^attempt, max)。
        if error.retry_after_hint_sec is not None:
            delay = min(error.retry_after_hint_sec, self.max_backoff_sec)
        else:
            delay = min(
                self.base_backoff_sec * (2 ** attempt),
                self.max_backoff_sec,
            )

        return RetryDecision(
            allow=True,
            next_after=datetime.now(timezone.utc) + timedelta(seconds=delay),
            next_attempt=attempt + 1,
            reason=f"retry {attempt + 1}/{max_attempts} after {delay:.1f}s",
        )


# ---------------------------------------------------------------------------
# CostPolicy 数据模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CostCheckResult:
    """CostPolicy 决策输出。

    - allow=True 时任务可提交/重试。
    - allow=False 时 reason 必须说明拒绝原因(用户预算耗尽 / 单任务超阈值等)。
    """

    allow: bool
    remaining_budget: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class CostPolicy:
    """CostPolicy 主入口。

    默认行为 = 全通过(allow=True) · 未接入实际预算数据源。
    未来通过 quota_bucket 查询 · 与 Issue-C 立项评审对齐。

    - `per_task_ceiling`:单任务成本上限(None=不限)
    - `per_bucket_daily_ceiling`:quota_bucket 单日累计上限(None=不限)
    """

    per_task_ceiling: Optional[float] = None
    per_bucket_daily_ceiling: Optional[float] = None

    def check(
        self,
        context: TaskContext,
        cost_estimate: Optional[float],
    ) -> CostCheckResult:
        """按 (context, cost_estimate) 检查是否允许提交/重试。

        默认路径:allow=True(等价"不做 cost 拦截")。
        """
        if cost_estimate is None:
            return CostCheckResult(allow=True, reason="cost_estimate unknown")

        if self.per_task_ceiling is not None and cost_estimate > self.per_task_ceiling:
            return CostCheckResult(
                allow=False,
                reason=(
                    f"cost {cost_estimate:.4f} exceeds per-task ceiling "
                    f"{self.per_task_ceiling:.4f}"
                ),
            )

        # per_bucket_daily_ceiling 需要外部数据源支持(Issue-C 承接)
        # 本 PR 只暴露字段 · 不做实际累加查询。
        return CostCheckResult(allow=True, remaining_budget=None)


# ---------------------------------------------------------------------------
# 默认策略实例(等价"不自动重试 + 不做 cost 拦截")
# ---------------------------------------------------------------------------

DEFAULT_RETRY_POLICY = RetryPolicy()
DEFAULT_COST_POLICY = CostPolicy()


__all__ = [
    "CostCheckResult",
    "CostPolicy",
    "DEFAULT_COST_POLICY",
    "DEFAULT_RETRY_POLICY",
    "RetryDecision",
    "RetryPolicy",
    "TaskContext",
    "TaskError",
    "category_default_retryable",
]
