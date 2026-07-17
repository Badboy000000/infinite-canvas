"""Schema 校验单元测试（权限 PR-0）。

- 8 类 identity JSON 文件的正例（合法 payload → 返回原对象）。
- 反例覆盖：
  - 顶层非 object
  - `_schema_version` 缺失 / 值错
  - 必填字段缺失
  - 字段类型错
  - 枚举值超出白名单
  - map key 与 record.id 不一致
"""
from __future__ import annotations

import pytest

from app.identity.schema import (
    SCHEMA_VERSION,
    BUILTIN_ROLES,
    SchemaValidationError,
    validate_auth_migration_state_file,
    validate_memberships_file,
    validate_resource_acl_file,
    validate_role_permissions_file,
    validate_roles_file,
    validate_user_aliases_file,
    validate_users_file,
    validate_workspaces_file,
)


# ---------------------------------------------------------------------------
# users.json
# ---------------------------------------------------------------------------


def test_validate_users_file_accepts_empty() -> None:
    payload = {"_schema_version": 1, "users": {}}
    assert validate_users_file(payload) == payload


def test_validate_users_file_accepts_single_bootstrap_user() -> None:
    payload = {
        "_schema_version": 1,
        "users": {
            "u1": {
                "id": "u1",
                "username": "system_admin",
                "status": "bootstrap_pending",
                "created_at": "2026-07-17T00:00:00+00:00",
            }
        },
    }
    assert validate_users_file(payload) == payload


def test_validate_users_file_rejects_non_object_top_level() -> None:
    with pytest.raises(SchemaValidationError):
        validate_users_file([])


def test_validate_users_file_rejects_missing_schema_version() -> None:
    with pytest.raises(SchemaValidationError):
        validate_users_file({"users": {}})


def test_validate_users_file_rejects_wrong_schema_version() -> None:
    with pytest.raises(SchemaValidationError):
        validate_users_file({"_schema_version": 2, "users": {}})


def test_validate_users_file_rejects_missing_required_field() -> None:
    with pytest.raises(SchemaValidationError):
        validate_users_file(
            {
                "_schema_version": 1,
                "users": {"u1": {"id": "u1", "username": "x"}},
            }
        )


def test_validate_users_file_rejects_wrong_status() -> None:
    with pytest.raises(SchemaValidationError):
        validate_users_file(
            {
                "_schema_version": 1,
                "users": {
                    "u1": {
                        "id": "u1",
                        "username": "x",
                        "status": "unknown",
                        "created_at": "2026-07-17T00:00:00+00:00",
                    }
                },
            }
        )


def test_validate_users_file_rejects_key_id_mismatch() -> None:
    with pytest.raises(SchemaValidationError):
        validate_users_file(
            {
                "_schema_version": 1,
                "users": {
                    "u1": {
                        "id": "different-id",
                        "username": "x",
                        "status": "active",
                        "created_at": "2026-07-17T00:00:00+00:00",
                    }
                },
            }
        )


# ---------------------------------------------------------------------------
# user_aliases.json
# ---------------------------------------------------------------------------


def test_validate_aliases_file_accepts_empty_list() -> None:
    payload = {"_schema_version": 1, "aliases": []}
    assert validate_user_aliases_file(payload) == payload


def test_validate_aliases_file_accepts_x_user_id() -> None:
    payload = {
        "_schema_version": 1,
        "aliases": [
            {
                "id": "a1",
                "kind": "x_user_id",
                "legacy_user_key": "some-legacy-user",
                "created_at": "2026-07-17T00:00:00+00:00",
            }
        ],
    }
    assert validate_user_aliases_file(payload) == payload


def test_validate_aliases_file_rejects_wrong_kind() -> None:
    with pytest.raises(SchemaValidationError):
        validate_user_aliases_file(
            {
                "_schema_version": 1,
                "aliases": [
                    {
                        "id": "a1",
                        "kind": "not_a_valid_kind",
                        "legacy_user_key": "x",
                        "created_at": "2026-07-17T00:00:00+00:00",
                    }
                ],
            }
        )


