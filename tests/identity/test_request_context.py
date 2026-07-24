"""`RequestContext` frozen dataclass 契约测试（权限 PR-0）。

覆盖：
- frozen 语义（对已实例化对象的赋值抛 `dataclasses.FrozenInstanceError`）。
- 字段清单（严格与协调纲要"字段冻结契约"一致；额外字段视为破坏契约）。
- `auth_mode` 三态字面量。
- `dataclasses.replace(ctx, request_id="new")` 语义（新对象、原对象不变）。
"""
from __future__ import annotations

import dataclasses
from typing import get_args, get_type_hints

import pytest

from app.identity.request_context import AuthMode, RequestContext


# ---------------------------------------------------------------------------
# 字段清单冻结
# ---------------------------------------------------------------------------


EXPECTED_FIELDS: list[str] = [
    # Wave 0 最小契约（9 字段 · 权限 PR-0 冻结 · 位置 + 名字 + 类型不许改）
    "request_id",
    "legacy_user_key",
    "x_user_id",
    "workspace_id",
    "project_id",
    "client_id",
    "ip",
    "user_agent",
    "auth_mode",
    # 权限 PR-3 尾附加长期字段（4 字段 · 全部 Optional 带默认值 · 只增不改
    # · PR-0 docstring 显式允许："长期字段（principal_kind / scopes /
    # session_id / api_key_id）由 PR-3 / PR-4 落地时另加"）
    "principal_kind",
    "scopes",
    "session_id",
    "api_key_id",
]


def test_request_context_field_names_frozen() -> None:
    actual = [f.name for f in dataclasses.fields(RequestContext)]
    assert actual == EXPECTED_FIELDS, (
        "RequestContext 字段清单已被协调纲要冻结（Wave 0 前 9 字段 + 权限 PR-3 "
        "尾附加 4 长期字段）；擅自增删字段视为破坏冻结契约。扩字段规则："
        "只允许尾附加带默认值的新长期字段，前 9 字段位置永久锁定。"
    )


def test_request_context_field_count_is_thirteen() -> None:
    """字段总数 = 9(Wave 0)+ 4(权限 PR-3 长期字段)= 13"""
    assert len(dataclasses.fields(RequestContext)) == 13


def test_request_context_wave0_first_nine_fields_frozen() -> None:
    """Wave 0 最小契约:前 9 字段位置 + 名字 + 类型永久冻结"""
    actual_first_nine = [f.name for f in dataclasses.fields(RequestContext)][:9]
    assert actual_first_nine == EXPECTED_FIELDS[:9]


def test_request_context_is_frozen() -> None:
    assert getattr(RequestContext, "__dataclass_params__").frozen is True


def test_request_id_is_required_str() -> None:
    hints = get_type_hints(RequestContext)
    assert hints["request_id"] is str


def test_auth_mode_literal_values_frozen() -> None:
    """`auth_mode` 三个字面量不许改：anonymous_or_legacy / authenticated_user / legacy_alias。"""
    values = set(get_args(AuthMode))
    assert values == {
        "anonymous_or_legacy",
        "authenticated_user",
        "legacy_alias",
    }, (
        "auth_mode 三态字面量已被协调纲要冻结；擅自增删字面量视为破坏 Wave 0 "
        "字段冻结契约。"
    )


# ---------------------------------------------------------------------------
# 实例化与 frozen 行为
# ---------------------------------------------------------------------------


def _make_ctx(**overrides) -> RequestContext:
    defaults = dict(
        request_id="req-1",
        legacy_user_key=None,
        x_user_id=None,
        workspace_id=None,
        project_id=None,
        client_id=None,
        ip=None,
        user_agent=None,
        auth_mode="anonymous_or_legacy",
    )
    defaults.update(overrides)
    return RequestContext(**defaults)


def test_can_instantiate_minimum_anonymous() -> None:
    ctx = _make_ctx()
    assert ctx.request_id == "req-1"
    assert ctx.auth_mode == "anonymous_or_legacy"
    assert ctx.workspace_id is None


def test_can_instantiate_authenticated_user() -> None:
    ctx = _make_ctx(
        request_id="req-2",
        x_user_id="user-x",
        workspace_id="ws-1",
        project_id="proj-1",
        auth_mode="authenticated_user",
    )
    assert ctx.auth_mode == "authenticated_user"
    assert ctx.workspace_id == "ws-1"


def test_can_instantiate_legacy_alias() -> None:
    ctx = _make_ctx(
        request_id="req-3",
        legacy_user_key="legacy-user-abc",
        auth_mode="legacy_alias",
    )
    assert ctx.auth_mode == "legacy_alias"
    assert ctx.legacy_user_key == "legacy-user-abc"


def test_frozen_setattr_raises() -> None:
    ctx = _make_ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.request_id = "attempt-mutation"  # type: ignore[misc]


def test_frozen_delattr_raises() -> None:
    ctx = _make_ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        del ctx.request_id  # type: ignore[misc]


# ---------------------------------------------------------------------------
# dataclasses.replace 语义
# ---------------------------------------------------------------------------


def test_replace_produces_new_instance() -> None:
    ctx = _make_ctx(request_id="req-old", workspace_id="ws-1")
    new_ctx = dataclasses.replace(ctx, request_id="req-new")
    assert new_ctx is not ctx
    assert new_ctx.request_id == "req-new"
    assert new_ctx.workspace_id == "ws-1"  # 其它字段保留


def test_replace_does_not_mutate_original() -> None:
    ctx = _make_ctx(request_id="req-old", auth_mode="anonymous_or_legacy")
    _ = dataclasses.replace(ctx, auth_mode="authenticated_user")
    assert ctx.request_id == "req-old"
    assert ctx.auth_mode == "anonymous_or_legacy"


# ---------------------------------------------------------------------------
# equality / hashing（frozen dataclass 天然支持）
# ---------------------------------------------------------------------------


def test_two_contexts_with_same_fields_are_equal() -> None:
    a = _make_ctx(request_id="same")
    b = _make_ctx(request_id="same")
    assert a == b


def test_frozen_context_is_hashable() -> None:
    ctx = _make_ctx()
    # frozen dataclass 默认 eq=True + frozen=True 会生成 __hash__
    assert hash(ctx) == hash(_make_ctx())
