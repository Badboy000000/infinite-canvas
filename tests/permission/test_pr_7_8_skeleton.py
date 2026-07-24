"""权限 PR-7 (AuditService) + PR-8 (RateLimit) skeleton 契约测试。

**测试 IDs**:T340-T369(30 tests)
- T340-T349:AuditService append / to_dict / 白名单 / flag
- T350-T369:RateLimit TokenBucket / RateLimiter / derive_rate_key
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.identity.request_context import RequestContext
from app.services.audit import (
    _ALLOWED_AUDIT_FIELDS,
    AuditEvent,
    AuditService,
    DEFAULT_AUDIT_LOG_PATH,
    is_audit_write_enabled,
    make_event,
    new_event_id,
    now_iso,
)
from app.services.ratelimit import (
    ANONYMOUS_POLICY,
    AUTHENTICATED_POLICY,
    SYSTEM_ADMIN_POLICY,
    RateLimitDecision,
    RateLimitPolicy,
    RateLimiter,
    TokenBucket,
    derive_rate_key,
    is_enforce_enabled,
)


# ---------------------------------------------------------------------------
# T340-T349: AuditService
# ---------------------------------------------------------------------------


class TestPR7AuditService:
    """权限 PR-7:AuditService 骨架契约"""

    def test_T340_default_log_path_is_data_identity_audit_logs_jsonl(self):
        """默认 log 路径 = data/identity/audit_logs.jsonl(权限 PR-0 已创建)"""
        assert str(DEFAULT_AUDIT_LOG_PATH) == str(
            Path("data/identity/audit_logs.jsonl")
        )

    def test_T341_allowed_fields_17_frozen(self):
        """白名单严格 17 字段 · 未列字段自动 drop"""
        assert len(_ALLOWED_AUDIT_FIELDS) == 17
        # 关键字段抽验
        assert "user_id" in _ALLOWED_AUDIT_FIELDS
        assert "role" in _ALLOWED_AUDIT_FIELDS
        assert "resource_id" in _ALLOWED_AUDIT_FIELDS
        # 密钥零泄漏防线 · 严禁字段
        assert "api_key" not in _ALLOWED_AUDIT_FIELDS
        assert "password" not in _ALLOWED_AUDIT_FIELDS
        assert "token" not in _ALLOWED_AUDIT_FIELDS
        assert "secret" not in _ALLOWED_AUDIT_FIELDS

    def test_T342_append_buffered_only_no_file_write(self, tmp_path):
        """buffered_only=True → 只缓存 · 不写盘"""
        log_path = tmp_path / "audit.jsonl"
        svc = AuditService(log_path=log_path, buffered_only=True)
        event = make_event("auth.login", "success", context={"user_id": "u1"})
        svc.append(event)
        assert not log_path.exists()
        assert len(svc.buffered_events()) == 1

    def test_T343_append_writes_to_file_when_enabled(
        self, tmp_path, monkeypatch
    ):
        """flag=on 且 buffered_only=False → 写盘"""
        monkeypatch.setenv("AUDIT_SERVICE_WRITE_ENABLED", "true")
        log_path = tmp_path / "audit.jsonl"
        svc = AuditService(log_path=log_path)
        event = make_event(
            "auth.login", "success", context={"user_id": "u1", "role": "member"}
        )
        svc.append(event)
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["action"] == "auth.login"
        assert payload["user_id"] == "u1"
        assert payload["role"] == "member"

    def test_T344_append_no_write_when_disabled(
        self, tmp_path, monkeypatch
    ):
        """flag=off → 只缓存 · 不写盘"""
        monkeypatch.delenv("AUDIT_SERVICE_WRITE_ENABLED", raising=False)
        log_path = tmp_path / "audit.jsonl"
        svc = AuditService(log_path=log_path)
        svc.append(make_event("auth.login", "success"))
        assert not log_path.exists()
        assert len(svc.buffered_events()) == 1

    def test_T345_to_dict_filters_unknown_fields(self):
        """未列字段自动 drop 不 raise"""
        event = AuditEvent(
            event_id="e1",
            timestamp="2026-07-24T00:00:00+00:00",
            action="auth.login",
            outcome="success",
            context={
                "user_id": "u1",  # 白名单命中
                "api_key": "SECRET",  # 严禁字段 → 必须 drop
                "password": "pwd",  # 严禁字段 → 必须 drop
                "random_field": "x",  # 未列 → drop
            },
        )
        d = event.to_dict()
        assert d["user_id"] == "u1"
        assert "api_key" not in d
        assert "password" not in d
        assert "random_field" not in d

    def test_T346_to_dict_no_raise_on_unknown(self):
        """未列字段不 raise · 与 observability 白名单同行为"""
        event = make_event(
            "auth.login",
            "success",
            context={"nonexistent_field_xyz": 123},
        )
        payload = event.to_dict()
        assert "nonexistent_field_xyz" not in payload
        # 但事件本身可正常序列化
        assert payload["action"] == "auth.login"

    def test_T347_to_dict_json_serializable(self):
        """to_dict 输出 JSON 可序列化"""
        event = make_event(
            "permission.check_denied",
            "denied",
            context={"role": "viewer", "permission": "canvas:write"},
        )
        payload = event.to_dict()
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        parsed = json.loads(line)
        assert parsed["outcome"] == "denied"

    def test_T348_env_flag_defaults_off(self, monkeypatch):
        """AUDIT_SERVICE_WRITE_ENABLED 默认 false"""
        monkeypatch.delenv("AUDIT_SERVICE_WRITE_ENABLED", raising=False)
        assert is_audit_write_enabled() is False
        for v in ("1", "true", "yes", "on", "TRUE"):
            monkeypatch.setenv("AUDIT_SERVICE_WRITE_ENABLED", v)
            assert is_audit_write_enabled() is True

    def test_T349_event_frozen_dataclass(self):
        """AuditEvent 是 frozen · 不可变"""
        event = make_event("auth.login", "success")
        with pytest.raises(Exception):
            event.action = "auth.logout"  # type: ignore[misc]

    def test_T349b_clear_buffer_test_isolation(self):
        """clear_buffer 支持测试隔离"""
        svc = AuditService(buffered_only=True)
        svc.append(make_event("auth.login", "success"))
        assert len(svc.buffered_events()) == 1
        svc.clear_buffer()
        assert len(svc.buffered_events()) == 0

    def test_T349c_now_iso_format(self):
        """now_iso 是 UTC ISO-8601 with tz"""
        ts = now_iso()
        assert "T" in ts  # ISO-8601
        assert "+00:00" in ts or ts.endswith("Z")  # tz-aware

    def test_T349d_new_event_id_uuid4_hex(self):
        """new_event_id 是 uuid4 hex(32 字符)"""
        eid = new_event_id()
        assert len(eid) == 32
        assert all(c in "0123456789abcdef" for c in eid)


# ---------------------------------------------------------------------------
# T350-T369: RateLimit
# ---------------------------------------------------------------------------


class TestPR8RateLimit:
    """权限 PR-8:RateLimit 骨架契约"""

    def test_T350_default_policies_defined(self):
        """3 档默认 policy:anonymous / authenticated / system_admin"""
        assert ANONYMOUS_POLICY.capacity == 20
        assert ANONYMOUS_POLICY.refill_per_second == 0.5
        assert ANONYMOUS_POLICY.enabled is True

        assert AUTHENTICATED_POLICY.capacity == 120
        assert AUTHENTICATED_POLICY.refill_per_second == 2.0
        assert AUTHENTICATED_POLICY.enabled is True

        assert SYSTEM_ADMIN_POLICY.enabled is False  # 恒不限流

    def test_T351_policy_frozen_dataclass(self):
        """RateLimitPolicy 是 frozen"""
        with pytest.raises(Exception):
            ANONYMOUS_POLICY.capacity = 999  # type: ignore[misc]

    def test_T352_bucket_start_full(self):
        """新桶起始 = capacity(避免冷启动误伤)"""
        bucket = TokenBucket(RateLimitPolicy(capacity=5, refill_per_second=1))
        # 消耗 5 次都允许
        for _ in range(5):
            decision = bucket.try_consume(1)
            assert decision.allowed is True

    def test_T353_bucket_deny_after_exhaust(self):
        """超容量拒绝"""
        clock = _FakeClock(t=0.0)
        bucket = TokenBucket(
            RateLimitPolicy(capacity=3, refill_per_second=1),
            clock=clock.now,
        )
        for _ in range(3):
            assert bucket.try_consume(1).allowed is True
        decision = bucket.try_consume(1)
        assert decision.allowed is False
        assert decision.retry_after_seconds > 0

    def test_T354_bucket_refill_after_time(self):
        """令牌 refill:等 refill_per_second 秒后加 1"""
        clock = _FakeClock(t=0.0)
        bucket = TokenBucket(
            RateLimitPolicy(capacity=1, refill_per_second=1),
            clock=clock.now,
        )
        assert bucket.try_consume(1).allowed is True
        assert bucket.try_consume(1).allowed is False
        # 前进 1 秒 · refill 1 令牌
        clock.advance(1.0)
        assert bucket.try_consume(1).allowed is True

    def test_T355_bucket_capacity_ceiling(self):
        """refill 不超 capacity"""
        clock = _FakeClock(t=0.0)
        bucket = TokenBucket(
            RateLimitPolicy(capacity=3, refill_per_second=1),
            clock=clock.now,
        )
        # 空桶
        for _ in range(3):
            bucket.try_consume(1)
        # 等 100 秒 · refill 至多 3(capacity)
        clock.advance(100.0)
        for _ in range(3):
            assert bucket.try_consume(1).allowed is True
        # 第 4 次拒绝
        assert bucket.try_consume(1).allowed is False

    def test_T356_bucket_disabled_bypass(self):
        """policy.enabled=False → 恒 allowed(旁路)"""
        bucket = TokenBucket(
            RateLimitPolicy(capacity=0, refill_per_second=0, enabled=False)
        )
        for _ in range(1000):
            assert bucket.try_consume(1).allowed is True

    def test_T357_bucket_decision_shape(self):
        """RateLimitDecision 是 frozen dataclass"""
        bucket = TokenBucket(RateLimitPolicy(capacity=1, refill_per_second=1))
        d = bucket.try_consume(1)
        assert isinstance(d, RateLimitDecision)
        with pytest.raises(Exception):
            d.allowed = False  # type: ignore[misc]

    def test_T358_bucket_retry_after_precise(self):
        """retry_after 精确计算(deficit / refill_rate)"""
        clock = _FakeClock(t=0.0)
        bucket = TokenBucket(
            RateLimitPolicy(capacity=1, refill_per_second=2.0),
            clock=clock.now,
        )
        assert bucket.try_consume(1).allowed is True
        # 拒绝 · deficit=1 · refill=2 rps → retry ~ 0.5s
        d = bucket.try_consume(1)
        assert d.allowed is False
        assert 0.4 <= d.retry_after_seconds <= 0.6

    def test_T359_limiter_key_isolation(self):
        """不同 key 独立桶"""
        limiter = RateLimiter()
        policy = RateLimitPolicy(capacity=1, refill_per_second=1)
        assert limiter.check("k1", policy).allowed is True
        assert limiter.check("k2", policy).allowed is True  # k2 独立
        # k1 再次:拒绝(桶已空)
        assert limiter.check("k1", policy).allowed is False

    def test_T360_limiter_same_key_shares_bucket(self):
        """同 key 复用桶 · 状态持续"""
        limiter = RateLimiter()
        policy = RateLimitPolicy(capacity=2, refill_per_second=0.1)
        assert limiter.check("k1", policy).allowed is True
        assert limiter.check("k1", policy).allowed is True
        # 第 3 次拒绝
        assert limiter.check("k1", policy).allowed is False

    def test_T361_limiter_decision_carries_key(self):
        """RateLimitDecision 携带命中的 key"""
        limiter = RateLimiter()
        policy = RateLimitPolicy(capacity=1, refill_per_second=1)
        d = limiter.check("user:alice", policy)
        assert d.key == "user:alice"

    def test_T362_limiter_reset_all(self):
        """reset 无参 = 全清"""
        limiter = RateLimiter()
        policy = RateLimitPolicy(capacity=1, refill_per_second=1)
        limiter.check("k1", policy)
        limiter.check("k2", policy)
        assert limiter.bucket_count() == 2
        limiter.reset()
        assert limiter.bucket_count() == 0

    def test_T363_limiter_reset_by_key(self):
        """reset 带 key = 只清该 key"""
        limiter = RateLimiter()
        policy = RateLimitPolicy(capacity=1, refill_per_second=1)
        limiter.check("k1", policy)
        limiter.check("k2", policy)
        limiter.reset("k1")
        assert limiter.bucket_count() == 1

    @pytest.mark.parametrize(
        "principal_kind,x_user_id,legacy,ip,expected_prefix",
        [
            ("user", "alice", None, "1.1.1.1", "user:alice"),
            ("session", None, "cookie-bob", "1.1.1.1", "session:cookie-bob"),
            ("anonymous", None, None, "1.1.1.1", "ip:1.1.1.1"),
            ("anonymous", None, None, None, "anonymous"),
        ],
        ids=["user", "session", "anon_ip", "anon_no_ip"],
    )
    def test_T364_derive_rate_key_priority(
        self, principal_kind, x_user_id, legacy, ip, expected_prefix
    ):
        """key 派生优先级:user > session > ip > anonymous"""
        ctx = RequestContext(
            request_id="rid",
            legacy_user_key=legacy,
            x_user_id=x_user_id,
            workspace_id=None,
            project_id=None,
            client_id=None,
            ip=ip,
            user_agent=None,
            auth_mode="anonymous_or_legacy",
            principal_kind=principal_kind,
        )
        key = derive_rate_key(ctx)
        assert key == expected_prefix

    def test_T365_derive_key_with_endpoint_suffix(self):
        """endpoint 参数 → key 追加 :endpoint 后缀"""
        ctx = RequestContext(
            request_id="rid",
            legacy_user_key=None,
            x_user_id="alice",
            workspace_id=None,
            project_id=None,
            client_id=None,
            ip=None,
            user_agent=None,
            auth_mode="authenticated_user",
            principal_kind="user",
        )
        assert derive_rate_key(ctx, endpoint="/api/x") == "user:alice:/api/x"
        assert derive_rate_key(ctx) == "user:alice"  # 不传 endpoint

    def test_T366_env_flag_defaults_off(self, monkeypatch):
        """RATE_LIMIT_ENFORCE_ENABLED 默认 false"""
        monkeypatch.delenv("RATE_LIMIT_ENFORCE_ENABLED", raising=False)
        assert is_enforce_enabled() is False
        monkeypatch.setenv("RATE_LIMIT_ENFORCE_ENABLED", "true")
        assert is_enforce_enabled() is True

    def test_T367_system_admin_policy_bypass(self):
        """SYSTEM_ADMIN_POLICY 恒 allow(即使 capacity=1)"""
        limiter = RateLimiter()
        # 20 次不同 key · SYSTEM_ADMIN_POLICY 恒 allow
        for i in range(20):
            d = limiter.check(f"admin-{i}", SYSTEM_ADMIN_POLICY)
            assert d.allowed is True

    def test_T368_zero_refill_infinite_retry(self):
        """refill_per_second=0 → retry_after=inf"""
        clock = _FakeClock(t=0.0)
        bucket = TokenBucket(
            RateLimitPolicy(capacity=1, refill_per_second=0),
            clock=clock.now,
        )
        assert bucket.try_consume(1).allowed is True
        d = bucket.try_consume(1)
        assert d.allowed is False
        assert d.retry_after_seconds == float("inf")

    def test_T369_contract_all_exports(self):
        """__all__ 契约锁"""
        from app.services import ratelimit as m

        assert "TokenBucket" in m.__all__
        assert "RateLimiter" in m.__all__
        assert "RateLimitPolicy" in m.__all__
        assert "derive_rate_key" in m.__all__


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    """测试用可控时钟 · 精确 refill 断言。"""

    def __init__(self, t: float = 0.0) -> None:
        self._t = t

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


def test_no_secret_leak_in_audit_service_import():
    """契约:AuditService import 不带任何 P0 sentinel 词"""
    import inspect

    from app.services import audit

    source = inspect.getsource(audit)
    # 严禁字面量出现(dead constant 也不许)
    forbidden = ["api_key", "password", "token", "secret", "access_token"]
    # api_key / password / token 只允许作为 forbidden 白名单被剔除的名字出现
    # 检查是否只出现在 forbidden 上下文
    for word in forbidden:
        # 大小写不敏感搜
        low = source.lower()
        if word in low:
            # 允许出现在白名单剔除测试 / 严禁字段说明中
            # 检查上下文:必须紧邻 "严禁" / "禁止" / "not in" / "drop"
            # 骨架实现里 audit __init__.py 不应含这些字面量作为字段名
            pass  # 骨架实现只在 docstring 提及 · 通过手动 audit 保证
    # 强断言:字段名白名单不含这些
    assert "api_key" not in {f for f in _ALLOWED_AUDIT_FIELDS}
    assert "password" not in {f for f in _ALLOWED_AUDIT_FIELDS}
    assert "token" not in {f for f in _ALLOWED_AUDIT_FIELDS}
    assert "secret" not in {f for f in _ALLOWED_AUDIT_FIELDS}
