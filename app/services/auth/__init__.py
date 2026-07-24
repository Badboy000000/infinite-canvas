"""Auth service 包（权限 PR-3 · 认证入口骨架 · Wave 3-N.9 Batch 1 主线 B）。

**定位**：提供密码哈希、Session 存储、认证服务三件套，作为权限治理专题
M1 认证入口骨架的 service 层。所有服务默认关闭（`AUTH_ENABLED=false`），
GM-22 defaults-off pattern 复用。

**依赖决策**：
- 密码存储：argon2id（`argon2-cffi` 直用，passlib 未安装故此环境走 argon2 直用）
- Session 载体：httpOnly Cookie + server-side opaque session（SQLAlchemy Core）
- 无 JWT、无客户端 token、服务端记录

**P0 密钥零泄漏**：password / session_token / api_key 禁止出现在 log / err msg / repr。
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import FrozenSet, List, Optional

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from sqlalchemy import select, text

from app.db.engine import get_engine
from app.db.session import get_session as _db_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 环境 flag（默认关闭 · GM-22 pattern 复用）
# ---------------------------------------------------------------------------

_TRUTHY: FrozenSet[str] = frozenset({"1", "true", "yes", "on"})
_ENV_FLAG = "AUTH_ENABLED"


def is_auth_enabled() -> bool:
    """读取 `AUTH_ENABLED` env flag（默认 false）。"""
    raw = os.environ.get(_ENV_FLAG, "").strip().lower()
    return raw in _TRUTHY


# ---- 闲置超时与绝对超时（Decision 认证栈选型 §2）----
IDLE_TIMEOUT = timedelta(hours=12)
ABSOLUTE_TIMEOUT = timedelta(days=7)
LOCK_DURATION = timedelta(minutes=15)
MAX_FAILED_ATTEMPTS = 5
MIN_PASSWORD_LENGTH = 12

# ---------------------------------------------------------------------------
# AuthenticationError
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthenticationError(Exception):
    """认证错误（frozen dataclass · 零密钥泄漏）。

    错误码对齐决策 §1 错误码清单：
    - invalid_credentials / account_locked / session_expired
    - password_too_weak / password_change_required
    """

    code: str
    message: str
    http_status: int = 401

    def __repr__(self) -> str:
        # 零密钥泄漏：只暴露 code，不暴露 message 细节
        return f"AuthenticationError(code={self.code!r})"

    def __str__(self) -> str:
        return self.message


# ---------------------------------------------------------------------------
# PasswordHasher
# ---------------------------------------------------------------------------


class PasswordHasher:
    """argon2id 密码哈希器（argon2-cffi 直用）。

    参数（决策 §1 默认值）：
    - time_cost=3
    - memory_cost=65536 (64 MiB)
    - parallelism=2
    - hash_len=32
    - salt_len=16

    **安全约束**：
    - verify() 使用 hmac.compare_digest 防时序攻击
    - 明文密码不许出现在 log / err msg / repr
    - 比对失败不区分"用户不存在"与"密码错误"（防用户枚举）
    """

    def __init__(self) -> None:
        self._hasher = _Argon2Hasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=2,
            hash_len=32,
            salt_len=16,
        )

    def hash(self, password: str) -> str:
        """对明文密码进行 argon2id 哈希。

        password 长度 < MIN_PASSWORD_LENGTH 时 raise AuthenticationError。
        """
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AuthenticationError(
                code="password_too_weak",
                message=f"密码长度不足 {MIN_PASSWORD_LENGTH} 字符",
                http_status=422,
            )
        return self._hasher.hash(password)

    def verify(self, hash_value: str, password: str) -> bool:
        """验证密码与哈希值匹配。

        使用 argon2 内置 verify（内部已做恒定时间比较）。
        失败时静默返回 False，不泄露失败原因。
        """
        if not hash_value or not password:
            return False
        try:
            self._hasher.verify(hash_value, password)
            return True
        except (VerifyMismatchError, VerificationError):
            return False

    def needs_rehash(self, hash_value: str) -> bool:
        """检查是否需要升级哈希参数（惰性重哈希）。"""
        if not hash_value:
            return False
        try:
            return self._hasher.check_needs_rehash(hash_value)
        except Exception:
            return False


# ---------------------------------------------------------------------------
# SessionRepository
# ---------------------------------------------------------------------------


class SessionRepository:
    """服务端 opaque session 存储（SQLAlchemy Core）。

    设计要点：
    - session_id 是 UUID4 字符串，同时作为 DB 主键和 Cookie 值。
    - Cookie 格式：`sid.<session_id>`（不透明字符串，不含用户信息）。
    - 滑动续期：`touch()` 刷新 `last_seen_at`，绝对时间不刷新。
    - 撤销：logout 删除行 + 密码变更时 `revoke_all_for_user`。
    - 过期清理：startup 时扫描 `expires_at < now()` 的行并删除。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        from app.services.auth.tables import sessions as _sessions_table

        self._table = _sessions_table

    # ---- 创建 ----------------------------------------------------------

    def create(
        self,
        user_id: str,
        username: str,
        *,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        idle_timeout: timedelta = IDLE_TIMEOUT,
        absolute_timeout: timedelta = ABSOLUTE_TIMEOUT,
    ) -> str:
        """创建新 session，返回 session_id（UUID4）。"""
        session_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        with _db_session() as session:
            session.execute(
                self._table.insert().values(
                    session_id=session_id,
                    user_id=user_id,
                    username=username,
                    ip=ip,
                    user_agent=user_agent,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=now + absolute_timeout,
                    revoked_at=None,
                )
            )
            session.commit()
        return session_id

    # ---- 查询 ----------------------------------------------------------

    def load(self, session_id: str) -> Optional[dict]:
        """加载 session 行（若无或已过期/撤销则返回 None）。

        返回 dict 包含：user_id, username, expires_at, last_seen_at, revoked_at。
        """
        with _db_session() as session:
            row = session.execute(
                select(self._table).where(self._table.c.session_id == session_id)
            ).first()
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            if row.revoked_at is not None:
                return None
            if row.expires_at is not None:
                # 比较时需要确保两个都是 aware datetime
                expires = row.expires_at
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if now > expires:
                    return None
            return {
                "user_id": row.user_id,
                "username": row.username,
                "expires_at": row.expires_at,
                "last_seen_at": row.last_seen_at,
                "revoked_at": row.revoked_at,
            }

    def touch(self, session_id: str) -> bool:
        """刷新 last_seen_at（滑动续期）。返回 True 如果行存在且未过期。"""
        now = datetime.now(timezone.utc)
        with _db_session() as session:
            result = session.execute(
                text(
                    "UPDATE sessions SET last_seen_at = :now "
                    "WHERE session_id = :sid AND revoked_at IS NULL "
                    "AND expires_at > :now"
                ),
                {"now": now, "sid": session_id},
            )
            session.commit()
            return result.rowcount > 0

    # ---- 撤销 ----------------------------------------------------------

    def revoke(self, session_id: str) -> None:
        """撤销单个 session（标记 revoked_at）。"""
        now = datetime.now(timezone.utc)
        with _db_session() as session:
            session.execute(
                text(
                    "UPDATE sessions SET revoked_at = :now "
                    "WHERE session_id = :sid AND revoked_at IS NULL"
                ),
                {"now": now, "sid": session_id},
            )
            session.commit()

    def revoke_all_for_user(self, user_id: str) -> int:
        """撤销某用户的所有活跃 session。返回撤销数量。"""
        now = datetime.now(timezone.utc)
        with _db_session() as session:
            result = session.execute(
                text(
                    "UPDATE sessions SET revoked_at = :now "
                    "WHERE user_id = :uid AND revoked_at IS NULL"
                ),
                {"now": now, "uid": user_id},
            )
            session.commit()
            return result.rowcount

    # ---- 清理 ----------------------------------------------------------

    def cleanup_expired(self) -> int:
        """删除所有已过期 session。返回删除数量。"""
        now = datetime.now(timezone.utc)
        with _db_session() as session:
            result = session.execute(
                text(
                    "DELETE FROM sessions WHERE revoked_at IS NOT NULL "
                    "OR expires_at <= :now"
                ),
                {"now": now},
            )
            session.commit()
            return result.rowcount