def test_validate_aliases_file_rejects_non_list_aliases() -> None:
    with pytest.raises(SchemaValidationError):
        validate_user_aliases_file({"_schema_version": 1, "aliases": {}})


# ---------------------------------------------------------------------------
# workspaces.json
# ---------------------------------------------------------------------------


def test_validate_workspaces_file_accepts_empty() -> None:
    payload = {"_schema_version": 1, "workspaces": {}}
    assert validate_workspaces_file(payload) == payload


def test_validate_workspaces_file_accepts_default_workspace() -> None:
    payload = {
        "_schema_version": 1,
        "workspaces": {
            "ws-default": {
                "id": "ws-default",
                "name": "默认工作区",
                "created_at": "2026-07-17T00:00:00+00:00",
            }
        },
    }
    assert validate_workspaces_file(payload) == payload


def test_validate_workspaces_file_rejects_missing_name() -> None:
    with pytest.raises(SchemaValidationError):
        validate_workspaces_file(
            {
                "_schema_version": 1,
                "workspaces": {
                    "ws1": {
                        "id": "ws1",
                        "created_at": "2026-07-17T00:00:00+00:00",
                    }
                },
            }
        )


# ---------------------------------------------------------------------------
# memberships.json
# ---------------------------------------------------------------------------


def test_validate_memberships_file_accepts_empty() -> None:
    payload = {
        "_schema_version": 1,
        "workspace_memberships": [],
        "project_memberships": [],
    }
    assert validate_memberships_file(payload) == payload


def test_validate_memberships_file_accepts_workspace_admin() -> None:
    payload = {
        "_schema_version": 1,
        "workspace_memberships": [
            {
                "workspace_id": "ws-default",
                "user_id": "u1",
                "role": "workspace_admin",
                "created_at": "2026-07-17T00:00:00+00:00",
            }
        ],
        "project_memberships": [],
    }
    assert validate_memberships_file(payload) == payload


def test_validate_memberships_file_rejects_missing_role() -> None:
    with pytest.raises(SchemaValidationError):
        validate_memberships_file(
            {
                "_schema_version": 1,
                "workspace_memberships": [
                    {
                        "workspace_id": "ws-default",
                        "user_id": "u1",
                        "created_at": "2026-07-17T00:00:00+00:00",
                    }
                ],
                "project_memberships": [],
            }
        )


def test_validate_memberships_file_rejects_missing_list_key() -> None:
    with pytest.raises(SchemaValidationError):
        validate_memberships_file(
            {
                "_schema_version": 1,
                "workspace_memberships": [],
            }
        )


# ---------------------------------------------------------------------------
# roles.json
# ---------------------------------------------------------------------------


def test_validate_roles_file_accepts_builtin_five() -> None:
    """确认内置五档角色能通过 schema 校验（bootstrap 写入的正例）。"""
    roles = {}
    for key, meta in BUILTIN_ROLES.items():
        roles[key] = {
            "key": key,
            "display_name": meta["display_name"],
            "description": meta["description"],
            "scope": meta["scope"],
            "created_at": "2026-07-17T00:00:00+00:00",
        }
    payload = {"_schema_version": 1, "roles": roles}
    assert validate_roles_file(payload) == payload
    # 且五档齐全
    assert set(roles.keys()) == {
        "system_admin",
        "workspace_admin",
        "project_admin",
        "editor",
        "viewer",
    }


def test_validate_roles_file_rejects_wrong_scope() -> None:
    with pytest.raises(SchemaValidationError):
        validate_roles_file(
            {
                "_schema_version": 1,
                "roles": {
                    "x": {
                        "key": "x",
                        "display_name": "X",
                        "description": "x",
                        "scope": "unknown",
                        "created_at": "2026-07-17T00:00:00+00:00",
                    }
                },
            }
        )


# ---------------------------------------------------------------------------
# role_permissions.json
# ---------------------------------------------------------------------------


def test_validate_role_permissions_file_accepts_empty_map() -> None:
    """本 PR 落地形态：空 map；PR-4 才填内容。"""
    payload = {"_schema_version": 1, "role_permissions": {}}
    assert validate_role_permissions_file(payload) == payload


