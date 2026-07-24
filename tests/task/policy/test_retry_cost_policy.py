"""任务 PR-7 · RetryPolicy + CostPolicy 骨架测试 · T60-T79 · 20 项参数化。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.task.policy import (
    CostCheckResult,
    CostPolicy,
    DEFAULT_COST_POLICY,
    DEFAULT_RETRY_POLICY,
    RetryDecision,
    RetryPolicy,
    TaskContext,
    TaskError,
    category_default_retryable,
)
from app.task.view.error_category import TaskErrorCategory


# ---------------------------------------------------------------------------
# T60-T64 · category_default_retryable 映射
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category,expected",
    [
        (TaskErrorCategory.rate_limit, True),
        (TaskErrorCategory.timeout, True),
        (TaskErrorCategory.upstream_5xx, True),
        (TaskErrorCategory.network_error, True),
        (TaskErrorCategory.unknown_recoverable, True),
        (TaskErrorCategory.invalid_credential, False),
        (TaskErrorCategory.invalid_input, False),
        (TaskErrorCategory.quota_exceeded, False),
        (TaskErrorCategory.content_moderation, False),
        (TaskErrorCategory.resource_not_found, False),
        (TaskErrorCategory.cancelled_by_user, False),
        (TaskErrorCategory.cancelled_by_upstream, False),
        (TaskErrorCategory.partial_success, False),
        (TaskErrorCategory.unknown_terminal, False),
        (None, False),
    ],
)
def test_T60_category_default_retryable(category, expected):
    """15 分类 → default retryable 派生:5 retryable + 9 not + None → False。"""
    assert category_default_retryable(category) is expected


# ---------------------------------------------------------------------------
# T65-T69 · RetryPolicy 默认路径(等价"不自动重试")
# ---------------------------------------------------------------------------


def test_T65_default_retry_policy_rejects_all():
    """默认 RetryPolicy(enabled_task_types=空)拒绝所有 task_type。"""
    ctx = TaskContext(task_id="t1", task_type="image")
    err = TaskError(category=TaskErrorCategory.timeout)
    decision = DEFAULT_RETRY_POLICY.decide(ctx, err, attempt=0)
    assert decision.allow is False
    assert decision.next_attempt == 0
    assert "not in enabled set" in decision.reason


def test_T66_retry_policy_rejects_disabled_type():
    """仅 image 启用 · video task_type 被拒。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 2},
    )
    ctx = TaskContext(task_id="t1", task_type="video")
    err = TaskError(category=TaskErrorCategory.timeout)
    decision = policy.decide(ctx, err, attempt=0)
    assert decision.allow is False
    assert "video" in decision.reason


def test_T67_retry_policy_rejects_when_attempts_exhausted():
    """attempt=2 · max_attempts=2 → 拒绝(达到上限)。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 2},
    )
    ctx = TaskContext(task_id="t1", task_type="image")
    err = TaskError(category=TaskErrorCategory.timeout)
    decision = policy.decide(ctx, err, attempt=2)
    assert decision.allow is False
    assert "exhausted" in decision.reason


def test_T68_retry_policy_rejects_non_retryable_category():
    """image 启用 · attempt=0 · category=invalid_credential(不可重试)→ 拒绝。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 2},
    )
    ctx = TaskContext(task_id="t1", task_type="image")
    err = TaskError(category=TaskErrorCategory.invalid_credential)
    decision = policy.decide(ctx, err, attempt=0)
    assert decision.allow is False
    assert "not retryable" in decision.reason


def test_T69_retry_policy_allows_retryable_category():
    """image 启用 · attempt=0 · category=timeout → 允许 + 指数退避。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 2},
        base_backoff_sec=5.0,
        max_backoff_sec=60.0,
    )
    ctx = TaskContext(task_id="t1", task_type="image")
    err = TaskError(category=TaskErrorCategory.timeout)
    decision = policy.decide(ctx, err, attempt=0)
    assert decision.allow is True
    assert decision.next_attempt == 1
    assert decision.next_after is not None
    # base * 2^0 = 5.0s → next_after ≈ now + 5s
    delta = (decision.next_after - datetime.now(timezone.utc)).total_seconds()
    assert 4.0 < delta < 6.5


# ---------------------------------------------------------------------------
# T70-T72 · RetryPolicy Retry-After hint 与指数退避
# ---------------------------------------------------------------------------


def test_T70_retry_policy_uses_retry_after_hint():
    """上游 Retry-After=30s 提示 · 优先使用(不走退避)。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 2},
        base_backoff_sec=5.0,
        max_backoff_sec=60.0,
    )
    ctx = TaskContext(task_id="t1", task_type="image")
    err = TaskError(
        category=TaskErrorCategory.rate_limit,
        retry_after_hint_sec=30.0,
    )
    decision = policy.decide(ctx, err, attempt=1)
    assert decision.allow is True
    delta = (decision.next_after - datetime.now(timezone.utc)).total_seconds()
    assert 29.0 < delta < 31.5


