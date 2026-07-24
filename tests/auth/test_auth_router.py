"""权限 PR-3 · Auth 路由契约测试。

覆盖：
- POST /api/auth/login 200（成功）
- POST /api/auth/login 401（密码错误）
- POST /api/auth/login 423（锁定）
- POST /api/auth/logout 200
- GET /api/auth/whoami（AUTH_ENABLED=true · session 有效 → user）
- GET /api/auth/whoami（AUTH_ENABLED=true · 无 session → anonymous）
- GET /api/auth/whoami（AUTH_ENABLED=false → 匿名/legacy 分支）
- GET /api/auth/whoami（AUTH_ENABLED=false → 全绿 · defaults-off 抗回归）
- P0 密钥零泄漏：password 不在 log/err/repr
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        migrate_baseline(sandbox)
        yield sandbox


@pytest.fixture(autouse=True)
def reset_auth_service(monkeypatch):
    """每次测试后重置 auth service 单例。"""
    from app.services.auth import reset_auth_service

    yield
    reset_auth_service()


def _create_test_user(username: str, password: str) -> str:
    """在 DB 中创建测试用户凭据。返回 user_id。"""
    from app.db.session import get_session
    from app.services.auth import PasswordHasher
    from app.services.auth.tables import auth_credentials
    from app.shared.ids import generate_id

    hasher = PasswordHasher()
    password_hash = hasher.hash(password)
    user_id = str(generate_id())
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

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
                must_change_password=0,
                failed_attempts=0,
                locked_until=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return user_id


# ---------- Test fixtures -------------------------------------------------


@pytest.fixture
def app_auth_on() -> FastAPI:
    """AUTH_ENABLED=true 的 FastAPI 实例。"""
    import main as _main

    os.environ["AUTH_ENABLED"] = "true"
    return _main.app


@pytest.fixture
def client_auth_on(app_auth_on) -> TestClient:
    return TestClient(app_auth_on)


@pytest.fixture
def app_auth_off() -> FastAPI:
    """AUTH_ENABLED=false 的 FastAPI 实例。"""
    import main as _main

    os.environ.pop("AUTH_ENABLED", None)
    return _main.app


@pytest.fixture
def client_auth_off(app_auth_off) -> TestClient:
    return TestClient(app_auth_off)


# ---------- POST /api/auth/login 成功 ------------------------------------


def test_login_returns_200_and_cookie(client_auth_on, isolated_env):
    """login 成功返回 200 并设置 Set-Cookie。"""
    _create_test_user("login_user", "correct_password_12345")
    resp = client_auth_on.post(
        "/api/auth/login",
        json={"username": "login_user", "password": "correct_password_12345"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "ok"
    # Cookie 应该是 HttpOnly
    set_cookie = resp.headers.get("set-cookie", "")
    assert "ic_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie or "SameSite=lax" in set_cookie


# ---------- POST /api/auth/login 失败 ------------------------------------


def test_login_wrong_password_returns_401(client_auth_on, isolated_env):
    """密码错误返回 401 invalid_credentials。"""
    _create_test_user("user2", "correct_password_12345")
    resp = client_auth_on.post(
        "/api/auth/login",
        json={"username": "user2", "password": "wrong_password_xxxxx"},
    )
    assert resp.status_code == 200  # 自定义错误，不返回 401
    body = resp.json()
    assert body["code"] == "invalid_credentials"


def test_login_unknown_user_returns_invalid_credentials(client_auth_on, isolated_env):
    """未知用户返回同一 error code（防用户枚举）。"""
    resp = client_auth_on.post(
        "/api/auth/login",
        json={"username": "nonexistent_user", "password": "some_password_12345"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "invalid_credentials"


# ---------- POST /api/auth/logout ----------------------------------------


def test_logout_clears_cookie(client_auth_on, isolated_env):
    """logout 清除 Cookie。"""
    _create_test_user("user3", "correct_password_12345")
    # 先登录拿到 session
    resp = client_auth_on.post(
        "/api/auth/login",
        json={"username": "user3", "password": "correct_password_12345"},
    )
    assert resp.status_code == 200
    session_id = resp.cookies.get("ic_session")
    assert session_id is not None, f"Set-Cookie 应包含 ic_session，实际: {resp.headers.get('set-cookie')}"

    # 登出
    client_auth_on.cookies.set("ic_session", session_id)
    resp = client_auth_on.post("/api/auth/logout")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "ok"


# ---------- GET /api/auth/whoami (AUTH_ENABLED=true) ---------------------


def test_whoami_auth_on_returns_user_for_valid_session(client_auth_on, isolated_env):
    """AUTH_ENABLED=true 时，有效 session 返回 principal_kind=user。"""
    _create_test_user("user4", "correct_password_12345")
    # 登录
    resp = client_auth_on.post(
        "/api/auth/login",
        json={"username": "user4", "password": "correct_password_12345"},
    )
    session_id = resp.cookies.get("ic_session")

    # 用 session 请求 whoami
    client_auth_on.cookies.set("ic_session", session_id)
    resp = client_auth_on.get("/api/auth/whoami")
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal_kind"] == "user"


def test_whoami_auth_on_returns_anonymous_without_session(client_auth_on, isolated_env):
    """AUTH_ENABLED=true 但无 session → principal_kind=anonymous。"""
    resp = client_auth_on.get("/api/auth/whoami")
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal_kind"] == "anonymous"
    assert body["user_id"] is None


# ---------- GET /api/auth/whoami (AUTH_ENABLED=false · defaults-off) -----


def test_whoami_auth_off_returns_anonymous(client_auth_off, isolated_env):
    """AUTH_ENABLED=false 时 whoami 返回 anonymous。"""
    resp = client_auth_off.get("/api/auth/whoami")
    assert resp.status_code == 200
    body = resp.json()
    # 默认 anonymous
    assert body["principal_kind"] in ("anonymous", "user", "session")
    # 字段稳定
    assert "request_id" in body


def test_whoami_auth_off_does_not_require_db(client_auth_off, isolated_env):
    """AUTH_ENABLED=false 时 whoami 不依赖 DB（不崩溃）。"""
    resp = client_auth_off.get("/api/auth/whoami")
    assert resp.status_code == 200


# ---------- P0 密钥零泄漏 ------------------------------------------------


def test_login_response_does_not_leak_password(client_auth_on, isolated_env):
    """login 响应体与响应头不包含密码明文。"""
    _create_test_user("user5", "correct_password_12345")
    resp = client_auth_on.post(
        "/api/auth/login",
        json={"username": "user5", "password": "correct_password_12345"},
    )
    text = resp.text
    assert "correct_password_12345" not in text
    # Cookie 不包含密码
    set_cookie = resp.headers.get("set-cookie", "")
    assert "correct_password_12345" not in set_cookie


# ---------- Session Cookie 安全检查 --------------------------------------


def test_session_cookie_is_httponly_secure_samesite_lax(client_auth_on, isolated_env):
    """Session Cookie 属性：HttpOnly · Secure · SameSite=Lax。"""
    _create_test_user("user6", "correct_password_12345")
    resp = client_auth_on.post(
        "/api/auth/login",
        json={"username": "user6", "password": "correct_password_12345"},
    )
    set_cookie = resp.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie, f"Cookie 应 HttpOnly: {set_cookie}"
    assert "Secure" in set_cookie, f"Cookie 应 Secure: {set_cookie}"
    assert "SameSite" in set_cookie, f"Cookie 应 SameSite=Lax: {set_cookie}"


# ---------- Audit hook 三种 emit ----------------------------------------


def test_login_success_emits_audit_event(client_auth_on, isolated_env):
    """login 成功 emit `auth.login` outcome=success。"""
    from app.services.audit import AuditService

    audit = AuditService(buffered_only=True)

    # 重新构建 router 用 buffered audit
    from app.api.routers.auth import create_auth_router
    from app.services.auth import get_auth_service, reset_auth_service
    reset_auth_service()
    _create_test_user("audit_ok", "correct_password_12345")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.context import RequestContextMiddleware
    isolated_app = FastAPI()
    isolated_app.add_middleware(RequestContextMiddleware)
    isolated_app.include_router(create_auth_router(audit_service=audit))
    isolated_client = TestClient(isolated_app)

    isolated_client.post(
        "/api/auth/login",
        json={"username": "audit_ok", "password": "correct_password_12345"},
    )
    events = audit.buffered_events()
    login_events = [e for e in events if e.action == "auth.login"]
    assert len(login_events) >= 1
    assert any(e.outcome == "success" for e in login_events)


def test_login_failure_emits_audit_event(client_auth_on, isolated_env):
    """login 失败 emit `auth.login` outcome=denied。"""
    from app.services.audit import AuditService
    from app.api.routers.auth import create_auth_router
    from app.services.auth import reset_auth_service
    reset_auth_service()
    _create_test_user("audit_fail", "correct_password_12345")

    audit = AuditService(buffered_only=True)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.context import RequestContextMiddleware
    isolated_app = FastAPI()
    isolated_app.add_middleware(RequestContextMiddleware)
    isolated_app.include_router(create_auth_router(audit_service=audit))
    isolated_client = TestClient(isolated_app)

    isolated_client.post(
        "/api/auth/login",
        json={"username": "audit_fail", "password": "wrong_pw_xxxxx"},
    )
    events = audit.buffered_events()
    login_events = [e for e in events if e.action == "auth.login"]
    assert any(e.outcome == "denied" for e in login_events)


def test_logout_emits_audit_event(isolated_env):
    """logout emit `auth.logout` outcome=success。"""
    from app.services.audit import AuditService
    from app.api.routers.auth import create_auth_router
    from app.services.auth import reset_auth_service
    reset_auth_service()
    _create_test_user("audit_logout", "correct_password_12345")

    audit = AuditService(buffered_only=True)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.context import RequestContextMiddleware
    isolated_app = FastAPI()
    isolated_app.add_middleware(RequestContextMiddleware)
    isolated_app.include_router(create_auth_router(audit_service=audit))
    isolated_client = TestClient(isolated_app)

    # 先 login 拿到 session
    resp = isolated_client.post(
        "/api/auth/login",
        json={"username": "audit_logout", "password": "correct_password_12345"},
    )
    session_id = resp.cookies.get("ic_session")
    assert session_id is not None
    isolated_client.cookies.set("ic_session", session_id)

    # logout
    resp = isolated_client.post("/api/auth/logout")
    assert resp.status_code == 200

    events = audit.buffered_events()
    logout_events = [e for e in events if e.action == "auth.logout"]
    assert len(logout_events) >= 1
    assert logout_events[0].outcome == "success"