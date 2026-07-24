"""权限 PR-3 · AuthService 契约测试。

覆盖：
- login 成功 → session 创建
- login 用户不存在 → invalid_credentials
- login 密码错误 → invalid_credentials
- login 账号锁定 → account_locked
- login 需修改密码 → password_change_required
- logout → session 撤销
- verify_session → session 有效返回 user 信息
- verify_session 过期 → None
- AUTH_ENABLED=false → login 拒绝 / verify_session 返回 None
- P0 密钥零泄漏：password 不在 log/err/repr 中
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        migrate_baseline(sandbox)
        yield sandbox


@pytest.fixture
def auth_flag_on(monkeypatch):
    """设置 AUTH_ENABLED=true。"""
    monkeypatch.setenv("AUTH_ENABLED", "true")


@pytest.fixture
def auth_flag_off(monkeypatch):
    """确保 AUTH_ENABLED 未设置（默认关闭）。"""
    monkeypatch.delenv("AUTH_ENABLED", raising=False)


def _create_test_user(username: str, password: str, must_change_password: bool = False) -> str:
    """在 DB 中创建一个测试用户凭据。返回 user_id。"""
    from app.db.session import get_session
    from app.services.auth import PasswordHasher
    from app.services.auth.tables import auth_credentials
    from app.shared.ids import generate_id

    hasher = PasswordHasher()
    password_hash = hasher.hash(password)
    user_id = str(generate_id())
    now = datetime.now(timezone.utc)

    # 首先创建 user 行（0006_identity 表）
    from sqlalchemy import text
    with get_session() as session:
        session.execute(
            text(
                "INSERT INTO user (id, legacy_user_key, display_name, avatar_url, "
                "created_at, updated_at) VALUES (:id, :key, :name, NULL, :now, :now)"
            ),
            {"id": user_id, "key": username, "name": username, "now": now},
        )
        session.execute(
            auth_credentials.insert().values(
                user_id=user_id,
                username=username,
                password_hash=password_hash,
                must_change_password=1 if must_change_password else 0,
                failed_attempts=0,
                locked_until=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return user_id


# ---------- login 成功路径 -----------------------------------------------


def test_login_success_returns_session_id(isolated_env, auth_flag_on):
    """login 成功返回 session_id（32 chars hex）。"""
    from app.services.auth import AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("alice", "correct_password_12345")
    svc = AuthService()
    session_id = svc.login("alice", "correct_password_12345")
    assert len(session_id) == 32
    assert all(c in "0123456789abcdef" for c in session_id)


def test_login_creates_session_row(isolated_env, auth_flag_on):
    """login 应该在 sessions 表中创建行。"""
    from app.services.auth import AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("bob", "correct_password_12345")
    svc = AuthService()
    session_id = svc.login("bob", "correct_password_12345", ip="127.0.0.1")

    data = svc._session_repo.load(session_id)
    assert data is not None
    assert data["username"] == "bob"


# ---------- login 失败路径 -----------------------------------------------


def test_login_wrong_password_raises_invalid_credentials(isolated_env, auth_flag_on):
    """密码错误 → AuthenticationError code=invalid_credentials。"""
    from app.services.auth import AuthenticationError, AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("charlie", "correct_password_12345")
    svc = AuthService()
    with pytest.raises(AuthenticationError) as exc_info:
        svc.login("charlie", "wrong_password_xxxxx")
    assert exc_info.value.code == "invalid_credentials"
    assert exc_info.value.http_status == 401


def test_login_unknown_user_returns_invalid_credentials_not_user_not_found(
    isolated_env, auth_flag_on
):
    """未知用户 → 返回同一 error code（防用户枚举）。"""
    from app.services.auth import AuthenticationError, AuthService, reset_auth_service

    reset_auth_service()
    svc = AuthService()
    with pytest.raises(AuthenticationError) as exc_info:
        svc.login("nonexistent_user", "some_password_12345")
    assert exc_info.value.code == "invalid_credentials"


def test_login_password_change_required_raises(isolated_env, auth_flag_on):
    """`must_change_password=1` 用户登录被拒绝。"""
    from app.services.auth import AuthenticationError, AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("must_change", "correct_password_12345", must_change_password=True)
    svc = AuthService()
    with pytest.raises(AuthenticationError) as exc_info:
        svc.login("must_change", "correct_password_12345")
    assert exc_info.value.code == "password_change_required"


def test_login_account_locked_after_max_failed_attempts(isolated_env, auth_flag_on):
    """5 次失败尝试后账号锁定。"""
    from app.services.auth import AuthenticationError, AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("dave", "correct_password_12345")
    svc = AuthService()
    # 5 次失败
    for _ in range(5):
        with pytest.raises(AuthenticationError):
            svc.login("dave", "wrong_password_xxxxx")
    # 第 6 次 → 锁定 error
    with pytest.raises(AuthenticationError) as exc_info:
        svc.login("dave", "correct_password_12345")
    assert exc_info.value.code == "account_locked"


# ---------- logout 路径 --------------------------------------------------


def test_logout_revokes_session(isolated_env, auth_flag_on):
    """logout 后 verify_session 返回 None。"""
    from app.services.auth import AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("eve", "correct_password_12345")
    svc = AuthService()
    session_id = svc.login("eve", "correct_password_12345")
    assert svc.verify_session(session_id) is not None

    svc.logout(session_id)
    assert svc.verify_session(session_id) is None


# ---------- verify_session 路径 ------------------------------------------


def test_verify_session_returns_user_info(isolated_env, auth_flag_on):
    """verify_session 返回 user 信息 dict。"""
    from app.services.auth import AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("frank", "correct_password_12345")
    svc = AuthService()
    session_id = svc.login("frank", "correct_password_12345")

    info = svc.verify_session(session_id)
    assert info is not None
    assert info["username"] == "frank"
    assert info["session_id"] == session_id


def test_verify_session_unknown_returns_none(isolated_env, auth_flag_on):
    """未知 session_id → None。"""
    from app.services.auth import AuthService, reset_auth_service

    reset_auth_service()
    svc = AuthService()
    assert svc.verify_session("nonexistent_session_id") is None


# ---------- AUTH_ENABLED=false 默认路径 ----------------------------------


def test_login_returns_disabled_when_auth_flag_off(isolated_env, auth_flag_off):
    """AUTH_ENABLED=false 时 login raises AuthenticationError code=auth_disabled."""
    from app.services.auth import AuthenticationError, AuthService, reset_auth_service

    reset_auth_service()
    svc = AuthService()
    with pytest.raises(AuthenticationError) as exc_info:
        svc.login("anyone", "any_password_12345")
    assert exc_info.value.code == "auth_disabled"
    assert exc_info.value.http_status == 503


def test_verify_session_returns_none_when_auth_flag_off(isolated_env, auth_flag_off):
    """AUTH_ENABLED=false 时 verify_session 直接返回 None。"""
    from app.services.auth import AuthService, reset_auth_service

    reset_auth_service()
    svc = AuthService()
    assert svc.verify_session("any_session_id") is None


# ---------- SessionRepository 独立测试 -----------------------------------


def test_session_repo_expires_after_absolute_timeout(isolated_env, auth_flag_on, monkeypatch):
    """SessionRepository 应该按 expires_at 过期。"""
    from app.services.auth import SessionRepository
    from datetime import timedelta

    user_id = _create_test_user("gina", "correct_password_12345")
    repo = SessionRepository()
    # 设短超时
    session_id = repo.create(
        user_id=user_id,
        username="gina",
        absolute_timeout=timedelta(milliseconds=1),
    )
    import time
    time.sleep(0.05)
    # 应该过期
    assert repo.load(session_id) is None


def test_session_repo_revoke_all_for_user(isolated_env, auth_flag_on):
    """revoke_all_for_user 撤销该用户所有 session。"""
    from app.services.auth import SessionRepository

    user_id_h = _create_test_user("harry", "correct_password_12345")
    user_id_o = _create_test_user("other", "correct_password_12345")
    repo = SessionRepository()
    s1 = repo.create(user_id=user_id_h, username="harry")
    s2 = repo.create(user_id=user_id_h, username="harry")
    s3 = repo.create(user_id=user_id_o, username="other")

    count = repo.revoke_all_for_user(user_id_h)
    assert count == 2
    assert repo.load(s1) is None
    assert repo.load(s2) is None
    assert repo.load(s3) is not None


# ---------- P0 密钥零泄漏 ------------------------------------------------


def test_password_never_in_authentication_error_repr(isolated_env, auth_flag_on):
    """AuthenticationError repr 不泄露 message。"""
    from app.services.auth import AuthenticationError

    err = AuthenticationError(code="invalid_credentials", message="密码 secret_pw_xyz 错误")
    repr_str = repr(err)
    assert "secret_pw_xyz" not in repr_str
    assert "invalid_credentials" in repr_str


def test_session_id_is_opaque_uuid_hex(isolated_env, auth_flag_on):
    """session_id 是 UUID4 hex，不包含用户信息。"""
    from app.services.auth import AuthService, reset_auth_service

    reset_auth_service()
    _create_test_user("iris", "correct_password_12345")
    svc = AuthService()
    session_id = svc.login("iris", "correct_password_12345")
    # session_id 不包含用户名或密码
    assert "iris" not in session_id
    assert "correct_password" not in session_id
    # 是 hex string
    assert all(c in "0123456789abcdef" for c in session_id)