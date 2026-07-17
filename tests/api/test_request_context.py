"""PR-BE-02 契约测试：`RequestContextMiddleware` + `get_request_context()`。

覆盖：
- middleware 在响应上写 `X-Request-Id` header（生成 / 回显两种路径）。
- ContextVar 装配：dependency 能在路由函数内读到中间件设置的 ctx。
- `auth_mode` 判定矩阵：无 legacy 线索 / X-User-Id / cookie / query。
- `legacy_user_key` 优先级：cookie > query > x_user_id。
- 未装配 middleware（后台任务 / 测试直调）时 `get_request_context()` 兜底。
"""
from __future__ import annotations

import re
import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.context import (
    RequestContextMiddleware,
    RequestContextVar,
    get_request_context,
    request_context_dependency,
)
from app.identity.request_context import RequestContext


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/echo")
    def echo(ctx: RequestContext = Depends(request_context_dependency)) -> dict:
        return {
            "request_id": ctx.request_id,
            "legacy_user_key": ctx.legacy_user_key,
            "x_user_id": ctx.x_user_id,
            "workspace_id": ctx.workspace_id,
            "project_id": ctx.project_id,
            "client_id": ctx.client_id,
            "ip": ctx.ip,
            "user_agent": ctx.user_agent,
            "auth_mode": ctx.auth_mode,
        }

    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_make_app())


# ---------------------------- X-Request-Id ----------------------------------


def test_response_carries_generated_request_id_when_absent(client: TestClient) -> None:
    resp = client.get("/echo")
    assert resp.status_code == 200
    rid = resp.headers.get("X-Request-Id")
    assert rid is not None and len(rid) > 0
    # 生成路径是 uuid4 hex (32 chars) 或 uuid4 str（36 chars 含横线）；本实现是 hex。
    assert re.fullmatch(r"[0-9a-f]{32}", rid) is not None
    assert resp.json()["request_id"] == rid


def test_two_requests_get_distinct_request_ids(client: TestClient) -> None:
    r1 = client.get("/echo")
    r2 = client.get("/echo")
    assert r1.headers["X-Request-Id"] != r2.headers["X-Request-Id"]


def test_incoming_request_id_is_echoed_verbatim(client: TestClient) -> None:
    trace = "my-trace-xxx-abc123"
    resp = client.get("/echo", headers={"X-Request-Id": trace})
    assert resp.status_code == 200
    assert resp.headers["X-Request-Id"] == trace
    assert resp.json()["request_id"] == trace


def test_blank_incoming_request_id_falls_back_to_generated(client: TestClient) -> None:
    resp = client.get("/echo", headers={"X-Request-Id": "   "})
    rid = resp.headers["X-Request-Id"]
    assert rid.strip() and rid != "   "
    assert re.fullmatch(r"[0-9a-f]{32}", rid) is not None


# ---------------------------- auth_mode 判定矩阵 ------------------------------


def test_auth_mode_anonymous_or_legacy_without_hints(client: TestClient) -> None:
    body = client.get("/echo").json()
    assert body["auth_mode"] == "anonymous_or_legacy"
    assert body["legacy_user_key"] is None
    assert body["x_user_id"] is None


def test_auth_mode_legacy_alias_from_x_user_id_header(client: TestClient) -> None:
    body = client.get("/echo", headers={"X-User-Id": "foo"}).json()
    assert body["auth_mode"] == "legacy_alias"
    assert body["x_user_id"] == "foo"
    # 无 cookie / query 时 legacy_user_key 回退到 x_user_id。
    assert body["legacy_user_key"] == "foo"


def test_auth_mode_legacy_alias_from_cookie(client: TestClient) -> None:
    body = client.get("/echo", cookies={"x_user_id": "cookie-user"}).json()
    assert body["auth_mode"] == "legacy_alias"
    assert body["legacy_user_key"] == "cookie-user"
    assert body["x_user_id"] is None


def test_auth_mode_legacy_alias_from_query(client: TestClient) -> None:
    body = client.get("/echo?user=query-user").json()
    assert body["auth_mode"] == "legacy_alias"
    assert body["legacy_user_key"] == "query-user"


def test_legacy_user_key_priority_cookie_over_query_over_header(client: TestClient) -> None:
    body = client.get(
        "/echo?user=q",
        headers={"X-User-Id": "h"},
        cookies={"x_user_id": "c"},
    ).json()
    assert body["auth_mode"] == "legacy_alias"
    assert body["legacy_user_key"] == "c"
    # header 原值仍在 x_user_id 字段内保留供 principal 派生。
    assert body["x_user_id"] == "h"


# ---------------------------- 其他字段 ---------------------------------------


def test_workspace_project_client_id_default_none_in_this_pr(client: TestClient) -> None:
    body = client.get("/echo", headers={"X-User-Id": "u"}).json()
    # 本 PR 冻结 workspace_id / project_id 为 None，等 PR-2 承接。
    assert body["workspace_id"] is None
    assert body["project_id"] is None


def test_client_id_header_is_propagated(client: TestClient) -> None:
    body = client.get("/echo", headers={"X-Client-Id": "canvas_abc"}).json()
    assert body["client_id"] == "canvas_abc"


def test_user_agent_is_captured(client: TestClient) -> None:
    body = client.get("/echo", headers={"User-Agent": "smoke/1.0"}).json()
    assert body["user_agent"] == "smoke/1.0"


def test_ip_from_forwarded_for_takes_precedence(client: TestClient) -> None:
    body = client.get("/echo", headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}).json()
    assert body["ip"] == "203.0.113.5"


# ---------------------------- ContextVar 生命周期 ----------------------------


def test_context_var_is_reset_after_response(client: TestClient) -> None:
    # 请求外 ContextVar 应为 None（middleware 已 reset）。
    _ = client.get("/echo")
    assert RequestContextVar.get() is None


def test_get_request_context_falls_back_when_unset() -> None:
    # 直接在测试进程内（无 middleware）调用兜底路径。
    RequestContextVar.set(None)  # 显式清空
    ctx = get_request_context()
    assert isinstance(ctx, RequestContext)
    assert ctx.auth_mode == "anonymous_or_legacy"
    assert ctx.request_id  # 非空 uuid4 hex
    uuid.UUID(hex=ctx.request_id)  # 合法 uuid


def test_dependency_returns_middleware_context(client: TestClient) -> None:
    """dependency 拿到的 request_id 与响应 header 一致，证明 ContextVar 装配成功。"""
    resp = client.get("/echo", headers={"X-Request-Id": "trace-42"})
    assert resp.json()["request_id"] == "trace-42"
    assert resp.headers["X-Request-Id"] == "trace-42"