def test_T71_retry_policy_clamps_retry_after_hint_to_max():
    """上游 Retry-After=3600s · max_backoff=60s → 被 clamp 到 60s。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 2},
        base_backoff_sec=5.0,
        max_backoff_sec=60.0,
    )
    ctx = TaskContext(task_id="t1", task_type="image")
    err = TaskError(
        category=TaskErrorCategory.rate_limit,
        retry_after_hint_sec=3600.0,
    )
    decision = policy.decide(ctx, err, attempt=0)
    delta = (decision.next_after - datetime.now(timezone.utc)).total_seconds()
    assert 59.0 < delta < 61.5


def test_T72_retry_policy_exponential_backoff_clamped():
    """attempt=10 · base=5s · max=60s → 60s(clamped)。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 100},
        base_backoff_sec=5.0,
        max_backoff_sec=60.0,
    )
    ctx = TaskContext(task_id="t1", task_type="image")
    err = TaskError(category=TaskErrorCategory.timeout)
    decision = policy.decide(ctx, err, attempt=10)
    delta = (decision.next_after - datetime.now(timezone.utc)).total_seconds()
    assert 59.0 < delta < 61.5


# ---------------------------------------------------------------------------
# T73-T76 · CostPolicy 默认与阈值
# ---------------------------------------------------------------------------


def test_T73_default_cost_policy_allows_all():
    """默认 CostPolicy 不做拦截 · 任何 cost 都通过。"""
    ctx = TaskContext(task_id="t1", task_type="image")
    result = DEFAULT_COST_POLICY.check(ctx, cost_estimate=999.0)
    assert result.allow is True


def test_T74_cost_policy_allows_when_estimate_unknown():
    """cost_estimate=None → 通过(未知不拦截)。"""
    policy = CostPolicy(per_task_ceiling=0.1)
    ctx = TaskContext(task_id="t1", task_type="image")
    result = policy.check(ctx, cost_estimate=None)
    assert result.allow is True
    assert "unknown" in result.reason


def test_T75_cost_policy_rejects_over_per_task_ceiling():
    """cost=1.0 · per_task_ceiling=0.5 → 拒绝。"""
    policy = CostPolicy(per_task_ceiling=0.5)
    ctx = TaskContext(task_id="t1", task_type="image")
    result = policy.check(ctx, cost_estimate=1.0)
    assert result.allow is False
    assert "exceeds" in result.reason


def test_T76_cost_policy_allows_within_ceiling():
    """cost=0.4 · per_task_ceiling=0.5 → 允许。"""
    policy = CostPolicy(per_task_ceiling=0.5)
    ctx = TaskContext(task_id="t1", task_type="image")
    result = policy.check(ctx, cost_estimate=0.4)
    assert result.allow is True


# ---------------------------------------------------------------------------
# T77-T79 · 契约 sentinel(GM-16 pre-flight + P0 密钥零泄漏)
# ---------------------------------------------------------------------------


def test_T77_default_policies_are_singletons():
    """DEFAULT_RETRY_POLICY / DEFAULT_COST_POLICY 是 frozen dataclass 单例。"""
    assert isinstance(DEFAULT_RETRY_POLICY, RetryPolicy)
    assert isinstance(DEFAULT_COST_POLICY, CostPolicy)
    # frozen dataclass 不允许字段赋值
    with pytest.raises((AttributeError, TypeError)):
        DEFAULT_RETRY_POLICY.base_backoff_sec = 999.0


def test_T78_task_context_frozen():
    """TaskContext 是 frozen dataclass · 抗回归。"""
    ctx = TaskContext(task_id="t1", task_type="image")
    with pytest.raises((AttributeError, TypeError)):
        ctx.task_id = "t2"


def test_T79_retry_decision_reason_no_secret_leak():
    """P0 密钥零泄漏 · reason 字段不含 9 sentinel 中任一 case-insensitive 命中。"""
    policy = RetryPolicy(
        enabled_task_types=frozenset({"image"}),
        max_attempts_by_type={"image": 2},
    )
    ctx = TaskContext(
        task_id="t1",
        task_type="image",
        provider_id="secret_provider",
    )
    err = TaskError(
        category=TaskErrorCategory.invalid_credential,
        message="sk-abc api_key=xxx Bearer yyy",
    )
    decision = policy.decide(ctx, err, attempt=0)
    reason_lower = decision.reason.lower()
    # reason 只应包含 category 名 · 不 echo error.message
    for sentinel in (
        "api_key",
        "access_token",
        "secret",
        "bearer",
        "refresh_token",
        "authorization",
        "x-api-key",
        "client_secret",
        "sk-",
    ):
        assert sentinel not in reason_lower, (
            f"policy.reason leaked sentinel {sentinel!r}: {decision.reason!r}"
        )
