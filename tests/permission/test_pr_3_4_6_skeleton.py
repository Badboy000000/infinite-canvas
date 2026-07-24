"""权限 PR-3 + PR-4 + PR-6 skeleton 契约测试（Wave 3-N.8 Batch 4）。

**测试 IDs**：T310-T339(30 tests)
- T310-T319:PR-3 RequestContext 扩字段 + derive_principal_kind
- T320-T329:PR-4 PermissionService allow/check/capabilities/resolve_role
- T330-T339:PR-6 build_capabilities + CapabilitiesResponse
"""
from __future__ import annotations

import os

import pytest

from app.identity.request_context import (
    AuthMode,
    PrincipalKind,
    RequestContext,
    derive_principal_kind,
)
from app.services.permission import (
    DEFAULT_ACTIONS,
    DEFAULT_PERMISSION_MATRIX,
    DEFAULT_PERMISSION_SERVICE,
    DEFAULT_ROLES,
    PermissionDenied,
    PermissionService,
    is_enforce_enabled,
)
from app.services.permission.capabilities import (
    CapabilitiesResponse,
    build_capabilities,
)


def _ctx(
    *,
    auth_mode: AuthMode = "anonymous_or_legacy",
    x_user_id: str | None = None,
    legacy_user_key: str | None = None,
    principal_kind: PrincipalKind | None = None,
    scopes: tuple[str, ...] | None = None,
    session_id: str | None = None,
    api_key_id: str | None = None,
) -> RequestContext:
    return RequestContext(
        request_id="req-test",
        legacy_user_key=legacy_user_key,
        x_user_id=x_user_id,
        workspace_id=None,
        project_id=None,
        client_id=None,
        ip=None,
        user_agent=None,
        auth_mode=auth_mode,
        principal_kind=principal_kind,
        scopes=scopes,
        session_id=session_id,
        api_key_id=api_key_id,
    )


# ---------------------------------------------------------------------------
# T310-T319: PR-3 RequestContext 扩字段 + derive_principal_kind
# ---------------------------------------------------------------------------


