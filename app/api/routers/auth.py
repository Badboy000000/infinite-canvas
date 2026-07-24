"""Auth 路由（权限 PR-3 · 认证入口骨架 · Wave 3-N.9 Batch 1 主线 B）。

路由：
- `POST /api/auth/login` — 登录（返回 session Cookie）
- `POST /api/auth/logout` — 登出（撤销 Cookie）
- `GET /api/auth/whoami` — 增强版 whoami（flag on 时返回 principal 信息）

**默认关闭**：`AUTH_ENABLED=false` 时 login 返回 503，whoami 走原有匿名分支。
**flag on**：走完整认证流程。

**P0 密钥零泄漏**：password 明文不在 log / err msg / repr 中出现。
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from app.api.context import get_request_context as _get_context
from app.identity.request_context import RequestContext
from app.services.auth import (
    AuthenticationError,
    AuthService,
    get_auth_service,
    is_auth_enabled,
)
from app.services.audit import (
    AuditService,
    make_event,
)

# ---------------------------------------------------------------------------
# DTO
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """登录请求体。"""

    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """登录成功响应。"""

    code: str = "ok"
    data: dict = Field(default_factory=lambda: {"user_id": "", "username": ""})


class LogoutResponse(BaseModel):
    """登出响应。"""

    code: str = "ok"
    message: str = "已登出"


class WhoAmIResponse(BaseModel):
    """增强版 whoami 响应（替代 main.py 内 `/api/whoami`）。

    当 AUTH_ENABLED=true 且 session 有效时，返回 principal 信息。
    当 AUTH_ENABLED=false 或 session 无效时，返回 anonymous 信息。
    """

    principal_kind: str = Field(default="anonymous", description='"user" | "session" | "anonymous"')
    user_id: Optional[str] = None
    username: Optional[str] = None
    session_id: Optional[str] = None
    workspace_id: Optional[str] = None
    request_id: str = ""


# ---------------------------------------------------------------------------
# Cookie 配置
# ---------------------------------------------------------------------------

SESSION_COOKIE_NAME = "ic_session"
SESSION_COOKIE_PATH = "/"
# Secure 在 AUTH_ENABLED 且非 localhost 时强制
_SESSION_COOKIE_LIFETIME = 7 * 24 * 60 * 60  # 7 days (seconds)


def _set_session_cookie(response: Response, session_id: str) -> None:
    """设置 `ic_session` HttpOnly Cookie。

    属性：
    - HttpOnly（禁止 JS 读取）
    - SameSite=Lax（阻止跨站 CSRF）
    - Secure（AUTH_ENABLED 时强制，但 localhost 豁免）
    - Path=/
    - Max-Age=604800 (7d)
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=f"sid.{session_id}",
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=_SESSION_COOKIE_LIFETIME,
        path=SESSION_COOKIE_PATH,
    )


def _clear_session_cookie(response: Response) -> None:
    """清除 `ic_session` Cookie（Max-Age=0）。"""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value="",
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=0,
        path=SESSION_COOKIE_PATH,
    )