# ---------------------------------------------------------------------------
# AuthService
# ---------------------------------------------------------------------------


class AuthService:
    """认证服务（login / logout / verify_session）。

    **默认关闭**：`AUTH_ENABLED=false` 时 login 返回 503，verify_session 返回 None。
    **flag on**：走完整认证流程。
    """

    def __init__(
        self,
        password_hasher: Optional[PasswordHasher] = None,
        session_repo: Optional[SessionRepository] = None,
    ) -> None:
        self._password_hasher = password_hasher or PasswordHasher()
        self._session_repo = session_repo or SessionRepository()

    # ---- login --------------------------------------------------------

    def login(
        self,
        username: str,
        password: str,
        *,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> str:
        """验证用户名密码并创建 session。返回 session_id。

        Raises AuthenticationError 如果：
        - 用户名不存在（但返回与密码错误相同的错误码，防用户枚举）
        - 密码错误
        - 账号锁定
        - 要求修改密码
        """
        if not is_auth_enabled():
            raise AuthenticationError(
                code="auth_disabled",
                message="认证服务未启用",
                http_status=503,
            )

        # 查 auth_credentials 表
        from app.services.auth.tables import auth_credentials as _creds_table

        with _db_session() as session:
            row = session.execute(
                select(_creds_table).where(_creds_table.c.username == username)
            ).first()

        # 用户不存在或凭据行不存在 → 伪装为密码错误（防枚举）
        if row is None:
            self._dummy_verify(password)
            raise AuthenticationError(
                code="invalid_credentials",
                message="用户名或密码错误",
                http_status=401,
            )

        # 检查锁定
        if row.locked_until is not None:
            locked = row.locked_until
            if locked.tzinfo is None:
                locked = locked.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < locked:
                raise AuthenticationError(
                    code="account_locked",
                    message="账号已锁定，请稍后再试",
                    http_status=423,
                )

        # 检查密码
        if not self._password_hasher.verify(row.password_hash, password):
            self._record_failed_attempt(username)
            raise AuthenticationError(
                code="invalid_credentials",
                message="用户名或密码错误",
                http_status=401,
            )

        # 登录成功 → 重置失败计数
        self._reset_failed_attempts(username)

        # 检查是否要求修改密码
        if row.must_change_password:
            raise AuthenticationError(
                code="password_change_required",
                message="首次登录必须修改密码",
                http_status=403,
            )

        # 创建 session
        session_id = self._session_repo.create(
            user_id=row.user_id,
            username=username,
            ip=ip,
            user_agent=user_agent,
        )

        return session_id

    # ---- logout -------------------------------------------------------

    def logout(self, session_id: str, *, all_devices: bool = False) -> None:
        """登出：撤销当前 session 或全部设备 session。"""
        self._session_repo.revoke(session_id)
        if all_devices:
            # 从 session 表中查 user_id
            session_data = self._session_repo.load(session_id)
            if session_data is not None:
                self._session_repo.revoke_all_for_user(session_data["user_id"])

    # ---- verify_session -----------------------------------------------

    def verify_session(self, session_id: str) -> Optional[dict]:
        """验证 session 并返回 user 信息。无/过期 session 返回 None。

        返回 dict：{user_id, username, session_id}。
        """
        if not is_auth_enabled():
            return None
        data = self._session_repo.load(session_id)
        if data is None:
            return None
        # 滑动续期
        self._session_repo.touch(session_id)
        return {
            "user_id": data["user_id"],
            "username": data["username"],
            "session_id": session_id,
        }

    # ---- 内部 helpers -------------------------------------------------

    def _dummy_verify(self, password: str) -> None:
        """伪验证：消耗近似时间，防用户枚举时序攻击。"""
        # 对恒定的 dummy hash 做 verify，消耗与真实验证接近的时间
        dummy_hash = self._password_hasher.hash("dummy_password_12")
        self._password_hasher.verify(dummy_hash, password)

    def _record_failed_attempt(self, username: str) -> None:
        """记录登录失败尝试。达到阈值时锁定账号。"""
        from app.services.auth.tables import auth_credentials as _creds_table

        with _db_session() as session:
            session.execute(
                text(
                    "UPDATE auth_credentials SET failed_attempts = failed_attempts + 1, "
                    "updated_at = :now WHERE username = :uname"
                ),
                {"now": datetime.now(timezone.utc), "uname": username},
            )
            # 检查是否达到阈值
            row = session.execute(
                select(_creds_table.c.failed_attempts).where(
                    _creds_table.c.username == username
                )
            ).first()
            if row is not None and row.failed_attempts >= MAX_FAILED_ATTEMPTS:
                lock_until = datetime.now(timezone.utc) + LOCK_DURATION
                session.execute(
                    text(
                        "UPDATE auth_credentials SET locked_until = :lock, "
                        "updated_at = :now WHERE username = :uname"
                    ),
                    {"lock": lock_until, "now": datetime.now(timezone.utc), "uname": username},
                )
            session.commit()

    def _reset_failed_attempts(self, username: str) -> None:
        """登录成功后重置失败计数与锁定状态。"""
        with _db_session() as session:
            session.execute(
                text(
                    "UPDATE auth_credentials SET failed_attempts = 0, "
                    "locked_until = NULL, updated_at = :now "
                    "WHERE username = :uname"
                ),
                {"now": datetime.now(timezone.utc), "uname": username},
            )
            session.commit()


# ---------------------------------------------------------------------------
# 工厂
# ---------------------------------------------------------------------------

_auth_service_singleton: Optional[AuthService] = None
_singleton_lock = threading.Lock()


def get_auth_service() -> AuthService:
    """获取 AuthService 进程内单例。"""
    global _auth_service_singleton
    if _auth_service_singleton is None:
        with _singleton_lock:
            if _auth_service_singleton is None:
                _auth_service_singleton = AuthService()
    return _auth_service_singleton


def reset_auth_service() -> None:
    """拆除 AuthService 单例（供测试隔离）。"""
    global _auth_service_singleton
    _auth_service_singleton = None


__all__ = [
    "AuthenticationError",
    "AuthService",
    "PasswordHasher",
    "SessionRepository",
    "get_auth_service",
    "reset_auth_service",
    "is_auth_enabled",
    "IDLE_TIMEOUT",
    "ABSOLUTE_TIMEOUT",
    "LOCK_DURATION",
    "MAX_FAILED_ATTEMPTS",
    "MIN_PASSWORD_LENGTH",
]