class TestPR3RequestContextExtension:
    """权限 PR-3:RequestContext 扩 4 长期字段契约"""

    def test_T310_default_all_extended_fields_none(self):
        """扩字段全部默认 None（Wave 0 兼容承诺）"""
        ctx = RequestContext(
            request_id="rid",
            legacy_user_key=None,
            x_user_id=None,
            workspace_id=None,
            project_id=None,
            client_id=None,
            ip=None,
            user_agent=None,
            auth_mode="anonymous_or_legacy",
        )
        assert ctx.principal_kind is None
        assert ctx.scopes is None
        assert ctx.session_id is None
        assert ctx.api_key_id is None

    def test_T311_extended_fields_accept_values(self):
        """扩字段可显式赋值（frozen · 全部只读）"""
        ctx = _ctx(
            principal_kind="user",
            scopes=("canvas:read", "canvas:write"),
            session_id="sess-1",
            api_key_id="ak-1",
        )
        assert ctx.principal_kind == "user"
        assert ctx.scopes == ("canvas:read", "canvas:write")
        assert ctx.session_id == "sess-1"
        assert ctx.api_key_id == "ak-1"

    def test_T312_frozen_dataclass_immutable(self):
        """frozen 语义:扩字段也不可修改"""
        ctx = _ctx(principal_kind="user")
        with pytest.raises(Exception):  # FrozenInstanceError
            ctx.principal_kind = "session"  # type: ignore[misc]

    def test_T313_scopes_uses_tuple_hashable(self):
        """scopes 用 Tuple[str, ...] 保 hashable"""
        ctx = _ctx(scopes=("a", "b"))
        # frozen dataclass with tuple scopes 应 hashable
        hash(ctx)

    def test_T314_original_9_fields_position_frozen(self):
        """Wave 0 前 9 字段位置冻结 · dataclass fields 顺序"""
        from dataclasses import fields

        names = [f.name for f in fields(RequestContext)]
        assert names[:9] == [
            "request_id",
            "legacy_user_key",
            "x_user_id",
            "workspace_id",
            "project_id",
            "client_id",
            "ip",
            "user_agent",
            "auth_mode",
        ]

    def test_T315_extended_4_fields_appended_tail(self):
        """新 4 字段全部尾附加 · 与冻结契约兼容"""
        from dataclasses import fields

        names = [f.name for f in fields(RequestContext)]
        assert names[9:] == [
            "principal_kind",
            "scopes",
            "session_id",
            "api_key_id",
        ]

    @pytest.mark.parametrize(
        "auth_mode,x_user_id,legacy_user_key,expected",
        [
            ("authenticated_user", None, None, "user"),
            ("authenticated_user", "alice", None, "user"),
            ("legacy_alias", "alice", None, "user"),
            ("legacy_alias", "alice", "alice", "user"),
            ("legacy_alias", None, "cookie-bob", "session"),
            ("anonymous_or_legacy", None, "cookie-carol", "session"),
            ("anonymous_or_legacy", None, None, "anonymous"),
        ],
        ids=[
            "auth_no_alias",
            "auth_with_x_user_id",
            "legacy_x_user_id_set",
            "legacy_both_set",
            "legacy_only_legacy_key",
            "anon_with_legacy_key",
            "anon_no_key",
        ],
    )
    def test_T316_derive_principal_kind_table(
        self, auth_mode, x_user_id, legacy_user_key, expected
    ):
        """派生表 5 行 · 7 组参数化"""
        ctx = _ctx(
            auth_mode=auth_mode,
            x_user_id=x_user_id,
            legacy_user_key=legacy_user_key,
        )
        assert derive_principal_kind(ctx) == expected

    def test_T317_derive_pure_function_no_ctx_mutation(self):
        """派生函数无副作用 · 不改 ctx.principal_kind"""
        ctx = _ctx(auth_mode="authenticated_user")
        assert ctx.principal_kind is None
        derive_principal_kind(ctx)
        assert ctx.principal_kind is None

    def test_T318_2_existing_call_sites_still_work(self):
        """现有 2 处 kwarg 构造点零破坏(不传扩字段)"""
        # 模拟 app/api/context.py::_build_context 的构造姿势
        ctx = RequestContext(
            request_id="rid",
            legacy_user_key=None,
            x_user_id=None,
            workspace_id=None,
            project_id=None,
            client_id=None,
            ip=None,
            user_agent=None,
            auth_mode="anonymous_or_legacy",
        )
        assert ctx.principal_kind is None

    def test_T319_no_default_for_original_9_fields(self):
        """前 9 字段无默认值 · 缺一即 TypeError(冻结契约保护)"""
        with pytest.raises(TypeError):
            RequestContext(request_id="rid")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# T320-T329: PR-4 PermissionService allow/check/capabilities/resolve_role
# ---------------------------------------------------------------------------


