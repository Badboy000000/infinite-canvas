"""`RequestContext` 只读桥与 `X-Request-Id` middleware（PR-BE-02 落地）。

本模块负责：

1. 在进程内维护一个 `contextvars.ContextVar` 承载当前请求的
   :class:`app.identity.request_context.RequestContext`。
2. 提供 `RequestContextMiddleware`：从 HTTP header / cookie / query 解析
   legacy 身份线索，构造 `RequestContext`，`set` 到 ContextVar；响应阶段
   把 `request_id` 回写为 `X-Request-Id` header，然后 `reset` ContextVar。
3. 提供 `get_request_context()` / `request_context_dependency()` 两个只读
   访问入口，供后续 PR-BE-04 的 store facade、PR-BE-12 的全局错误
   handler、以及权限 PR-1/PR-3/PR-4 的 principal 消费。

字段清单严格对齐权限 PR-0（[[app.identity.request_context]]）；本 PR **只
消费不再定义**。auth_mode 三态由本 middleware 判定，但 `"authenticated_user"`
路径由 PR-3 认证入口承接，本 PR **不实现**——保留 legacy 通道输入解析
即可。`workspace_id` / `project_id` / `client_id` 均恒 `None`，待
PR-2 legacy_mapper 落地后再填。

参考：
- [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-02
- [[60 讨论记录/2026-07-17 第二批开工/2026-07-17 第二批 PR 开工协调纲要]]
  §"字段冻结契约" / §"保活烟测 BE-15"
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from app.identity.request_context import AuthMode, RequestContext

__all__ = [
    "RequestContextVar",
    "RequestContextMiddleware",
    "get_request_context",
    "request_context_dependency",
]

# 全局 ContextVar：默认 None 表示"未被 middleware 装配"（unit test / 后台
# 任务场景）。`get_request_context()` 会用 fallback ctx 兜底，保证下游
# 消费方永远拿到一个非空 `RequestContext`。
RequestContextVar: ContextVar[Optional[RequestContext]] = ContextVar(
    "request_context",
    default=None,
)

_REQUEST_ID_HEADER = "X-Request-Id"
_USER_ID_HEADER = "X-User-Id"
_CLIENT_ID_HEADER = "X-Client-Id"
_USER_AGENT_HEADER = "User-Agent"
_FORWARDED_FOR_HEADER = "X-Forwarded-For"
_LEGACY_COOKIE_NAME = "x_user_id"
_LEGACY_QUERY_NAME = "user"


def _extract_ip(request: Request) -> Optional[str]:
    """反向代理下取 `X-Forwarded-For` 首段；否则 socket peer。"""
    forwarded = request.headers.get(_FORWARDED_FOR_HEADER)
    if forwarded:
        first = forwarded.split(",", 1)[0].strip()
        if first:
            return first
    client = request.client
    if client is not None and client.host:
        return client.host
    return None


def _build_context(request: Request) -> RequestContext:
    """从 `request` 构造 `RequestContext`。auth_mode 判定见 module docstring。"""
    incoming_rid = request.headers.get(_REQUEST_ID_HEADER)
    request_id = incoming_rid.strip() if incoming_rid and incoming_rid.strip() else uuid.uuid4().hex

    x_user_id = request.headers.get(_USER_ID_HEADER) or None
    client_hdr = request.headers.get(_CLIENT_ID_HEADER) or None
    user_agent = request.headers.get(_USER_AGENT_HEADER) or None

    cookie_user = request.cookies.get(_LEGACY_COOKIE_NAME) or None
    query_user = request.query_params.get(_LEGACY_QUERY_NAME) or None

    # legacy_user_key 优先级：cookie > query > header 派生（若无 legacy 通道
    # 输入则为 None）。x_user_id 字段保留 header 原值供 principal 派生。
    legacy_user_key: Optional[str] = cookie_user or query_user or x_user_id or None

    auth_mode: AuthMode
    if x_user_id or cookie_user or query_user:
        auth_mode = "legacy_alias"
    else:
        auth_mode = "anonymous_or_legacy"

    return RequestContext(
        request_id=request_id,
        legacy_user_key=legacy_user_key,
        x_user_id=x_user_id,
        # PR-2 legacy_mapper 承接后再由 middleware 或依赖填充；本 PR 恒 None。
        workspace_id=None,
        project_id=None,
        # WebSocket / 前端 X-Client-Id：为兼容 legacy 消费方本 PR 也读取，但
        # 主要消费在 PR-BE-11 realtime 治理。
        client_id=client_hdr,
        ip=_extract_ip(request),
        user_agent=user_agent,
        auth_mode=auth_mode,
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """在每个 HTTP 请求前后维护 :data:`RequestContextVar`。

    请求进入 → 解析 legacy 身份线索 → 构造 `RequestContext` → `set` 到
    ContextVar → 交给下游 handler；响应出去前 → 写 `X-Request-Id` 响应
    header → `reset` ContextVar。

    注意：本 middleware **只解析和承载**，不做认证决策；`authenticated_user`
    路径留给 PR-3 认证入口。
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        ctx = _build_context(request)
        token = RequestContextVar.set(ctx)
        try:
            response: Response = await call_next(request)
        finally:
            RequestContextVar.reset(token)
        response.headers[_REQUEST_ID_HEADER] = ctx.request_id
        return response


def _fallback_context() -> RequestContext:
    """ContextVar 未设时的兜底 ctx。

    用途：单元测试直接调用被装饰函数、后台任务在事件循环外读日志、异常
    路径在 middleware 之前抛出等场景。恒返回 `anonymous_or_legacy` 骨架
    ctx，`request_id` 为新 uuid4，避免下游 `KeyError`。
    """
    return RequestContext(
        request_id=uuid.uuid4().hex,
        legacy_user_key=None,
        x_user_id=None,
        workspace_id=None,
        project_id=None,
        client_id=None,
        ip=None,
        user_agent=None,
        auth_mode="anonymous_or_legacy",
    )


def get_request_context() -> RequestContext:
    """只读读取当前请求上下文。

    - middleware 装配后：返回 middleware `set` 的实例。
    - 未装配（测试 / 后台任务）：返回 fallback ctx。

    调用方**不要缓存**返回值到跨请求的全局变量——上下文按请求隔离。
    """
    ctx = RequestContextVar.get()
    if ctx is None:
        return _fallback_context()
    return ctx


def request_context_dependency() -> RequestContext:
    """FastAPI `Depends(...)` 兼容包装。

    路由函数用法示例（本 PR 不改任何路由，仅供后续 PR 消费）::

        from fastapi import Depends
        from app.api.context import request_context_dependency
        from app.identity.request_context import RequestContext

        @router.get("/x")
        def handler(ctx: RequestContext = Depends(request_context_dependency)) -> ...:
            ...
    """
    return get_request_context()