def test_validate_role_permissions_file_accepts_placeholder_note() -> None:
    """允许 `_note` 等元数据字段共存（本 PR 初始文件带一段说明性注释）。"""
    payload = {
        "_schema_version": 1,
        "_note": "PR-4 will fill",
        "role_permissions": {},
    }
    # validator 只关心 `_schema_version` 与 `role_permissions`；其它字段忽略
    result = validate_role_permissions_file(payload)
    assert result["_schema_version"] == 1


def test_validate_role_permissions_file_rejects_non_bool_allow() -> None:
    with pytest.raises(SchemaValidationError):
        validate_role_permissions_file(
            {
                "_schema_version": 1,
                "role_permissions": {"editor": {"canvas.read": "yes"}},
            }
        )


# ---------------------------------------------------------------------------
# resource_acl.json
# ---------------------------------------------------------------------------


def test_validate_resource_acl_file_accepts_empty() -> None:
    payload = {"_schema_version": 1, "acl": []}
    assert validate_resource_acl_file(payload) == payload


def test_validate_resource_acl_file_accepts_entry() -> None:
    payload = {
        "_schema_version": 1,
        "acl": [
            {
                "id": "acl1",
                "resource_type": "canvas",
                "resource_id": "canvas-x",
                "subject_kind": "user",
                "subject_id": "u1",
                "role": "editor",
                "created_at": "2026-07-17T00:00:00+00:00",
            }
        ],
    }
    assert validate_resource_acl_file(payload) == payload


def test_validate_resource_acl_file_rejects_wrong_subject_kind() -> None:
    with pytest.raises(SchemaValidationError):
        validate_resource_acl_file(
            {
                "_schema_version": 1,
                "acl": [
                    {
                        "id": "acl1",
                        "resource_type": "canvas",
                        "resource_id": "canvas-x",
                        "subject_kind": "group",
                        "subject_id": "g1",
                        "role": "editor",
                        "created_at": "2026-07-17T00:00:00+00:00",
                    }
                ],
            }
        )


# ---------------------------------------------------------------------------
# auth_migration_state.json
# ---------------------------------------------------------------------------


def test_validate_auth_migration_state_accepts_initial() -> None:
    payload = {
        "_schema_version": 1,
        "bootstrap_completed_at": None,
        "legacy_mapping_completed_at": None,
        "notes": [],
    }
    assert validate_auth_migration_state_file(payload) == payload


def test_validate_auth_migration_state_accepts_completed() -> None:
    payload = {
        "_schema_version": 1,
        "bootstrap_completed_at": "2026-07-17T00:00:00+00:00",
        "legacy_mapping_completed_at": None,
        "notes": ["bootstrap done"],
    }
    assert validate_auth_migration_state_file(payload) == payload


def test_validate_auth_migration_state_rejects_non_string_note() -> None:
    with pytest.raises(SchemaValidationError):
        validate_auth_migration_state_file(
            {
                "_schema_version": 1,
                "bootstrap_completed_at": None,
                "legacy_mapping_completed_at": None,
                "notes": [123],
            }
        )


def test_validate_auth_migration_state_rejects_non_list_notes() -> None:
    with pytest.raises(SchemaValidationError):
        validate_auth_migration_state_file(
            {
                "_schema_version": 1,
                "bootstrap_completed_at": None,
                "legacy_mapping_completed_at": None,
                "notes": "not a list",
            }
        )


# ---------------------------------------------------------------------------
# 常量断言
# ---------------------------------------------------------------------------


def test_schema_version_is_one() -> None:
    assert SCHEMA_VERSION == 1


def test_builtin_roles_have_five_entries() -> None:
    assert set(BUILTIN_ROLES.keys()) == {
        "system_admin",
        "workspace_admin",
        "project_admin",
        "editor",
        "viewer",
    }
    # 每个都必须有 display_name / description / scope
    for key, meta in BUILTIN_ROLES.items():
        assert "display_name" in meta and meta["display_name"], key
        assert "description" in meta and meta["description"], key
        assert meta["scope"] in ("system", "workspace", "project"), key
