"""`legacy_mapper` 单元测试（权限 PR-2 · Wave 3-N.8 Batch 1 主线 A）。

覆盖 T20-T29（反审矩阵 · legacy_mapper 单元）：

- `resolve_legacy_owner`：空字符串 / None / 匹配 / 不匹配 · 4 分支。
- `resolve_legacy_user_key`：4 分支。
- `fill_default_workspace_project`：缺字段 / 已有字段 · 2 分支。

所有断言只依赖 `app.identity.legacy_mapper` 与 `app.identity.schema`，
**不落盘**、**不接触项目 data/**。
"""
from __future__ import annotations

from typing import List

import pytest

from app.identity.legacy_mapper import (
    DEFAULT_PROJECT_ID,
    DEFAULT_WORKSPACE_ID,
    fill_default_workspace_project,
    resolve_legacy_owner,
    resolve_legacy_user_key,
)
from app.identity.schema import UserAliasRecord

TS = "2026-07-24T00:00:00+00:00"
WS = DEFAULT_WORKSPACE_ID


def _alias(
    kind: str, key: str, alias_id: str = "alias-a", user_id: str | None = None
) -> UserAliasRecord:
    return {
        "id": alias_id,
        "user_id": user_id,
        "kind": kind,  # type: ignore[typeddict-item]
        "legacy_user_key": key,
        "workspace_id": WS,
        "created_at": TS,
    }


@pytest.fixture()
def sample_aliases() -> List[UserAliasRecord]:
    return [
        _alias("x_user_id", "user-a", "alias-1"),
        _alias("x_user_id", "user-b", "alias-2"),
        _alias("conversation_dir", "conv-c", "alias-3"),
        _alias("cookie_user", "Alice", "alias-4"),
    ]


# ---------------------------------------------------------------------------
# T20-T23: resolve_legacy_owner 4 分支
# ---------------------------------------------------------------------------


def test_T20_resolve_legacy_owner_none_returns_none(
    sample_aliases: List[UserAliasRecord],
) -> None:
    assert resolve_legacy_owner(None, sample_aliases) is None


def test_T21_resolve_legacy_owner_empty_returns_none(
    sample_aliases: List[UserAliasRecord],
) -> None:
    assert resolve_legacy_owner("", sample_aliases) is None
    assert resolve_legacy_owner("   ", sample_aliases) is None


def test_T22_resolve_legacy_owner_match(
    sample_aliases: List[UserAliasRecord],
) -> None:
    got = resolve_legacy_owner("Alice", sample_aliases)
    assert got is not None
    assert got["id"] == "alias-4"
    assert got["kind"] == "cookie_user"

    # 空白容忍：trim 后仍能匹配
    got_ws = resolve_legacy_owner("  Alice  ", sample_aliases)
    assert got_ws is not None
    assert got_ws["id"] == "alias-4"


def test_T23_resolve_legacy_owner_no_match(
    sample_aliases: List[UserAliasRecord],
) -> None:
    assert resolve_legacy_owner("nobody", sample_aliases) is None


# ---------------------------------------------------------------------------
# T24-T27: resolve_legacy_user_key 4 分支
# ---------------------------------------------------------------------------


def test_T24_resolve_legacy_user_key_none_returns_none(
    sample_aliases: List[UserAliasRecord],
) -> None:
    assert resolve_legacy_user_key(None, sample_aliases) is None


def test_T25_resolve_legacy_user_key_empty_returns_none(
    sample_aliases: List[UserAliasRecord],
) -> None:
    assert resolve_legacy_user_key("", sample_aliases) is None
    assert resolve_legacy_user_key("   ", sample_aliases) is None


def test_T26_resolve_legacy_user_key_match(
    sample_aliases: List[UserAliasRecord],
) -> None:
    got = resolve_legacy_user_key("user-a", sample_aliases)
    assert got is not None
    assert got["id"] == "alias-1"
    assert got["kind"] == "x_user_id"


def test_T27_resolve_legacy_user_key_no_match_or_wrong_kind(
    sample_aliases: List[UserAliasRecord],
) -> None:
    # 完全不存在
    assert resolve_legacy_user_key("nobody", sample_aliases) is None
    # 存在但 kind 不匹配（`conv-c` 是 conversation_dir，不是 x_user_id）
    assert resolve_legacy_user_key("conv-c", sample_aliases) is None
    # 存在但 kind=cookie_user 也不匹配（"Alice"）
    assert resolve_legacy_user_key("Alice", sample_aliases) is None


# ---------------------------------------------------------------------------
# T28-T29: fill_default_workspace_project 2 分支
# ---------------------------------------------------------------------------


def test_T28_fill_default_when_missing() -> None:
    record = {"id": "canvas-x", "owner": "Alice"}
    out = fill_default_workspace_project(record)
    assert out["workspace_id"] == DEFAULT_WORKSPACE_ID
    assert out["project_id"] == DEFAULT_PROJECT_ID
    # 原字段保留
    assert out["id"] == "canvas-x"
    assert out["owner"] == "Alice"
    # 输入不被改动
    assert "workspace_id" not in record
    assert "project_id" not in record


def test_T29_fill_default_preserves_existing() -> None:
    record = {
        "id": "canvas-x",
        "workspace_id": "custom-ws",
        "project_id": "custom-pj",
    }
    out = fill_default_workspace_project(record)
    assert out["workspace_id"] == "custom-ws"
    assert out["project_id"] == "custom-pj"

    # 空字符串视作缺失，回填默认
    record2 = {"workspace_id": "", "project_id": "   "}
    out2 = fill_default_workspace_project(record2)
    assert out2["workspace_id"] == DEFAULT_WORKSPACE_ID
    assert out2["project_id"] == DEFAULT_PROJECT_ID
