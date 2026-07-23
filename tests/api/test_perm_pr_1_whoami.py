"""权限 PR-1 契约测试 · `/api/whoami` (Wave 3-N.5 Batch 4 主线 A · 停摆阶段 3 首开)。

Lead 圆桌决议候选 A (GM-14 · GM-10 停下报告收敛):PR-0 (`app/identity/request_context.py`
9 字段 frozen dataclass) + PR-BE-02 (`app/api/context.py` middleware + ContextVar) 均已
在位;本 PR-1 骨架层收缩为「principal 派生 + `/api/whoami` 契约」。测试不假设 dataclass
字段扩展 (那是 PR-3/PR-4 的活),只验证响应契约与派生逻辑。

编号池 T300-T309 (Wave 3-N.5 Batch 4 分配)。

覆盖:
- T300  header X-User-Id → principal_kind="user"
- T301  cookie x_user_id (无 header) → principal_kind="session"
- T302  query ?user=  (无 header/cookie) → principal_kind="session"
- T303  全无 → principal_kind="anonymous" · user_id=None
- T304  优先级:X-User-Id header > cookie > query (user_id 走 header)
- T305  响应 schema pin (5 字段固定)
- T306  响应零明文密码/token/API key (sentinel deep grep)
- T307  request_id:X-Request-Id 复用 + 缺失时 middleware 生成 uuid4 hex (32 lowercase hex)
- T308  `_derive_principal_kind` 派生表 5 组组合独立单元测试
- T309  `/api/whoami` 挂在 middleware 之后 · 走完整栈 · 非 fallback ctx
"""
from __future__ import annotations

import re
from typing import Dict, Optional

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Route

from app.identity.request_context import RequestContext


@pytest.fixture(scope="module")
def client() -> TestClient:
    # 懒 import main.app,避免 tests 顶部 import 触发全模块 side-effect
    # (pattern 参照 tests/api/test_validation_error_handler.py)。
    import main as _main  # type: ignore[import-untyped]

    return TestClient(_main.app)


# --------------------------------------------------------------------------- #
# T300-T304 · principal_kind 派生 + user_id 通道优先级                          #
# --------------------------------------------------------------------------- #