class TestPR4PermissionService:
    """权限 PR-4:PermissionService 骨架契约"""

    def test_T320_default_matrix_shape(self):
        """默认矩阵 4 role × 5 action 权限对齐治理方案"""
        assert set(DEFAULT_PERMISSION_MATRIX.keys()) == {
            "system_admin",
            "workspace_admin",
            "member",
            "viewer",
        }
        assert DEFAULT_PERMISSION_MATRIX["system_admin"] == DEFAULT_ACTIONS
        assert DEFAULT_PERMISSION_MATRIX["viewer"] == frozenset({"canvas:read"})

    @pytest.mark.parametrize(
        "role,action,expected",
        [
            ("system_admin", "canvas:read", True),
            ("system_admin", "workspace:admin", True),
            ("system_admin", "provider:manage", True),
            ("workspace_admin", "canvas:delete", True),
            ("workspace_admin", "provider:manage", False),  # 4/5 不含
            ("member", "canvas:read", True),
            ("member", "canvas:write", True),
            ("member", "canvas:delete", False),
            ("viewer", "canvas:read", True),
            ("viewer", "canvas:write", False),
        ],
        ids=[
            "sys_read",
            "sys_ws_admin",
            "sys_provider",
            "ws_delete",
            "ws_no_provider",
            "mem_read",
            "mem_write",
            "mem_no_delete",
            "view_read",
            "view_no_write",
        ],
    )
    def test_T321_allow_matrix(self, role, action, expected):
        """allow 覆盖矩阵 10 组"""
        svc = PermissionService()
        assert svc.allow(role, action) is expected

    def test_T322_allow_none_role_false(self):
        """role=None → False(未派生视为无权限)"""
        svc = PermissionService()
        assert svc.allow(None, "canvas:read") is False

    def test_T323_allow_unknown_role_false(self):
        """未知 role → False"""
        svc = PermissionService()
        assert svc.allow("unknown_role", "canvas:read") is False

    def test_T324_allow_unknown_action_false_no_wildcard(self):
        """未知 action → False(严禁 wildcard)"""
        svc = PermissionService()
        assert svc.allow("system_admin", "unknown:action") is False

    @pytest.mark.parametrize(
        "role,action,reason",
        [
            (None, "canvas:read", "principal_anonymous"),
            ("unknown", "canvas:read", "unknown_role"),
            ("member", "unknown:x", "unknown_action"),
            ("viewer", "canvas:write", "role_action_not_allowed"),
        ],
        ids=["none", "unknown_role", "unknown_action", "role_denied"],
    )
    def test_T325_check_raises_with_reason(self, role, action, reason):
        """check 抛 PermissionDenied 并附 reason"""
        svc = PermissionService()
        with pytest.raises(PermissionDenied) as ei:
            svc.check(role, action)
        assert ei.value.reason == reason
        assert ei.value.role == role
        assert ei.value.action == action

    def test_T326_check_pass_no_raise(self):
        """check 通过 → 无返回值 · 无异常"""
        svc = PermissionService()
        result = svc.check("system_admin", "canvas:read")
        assert result is None

    def test_T327_capabilities_shape(self):
        """capabilities 返回 frozenset · 稳定内容"""
        svc = PermissionService()
        assert svc.capabilities("viewer") == frozenset({"canvas:read"})
        assert svc.capabilities("member") == frozenset(
            {"canvas:read", "canvas:write"}
        )
        assert svc.capabilities(None) == frozenset()
        assert svc.capabilities("unknown") == frozenset()

    @pytest.mark.parametrize(
        "auth_mode,x_user_id,legacy,expected_role",
        [
            ("anonymous_or_legacy", None, None, "viewer"),  # anon
            ("anonymous_or_legacy", None, "k", "member"),  # session
            ("legacy_alias", "alice", None, "member"),  # user
            ("authenticated_user", None, None, "member"),  # user
        ],
        ids=["anon", "session", "legacy_user", "auth_user"],
    )
    def test_T328_resolve_role_from_ctx(
        self, auth_mode, x_user_id, legacy, expected_role
    ):
        """resolve_role skeleton 派生表:anon→viewer / 其他→member"""
        svc = PermissionService()
        ctx = _ctx(auth_mode=auth_mode, x_user_id=x_user_id, legacy_user_key=legacy)
        assert svc.resolve_role(ctx) == expected_role

    def test_T329_env_flag_defaults_off(self, monkeypatch):
        """PERMISSION_SERVICE_ENFORCE 默认 false"""
        monkeypatch.delenv("PERMISSION_SERVICE_ENFORCE", raising=False)
        assert is_enforce_enabled() is False
        # truthy 变体
        for v in ("1", "true", "yes", "on", "TRUE", "Yes"):
            monkeypatch.setenv("PERMISSION_SERVICE_ENFORCE", v)
            assert is_enforce_enabled() is True, v
        # falsy 变体
        for v in ("", "0", "false", "no", "off", "random"):
            monkeypatch.setenv("PERMISSION_SERVICE_ENFORCE", v)
            assert is_enforce_enabled() is False, v


# ---------------------------------------------------------------------------
# T330-T339: PR-6 build_capabilities + CapabilitiesResponse
# ---------------------------------------------------------------------------


