"""RateLimit 骨架(权限 PR-8 · Wave 3-N.8 Batch 4)。

**定位**:per-key 令牌桶速率限制器 · 支持 per-user / per-IP / per-endpoint
多维聚合 · 默认关闭 flag · 不侵入 FastAPI middleware(避免破坏冻结区)。

**当前 PR skeleton 交付**:
- `TokenBucket` 单桶 · 纯 Python `time.monotonic()` · 无外部依赖(如 Redis)。
- `RateLimiter` 多桶 registry · key 派生 helper `derive_rate_key(ctx, endpoint)`。
- 三档默认 policy:`ANONYMOUS_POLICY`(strict)/ `AUTHENTICATED_POLICY`(relax)
  / `SYSTEM_ADMIN_POLICY`(unlimited)。
- 默认关闭 flag `RATE_LIMIT_ENFORCE_ENABLED`(等价旧行为 · 不拦截)。

**GM-16 pre-flight**:`TokenBucket` / `RateLimiter` / `RateLimitPolicy` /
`RateLimitDecision` 全部为新公共符号 · greenfield。

**未来演进**(Wave 3-N.9+ 承接):
- FastAPI middleware / dependency 挂载 · 从 RequestContext 派生 key
- 429 响应统一 handler(带 Retry-After header)
- Redis 后端(多机场景 · 目前单机 in-memory 够用)
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Optional

from app.identity.request_context import RequestContext

__all__ = [
    "RateLimitPolicy",
    "RateLimitDecision",
    "TokenBucket",
    "RateLimiter",
    "ANONYMOUS_POLICY",
    "AUTHENTICATED_POLICY",
    "SYSTEM_ADMIN_POLICY",
    "derive_rate_key",
    "is_enforce_enabled",
]


# ---------------------------------------------------------------------------
# Policy · 令牌桶参数封装
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitPolicy:
    """令牌桶策略(frozen · 稳定 equality)。

    - `capacity`:桶容量 · 也是 burst 上限。0 = 禁用(所有请求拒绝)。
    - `refill_per_second`:每秒 refill 令牌数 · float 支持小数。
    - `enabled`:策略级开关 · False 时所有请求通过。
    """

    capacity: int
    refill_per_second: float
    enabled: bool = True


# 默认 3 档策略(与治理方案 §RateLimit 对齐)
ANONYMOUS_POLICY = RateLimitPolicy(capacity=20, refill_per_second=0.5)
"""匿名用户:20 burst / 0.5 rps ≈ 30 req/min"""

AUTHENTICATED_POLICY = RateLimitPolicy(capacity=120, refill_per_second=2.0)
"""认证用户:120 burst / 2 rps ≈ 120 req/min"""

SYSTEM_ADMIN_POLICY = RateLimitPolicy(
    capacity=1, refill_per_second=1.0, enabled=False
)
"""system_admin:不限流(enabled=False 恒放行)"""


# ---------------------------------------------------------------------------
# Decision · 单次限流决策结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RateLimitDecision:
    """限流决策结果(frozen · 稳定 equality)。

    - `allowed`:True = 请求通过 · False = 应拒绝(429)。
    - `retry_after_seconds`:被拒绝时的建议 Retry-After 秒数(下一 refill 时机)。
      allowed=True 时 = 0.0。
    - `tokens_remaining`:桶内剩余令牌数(允许时)· 用于告警观测。
    - `key`:命中的限流 key(便于日志追踪)。
    """

    allowed: bool
    retry_after_seconds: float = 0.0
    tokens_remaining: float = 0.0
    key: str = ""


# ---------------------------------------------------------------------------
# TokenBucket · 单桶实现
# ---------------------------------------------------------------------------


class TokenBucket:
    """线程安全令牌桶(纯 Python · 无外部依赖)。

    - `time.monotonic()` 无时钟回拨风险(与 wall-clock 独立)。
    - 单锁保 refill + consume 原子。
    - 首次初始化 = 满桶(避免冷启动误伤)。
    """

    def __init__(self, policy: RateLimitPolicy, *, clock=time.monotonic) -> None:
        self._policy = policy
        self._clock = clock
        self._tokens: float = float(policy.capacity)
        self._last_refill: float = clock()
        self._lock = threading.Lock()

    def try_consume(self, tokens: int = 1) -> RateLimitDecision:
        """尝试消耗 `tokens` 令牌 · 原子操作。

        - policy.enabled=False → 恒 allowed=True(旁路)
        - refill 到当前时间 · 消耗成功后返回 tokens_remaining
        - 令牌不足 → 计算下一次可用时机作为 retry_after_seconds
        """
        if not self._policy.enabled:
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0.0,
                tokens_remaining=float(self._policy.capacity),
            )

        with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._last_refill)
            refilled = elapsed * self._policy.refill_per_second
            self._tokens = min(
                float(self._policy.capacity), self._tokens + refilled
            )
            self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                return RateLimitDecision(
                    allowed=True,
                    retry_after_seconds=0.0,
                    tokens_remaining=self._tokens,
                )
            # 令牌不足 · 计算下一次可用
            deficit = tokens - self._tokens
            if self._policy.refill_per_second <= 0:
                retry_after = float("inf")
            else:
                retry_after = deficit / self._policy.refill_per_second
            return RateLimitDecision(
                allowed=False,
                retry_after_seconds=retry_after,
                tokens_remaining=self._tokens,
            )


# ---------------------------------------------------------------------------
# RateLimiter · 多桶 registry
# ---------------------------------------------------------------------------


class RateLimiter:
    """多桶 registry · 按 key 派生并复用 TokenBucket。

    - 按 key 惰性创建 bucket · 相同 key 复用同一实例(令牌状态持续)。
    - 支持 per-policy 派生:同一 key 不同 policy 视为不同桶(rarely used)。
    - 无过期回收:治理期骨架不做 · 生产切 Redis 时承接。
    """

    def __init__(self, *, clock=time.monotonic) -> None:
        self._buckets: Dict[str, TokenBucket] = {}
        self._clock = clock
        self._lock = threading.Lock()

    def check(self, key: str, policy: RateLimitPolicy) -> RateLimitDecision:
        """检查 key 是否可通过 policy 限流 · 消耗 1 令牌。"""
        bucket = self._get_or_create(key, policy)
        decision = bucket.try_consume(1)
        # 补上 key 供 caller 观测
        return RateLimitDecision(
            allowed=decision.allowed,
            retry_after_seconds=decision.retry_after_seconds,
            tokens_remaining=decision.tokens_remaining,
            key=key,
        )

    def _get_or_create(
        self, key: str, policy: RateLimitPolicy
    ) -> TokenBucket:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(policy, clock=self._clock)
                self._buckets[key] = bucket
            return bucket

    def reset(self, key: Optional[str] = None) -> None:
        """测试隔离 · 无参 = 清空全部 · 带参 = 只清该 key。"""
        with self._lock:
            if key is None:
                self._buckets.clear()
            else:
                self._buckets.pop(key, None)

    def bucket_count(self) -> int:
        """当前活跃 bucket 数量(观测)。"""
        with self._lock:
            return len(self._buckets)


# ---------------------------------------------------------------------------
# Key 派生 helper
# ---------------------------------------------------------------------------


def derive_rate_key(
    ctx: RequestContext,
    *,
    endpoint: Optional[str] = None,
) -> str:
    """从 RequestContext 派生 rate limit key。

    优先级:
    1. `principal_kind == "user"` 且 `x_user_id` set → `user:{x_user_id}[:endpoint]`
    2. `principal_kind == "session"` 且 `legacy_user_key` set →
       `session:{legacy_user_key}[:endpoint]`
    3. `ip` set → `ip:{ip}[:endpoint]`
    4. fallback → `anonymous[:endpoint]`

    endpoint 可选 · 传入即 key 后缀 `:endpoint`(scope 到接口)· 不传则全局。
    """
    if ctx.principal_kind == "user" and ctx.x_user_id:
        base = f"user:{ctx.x_user_id}"
    elif ctx.principal_kind == "session" and ctx.legacy_user_key:
        base = f"session:{ctx.legacy_user_key}"
    elif ctx.ip:
        base = f"ip:{ctx.ip}"
    else:
        base = "anonymous"
    if endpoint:
        return f"{base}:{endpoint}"
    return base


# ---------------------------------------------------------------------------
# 环境 flag(默认关闭 · GM-22 pattern 复用)
# ---------------------------------------------------------------------------

_TRUTHY: FrozenSet[str] = frozenset({"1", "true", "yes", "on"})
_ENV_FLAG = "RATE_LIMIT_ENFORCE_ENABLED"


def is_enforce_enabled() -> bool:
    """读取 `RATE_LIMIT_ENFORCE_ENABLED` env flag(默认 false)。"""
    raw = os.environ.get(_ENV_FLAG, "").strip().lower()
    return raw in _TRUTHY


# 全局默认 RateLimiter(消费方可 import · 也可注入自定义实例做测试)
DEFAULT_RATE_LIMITER = RateLimiter()