def test_T300_header_x_user_id_yields_principal_kind_user(client: TestClient) -> None:
    """T300 · header X-User-Id → principal_kind="user" · user_id=header 值。"""
    resp = client.get("/api/whoami", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal_kind"] == "user"
    assert body["user_id"] == "alice"


def test_T301_cookie_x_user_id_yields_principal_kind_session(client: TestClient) -> None:
    """T301 · cookie x_user_id (无 X-User-Id header) → principal_kind="session"。

    RequestContext.auth_mode="legacy_alias" (cookie 命中 legacy 通道),但
    x_user_id header 为空 → 派生表命中 legacy_alias · x_user_id None · lk set → session。
    """
    resp = client.get("/api/whoami", cookies={"x_user_id": "bob"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal_kind"] == "session"
    assert body["user_id"] == "bob"


def test_T302_query_user_yields_principal_kind_session(client: TestClient) -> None:
    """T302 · query ?user=carol (无 header 无 cookie) → principal_kind="session"。

    auth_mode="legacy_alias" (query 命中),x_user_id=None,legacy_user_key=query 值。
    """
    resp = client.get("/api/whoami", params={"user": "carol"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal_kind"] == "session"
    assert body["user_id"] == "carol"


def test_T303_no_credential_yields_anonymous(client: TestClient) -> None:
    """T303 · 全无 legacy 线索 → principal_kind="anonymous" · user_id=None。"""
    resp = client.get("/api/whoami")
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal_kind"] == "anonymous"
    assert body["user_id"] is None


def test_T304_priority_header_over_cookie_over_query(client: TestClient) -> None:
    """T304 · 优先级链:X-User-Id header > cookie x_user_id > query ?user=。

    三通道同时命中时:
    - x_user_id header 原值 = "alice"(header)
    - legacy_user_key = cookie > query > x_user_id 派生 = "bob"(middleware 现有实现)
    - user_id 响应字段 = x_user_id or legacy_user_key = "alice" (header 胜出)
    - principal_kind = legacy_alias + x_user_id set → "user"
    """
    resp = client.get(
        "/api/whoami?user=carol",
        headers={"X-User-Id": "alice"},
        cookies={"x_user_id": "bob"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["principal_kind"] == "user"
    assert body["user_id"] == "alice", (
        "header X-User-Id must win over cookie/query for user_id"
    )


# --------------------------------------------------------------------------- #
# T305 · schema pin                                                            #
# --------------------------------------------------------------------------- #


def test_T305_response_schema_pin_five_fields_exact(client: TestClient) -> None:
    """T305 · WhoamiResponse 响应体恒 5 字段 · 无额外字段。"""
    resp = client.get("/api/whoami", headers={"X-User-Id": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "principal_kind",
        "user_id",
        "workspace_id",
        "project_id",
        "request_id",
    }
    # 字段类型 sanity check
    assert isinstance(body["principal_kind"], str)
    assert body["principal_kind"] in {"user", "session", "anonymous"}
    assert isinstance(body["request_id"], str) and body["request_id"]
    assert body["user_id"] is None or isinstance(body["user_id"], str)
    assert body["workspace_id"] is None or isinstance(body["workspace_id"], str)
    assert body["project_id"] is None or isinstance(body["project_id"], str)


# --------------------------------------------------------------------------- #
# T306 · 零明文密钥/token 泄漏                                                  #
# --------------------------------------------------------------------------- #


_SECRET_SENTINELS = (
    "password",
    "secret",
    "Bearer",
    "Authorization",
    "api_key",
    "access_token",
)


def test_T306_response_body_has_no_secret_sentinel(client: TestClient) -> None:
    """T306 · principal identity 响应体不得携带密钥类字段字面量 (case-insensitive)。

    向请求塞入哨兵值,验证响应体既不回显 sentinel value 也不出现 sentinel key。
    """
    resp = client.get(
        "/api/whoami",
        headers={
            "X-User-Id": "alice",
            "Authorization": "Bearer sk-TEST-DO-NOT-LOG",
            "X-Api-Key": "should-not-leak-secret",
        },
        cookies={"password": "leak-secret-123"},
    )
    assert resp.status_code == 200
    body_text = resp.text.lower()
    for sentinel in _SECRET_SENTINELS:
        assert sentinel.lower() not in body_text, (
            f"principal identity response leaked sentinel {sentinel!r}: {resp.text}"
        )


# --------------------------------------------------------------------------- #
# T307 · request_id 复用 / uuid4 生成                                           #
# --------------------------------------------------------------------------- #


def test_T307_request_id_reuse_and_generate(client: TestClient) -> None:
    """T307 · X-Request-Id header 复用 + 缺失时 uuid4 hex 生成 (middleware 事实格式)。

    middleware 实现 (`app/api/context.py::_build_context`) 使用 `uuid.uuid4().hex`
    = 32 位小写十六进制,无前缀。断言按事实实现走,不假设 `req-<hex>` 前缀。
    """
    # 复用路径
    incoming_rid = "test-rid-perm-pr-1-T307-reuse"
    resp = client.get("/api/whoami", headers={"X-Request-Id": incoming_rid})
    assert resp.status_code == 200
    assert resp.json()["request_id"] == incoming_rid
    assert resp.headers.get("X-Request-Id") == incoming_rid

    # 生成路径 · uuid4().hex
    resp2 = client.get("/api/whoami")
    assert resp2.status_code == 200
    gen_rid = resp2.json()["request_id"]
    assert gen_rid == resp2.headers.get("X-Request-Id")
    assert re.fullmatch(r"[0-9a-f]{32}", gen_rid), (
        f"middleware-generated request_id must be uuid4().hex (32 lowercase hex), got {gen_rid!r}"
    )


# --------------------------------------------------------------------------- #
# T308 · principal_kind 派生表 5 组组合单元测试                                  #
# --------------------------------------------------------------------------- #


def _make_ctx(
    *,
    auth_mode: str,
    x_user_id: Optional[str],
    legacy_user_key: Optional[str],
) -> RequestContext:
    return RequestContext(
        request_id="rid-fixture",
        legacy_user_key=legacy_user_key,
        x_user_id=x_user_id,
        workspace_id=None,
        project_id=None,
        client_id=None,
        ip=None,
        user_agent=None,
        auth_mode=auth_mode,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("auth_mode", "x_user_id", "legacy_user_key", "expected"),
    [
        # 1. authenticated_user 恒为 user (PR-3 后启用)
        ("authenticated_user", None, None, "user"),
        # 2. legacy_alias · x_user_id set → user
        ("legacy_alias", "alice", "alice", "user"),
        # 3. legacy_alias · x_user_id None · lk set → session
        ("legacy_alias", None, "bob", "session"),
        # 4. anonymous_or_legacy · lk set → session
        ("anonymous_or_legacy", None, "carol", "session"),
        # 5. anonymous_or_legacy · lk None → anonymous
        ("anonymous_or_legacy", None, None, "anonymous"),
    ],
)
def test_T308_derive_principal_kind_matrix(
    auth_mode: str,
    x_user_id: Optional[str],
    legacy_user_key: Optional[str],
    expected: str,
) -> None:
    """T308 · `_derive_principal_kind` 5 组派生组合 (纯函数 · 不走 HTTP 层)。"""
    from main import _derive_principal_kind  # type: ignore[import-untyped]

    ctx = _make_ctx(
        auth_mode=auth_mode,
        x_user_id=x_user_id,
        legacy_user_key=legacy_user_key,
    )
    assert _derive_principal_kind(ctx) == expected


# --------------------------------------------------------------------------- #
# T309 · /api/whoami 走完整 middleware 栈 · 非 fallback ctx                     #
# --------------------------------------------------------------------------- #


def test_T309_whoami_reads_live_context_not_fallback(client: TestClient) -> None:
    """T309 · `/api/whoami` 走完整 middleware 栈 · get_request_context() 命中 ContextVar。

    验证方式:显式 X-Request-Id 头 → 响应 body.request_id 必须等于 header 值。
    若命中 fallback ctx,fallback 会生成新 uuid4().hex,不可能与 header 值相等。
    """
    marker = "T309-live-ctx-perm-pr-1-marker"
    resp = client.get("/api/whoami", headers={"X-Request-Id": marker})
    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == marker, (
        "get_request_context() must read the middleware-set ctx from ContextVar, "
        "not the fallback ctx (fallback generates fresh uuid4().hex)"
    )
    # middleware 也把 header 回写到响应
    assert resp.headers.get("X-Request-Id") == marker

    # 同时验证 /api/whoami 确实注册在 main.app 上 (挂载存在断言)
    import main as _main  # type: ignore[import-untyped]

    whoami_routes = [
        r for r in _main.app.routes
        if isinstance(r, Route) and r.path == "/api/whoami"
    ]
    assert whoami_routes, "/api/whoami must be registered on main.app"
    assert "GET" in whoami_routes[0].methods