class TestPR6BuildCapabilities:
    """权限 PR-6:capabilities API 骨架契约"""

    def test_T330_anonymous_returns_viewer_role(self):
        """匿名 ctx → viewer role + canvas:read 单项能力"""
        svc = PermissionService()
        ctx = _ctx(auth_mode="anonymous_or_legacy")
        resp = build_capabilities(svc, ctx)
        assert resp.principal_kind == "anonymous"
        assert resp.role == "viewer"
        assert resp.capabilities == ["canvas:read"]

    def test_T331_authenticated_returns_member_role(self):
        """认证用户 → member role + canvas:read/write 两项能力"""
        svc = PermissionService()
        ctx = _ctx(auth_mode="authenticated_user")
        resp = build_capabilities(svc, ctx)
        assert resp.principal_kind == "user"
        assert resp.role == "member"
        assert resp.capabilities == ["canvas:read", "canvas:write"]

    def test_T332_capabilities_sorted_stable(self):
        """capabilities 列表恒排序输出(sorted)"""
        svc = PermissionService()
        ctx = _ctx(auth_mode="authenticated_user")
        resp = build_capabilities(svc, ctx)
        assert resp.capabilities == sorted(resp.capabilities)

    def test_T333_uses_ctx_principal_kind_if_derived(self):
        """如 ctx.principal_kind 已派生 · 直接消费不重复派生"""
        svc = PermissionService()
        ctx = _ctx(auth_mode="anonymous_or_legacy", principal_kind="user")
        resp = build_capabilities(svc, ctx)
        assert resp.principal_kind == "user"  # 消费已派生值

    def test_T334_workspace_project_passed_through(self):
        """workspace_id / project_id 原值传递(骨架期不消费但保留)"""
        svc = PermissionService()
        ctx = _ctx(auth_mode="authenticated_user")
        resp = build_capabilities(
            svc, ctx, workspace_id="ws-1", project_id="p-1"
        )
        assert resp.workspace_id == "ws-1"
        assert resp.project_id == "p-1"

    def test_T335_response_frozen_dataclass(self):
        """CapabilitiesResponse 是 frozen dataclass"""
        svc = PermissionService()
        ctx = _ctx(auth_mode="anonymous_or_legacy")
        resp = build_capabilities(svc, ctx)
        with pytest.raises(Exception):
            resp.role = "member"  # type: ignore[misc]

    def test_T336_response_capabilities_list_type(self):
        """capabilities 字段类型 List[str](JSON 直接序列化)"""
        svc = PermissionService()
        ctx = _ctx(auth_mode="authenticated_user")
        resp = build_capabilities(svc, ctx)
        assert isinstance(resp.capabilities, list)
        assert all(isinstance(c, str) for c in resp.capabilities)

    def test_T337_response_json_serializable(self):
        """整个 response 结构 JSON 可序列化(通过 dataclass asdict)"""
        import json
        from dataclasses import asdict

        svc = PermissionService()
        ctx = _ctx(auth_mode="authenticated_user")
        resp = build_capabilities(svc, ctx)
        payload = asdict(resp)
        assert json.dumps(payload)  # 不抛就通过

    def test_T338_session_maps_to_member_role(self):
        """session 类型(legacy_alias without x_user_id) → member"""
        svc = PermissionService()
        ctx = _ctx(
            auth_mode="anonymous_or_legacy", legacy_user_key="cookie-bob"
        )
        resp = build_capabilities(svc, ctx)
        assert resp.principal_kind == "session"
        assert resp.role == "member"

    def test_T339_default_service_singleton_usable(self):
        """DEFAULT_PERMISSION_SERVICE 单例可直接消费"""
        ctx = _ctx(auth_mode="authenticated_user")
        resp = build_capabilities(DEFAULT_PERMISSION_SERVICE, ctx)
        assert resp.role == "member"
        assert "canvas:read" in resp.capabilities


# ---------------------------------------------------------------------------
# 契约锁:__all__ 白名单 · 未来 refactor 保护
# ---------------------------------------------------------------------------


def test_permission_module_all_contract():
    """app.services.permission 顶层 __all__ 契约"""
    from app.services import permission as m

    assert "PermissionService" in m.__all__
    assert "PermissionDenied" in m.__all__
    assert "DEFAULT_PERMISSION_MATRIX" in m.__all__


def test_capabilities_module_all_contract():
    """app.services.permission.capabilities 顶层 __all__ 契约"""
    from app.services.permission import capabilities as m

    assert "CapabilitiesResponse" in m.__all__
    assert "build_capabilities" in m.__all__