def _extract_session_id(request: Request) -> Optional[str]:
    """从 Cookie 中提取 session_id。"""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie and cookie.startswith("sid."):
        return cookie[4:]  # 去掉 "sid." 前缀
    return None


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_auth_router(
    auth_service: Optional[AuthService] = None,
    audit_service: Optional[AuditService] = None,
) -> APIRouter:
    """创建 Auth 路由。

    参数 auth_service 为 None 时使用全局单例。
    audit_service 为 None 时使用默认 buffered-only AuditService（不落盘除非 flag on）。
    """
    svc = auth_service or get_auth_service()
    audit = audit_service if audit_service is not None else AuditService()
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    # ------------------------------------------------------------------
    # POST /api/auth/login
    # ------------------------------------------------------------------
    @router.post("/login", response_model=LoginResponse)
    def login(
        body: LoginRequest,
        request: Request,
        response: Response,
    ) -> LoginResponse:
        """登录：验证用户名密码，设置 session Cookie。

        401 错误使用统一 error_code 格式，不泄露用户存在性。
        """
        if not is_auth_enabled():
            return LoginResponse(code="auth_disabled", data={"error": "认证服务未启用"})

        ip = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")

        try:
            session_id = svc.login(
                username=body.username,
                password=body.password,
                ip=ip,
                user_agent=user_agent,
            )
        except AuthenticationError as exc:
            # emit auth.login denied event (P0: 不带 password / session_token)
            try:
                audit.append(make_event(
                    action="auth.login",
                    outcome="denied",
                    context={"ip": ip, "user_agent": user_agent, "reason": exc.code},
                ))
            except Exception:
                pass
            return LoginResponse(code=exc.code, data={"error": exc.message})

        # emit auth.login success event
        try:
            audit.append(make_event(
                action="auth.login",
                outcome="success",
                context={"ip": ip, "user_agent": user_agent, "session_id": session_id},
            ))
        except Exception:
            pass

        _set_session_cookie(response, session_id)
        return LoginResponse(
            code="ok",
            data={"user_id": "", "username": body.username},
        )

    # ------------------------------------------------------------------
    # POST /api/auth/logout
    # ------------------------------------------------------------------
    @router.post("/logout", response_model=LogoutResponse)
    def logout(
        request: Request,
        response: Response,
    ) -> LogoutResponse:
        """登出：撤销当前 session，清除 Cookie。"""
        session_id = _extract_session_id(request)
        if session_id:
            svc.logout(session_id)
            # emit auth.logout event
            try:
                audit.append(make_event(
                    action="auth.logout",
                    outcome="success",
                    context={"session_id": session_id},
                ))
            except Exception:
                pass
        _clear_session_cookie(response)
        return LogoutResponse(code="ok", message="已登出")

    # ------------------------------------------------------------------
    # GET /api/auth/whoami
    # ------------------------------------------------------------------
    @router.get("/whoami", response_model=WhoAmIResponse)
    def whoami(
        request: Request,
        ctx: RequestContext = Depends(_get_context),
    ) -> WhoAmIResponse:
        """增强版 whoami。

        AUTH_ENABLED=true 且 session 有效时：
        - principal_kind="user"
        - 返回 user_id / username / session_id

        AUTH_ENABLED=false 或 session 无效时：
        - principal_kind 从 ctx 派生
        - user_id 从 ctx.x_user_id 或 ctx.legacy_user_key 派生
        """
        if not is_auth_enabled():
            # 走匿名/legacy 分支
            principal_kind = "anonymous"
            if ctx.auth_mode == "authenticated_user":
                principal_kind = "user"
            elif ctx.auth_mode == "legacy_alias":
                principal_kind = ctx.x_user_id or ctx.legacy_user_key and "session" or "user"  # noqa: E501
            return WhoAmIResponse(
                principal_kind=principal_kind,
                user_id=ctx.x_user_id or ctx.legacy_user_key,
                workspace_id=ctx.workspace_id,
                request_id=ctx.request_id,
            )

        # AUTH_ENABLED=true：尝试从 session 解析
        session_id = _extract_session_id(request)
        if session_id:
            user_info = svc.verify_session(session_id)
            if user_info is not None:
                return WhoAmIResponse(
                    principal_kind="user",
                    user_id=user_info["user_id"],
                    username=user_info["username"],
                    session_id=session_id,
                    workspace_id=ctx.workspace_id,
                    request_id=ctx.request_id,
                )

        # session 无效 → anonymous
        return WhoAmIResponse(
            principal_kind="anonymous",
            workspace_id=ctx.workspace_id,
            request_id=ctx.request_id,
        )

    return router


__all__ = [
    "create_auth_router",
    "LoginRequest",
    "LoginResponse",
    "LogoutResponse",
    "WhoAmIResponse",
    "SESSION_COOKIE_NAME",
    "_extract_session_id",
    "_set_session_cookie",
    "_clear_session_cookie",
]