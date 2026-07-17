"""`JsonIdentityStore` / `SqliteIdentityStore` 单元测试（权限 PR-0）。

覆盖：
- 空数据 fixture 下 9 个只读接口 + `write_auth_migration_state`。
- Bootstrap 后（fake bootstrapped fixture）的接口行为。
- `SqliteIdentityStore.__init__` 抛 NotImplementedError（其他方法同样）。
- 缺失 identity JSON 文件时 `FileNotFoundError`。

所有测试使用 `tmp_path` 隔离；**不接触** 项目 `data/identity/`。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.identity.store import JsonIdentityStore, SqliteIdentityStore


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _write(p: Path, payload) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


@pytest.fixture()
def empty_identity_dir(tmp_path: Path) -> Path:
    """A pristine identity dir with 8 initial JSON files (matches权限 PR-0 提交物)."""
    base = tmp_path / "identity"
    _write(base / "users.json", {"_schema_version": 1, "users": {}})
    _write(base / "user_aliases.json", {"_schema_version": 1, "aliases": []})
    _write(base / "workspaces.json", {"_schema_version": 1, "workspaces": {}})
    _write(
        base / "memberships.json",
        {
            "_schema_version": 1,
            "workspace_memberships": [],
            "project_memberships": [],
        },
    )
    _write(base / "roles.json", {"_schema_version": 1, "roles": {}})
    _write(
        base / "role_permissions.json",
        {"_schema_version": 1, "role_permissions": {}},
    )
    _write(base / "resource_acl.json", {"_schema_version": 1, "acl": []})
    _write(
        base / "auth_migration_state.json",
        {
            "_schema_version": 1,
            "bootstrap_completed_at": None,
            "legacy_mapping_completed_at": None,
            "notes": [],
        },
    )
    (base / "audit_logs.jsonl").write_bytes(b"")
    return base


@pytest.fixture()
def bootstrapped_identity_dir(empty_identity_dir: Path) -> Path:
    """A dir that looks like it's been through `migrate_identity_bootstrap.py`."""
    ts = "2026-07-17T12:00:00+00:00"
    ws_id = "ws-default-00000000-0000-0000-0000-000000000000"
    proj_id = "proj-default-00000000-0000-0000-0000-000000000000"
    user_id = "user-sysadmin-00000000-0000-0000-0000-000000000000"
    _write(
        empty_identity_dir / "workspaces.json",
        {
            "_schema_version": 1,
            "workspaces": {
                ws_id: {
                    "id": ws_id,
                    "name": "默认工作区",
                    "description": "test",
                    "default_project_id": proj_id,
                    "legacy_owner_label": None,
                    "created_at": ts,
                    "updated_at": None,
                }
            },
        },
    )
    _write(
        empty_identity_dir / "users.json",
        {
            "_schema_version": 1,
            "users": {
                user_id: {
                    "id": user_id,
                    "username": "system_admin",
                    "password_hash": None,
                    "email": None,
                    "display_name": "系统管理员",
                    "status": "bootstrap_pending",
                    "created_at": ts,
                    "updated_at": None,
                    "legacy_owner_label": None,
                }
            },
        },
    )
    _write(
        empty_identity_dir / "memberships.json",
        {
            "_schema_version": 1,
            "workspace_memberships": [
                {
                    "workspace_id": ws_id,
                    "user_id": user_id,
                    "role": "workspace_admin",
                    "created_at": ts,
                }
            ],
            "project_memberships": [],
        },
    )
    _write(
        empty_identity_dir / "roles.json",
        {
            "_schema_version": 1,
            "roles": {
                "workspace_admin": {
                    "key": "workspace_admin",
                    "display_name": "工作区管理员",
                    "description": "Workspace 内最高权限",
                    "scope": "workspace",
                    "created_at": ts,
                }
            },
        },
    )
    _write(
        empty_identity_dir / "auth_migration_state.json",
        {
            "_schema_version": 1,
            "bootstrap_completed_at": ts,
            "legacy_mapping_completed_at": None,
            "notes": ["bootstrap done"],
        },
    )
    return empty_identity_dir


# ---------------------------------------------------------------------------
# JsonIdentityStore — 空 fixture
# ---------------------------------------------------------------------------


def test_get_user_returns_none_when_empty(empty_identity_dir: Path) -> None:
    store = JsonIdentityStore(empty_identity_dir)
    assert store.get_user("does-not-exist") is None


def test_find_alias_returns_none_when_empty(empty_identity_dir: Path) -> None:
    store = JsonIdentityStore(empty_identity_dir)
    assert store.find_alias("x_user_id", "any") is None


def test_list_user_aliases_empty(empty_identity_dir: Path) -> None:
    assert JsonIdentityStore(empty_identity_dir).list_user_aliases() == []


def test_list_workspaces_empty(empty_identity_dir: Path) -> None:
    assert JsonIdentityStore(empty_identity_dir).list_workspaces() == []


def test_list_memberships_empty(empty_identity_dir: Path) -> None:
    result = JsonIdentityStore(empty_identity_dir).list_memberships("nobody")
    assert result == {"workspace": [], "project": []}


def test_list_roles_empty(empty_identity_dir: Path) -> None:
    assert JsonIdentityStore(empty_identity_dir).list_roles() == []


def test_list_role_permissions_empty(empty_identity_dir: Path) -> None:
    assert JsonIdentityStore(empty_identity_dir).list_role_permissions() == {}


def test_get_resource_acl_empty(empty_identity_dir: Path) -> None:
    assert (
        JsonIdentityStore(empty_identity_dir).get_resource_acl(
            "canvas", "canvas-x"
        )
        == []
    )


def test_read_auth_migration_state_empty(empty_identity_dir: Path) -> None:
    state = JsonIdentityStore(empty_identity_dir).read_auth_migration_state()
    assert state["bootstrap_completed_at"] is None
    assert state["notes"] == []


# ---------------------------------------------------------------------------
# JsonIdentityStore — bootstrapped fixture
# ---------------------------------------------------------------------------


def test_get_user_after_bootstrap(bootstrapped_identity_dir: Path) -> None:
    store = JsonIdentityStore(bootstrapped_identity_dir)
    user = store.get_user("user-sysadmin-00000000-0000-0000-0000-000000000000")
    assert user is not None
    assert user["username"] == "system_admin"
    assert user["status"] == "bootstrap_pending"
    assert user["password_hash"] is None


def test_list_workspaces_after_bootstrap(bootstrapped_identity_dir: Path) -> None:
    store = JsonIdentityStore(bootstrapped_identity_dir)
    workspaces = store.list_workspaces()
    assert len(workspaces) == 1
    ws = workspaces[0]
    assert ws["id"] == "ws-default-00000000-0000-0000-0000-000000000000"
    assert ws["name"] == "默认工作区"


def test_list_memberships_after_bootstrap(bootstrapped_identity_dir: Path) -> None:
    store = JsonIdentityStore(bootstrapped_identity_dir)
    result = store.list_memberships(
        "user-sysadmin-00000000-0000-0000-0000-000000000000"
    )
    assert len(result["workspace"]) == 1
    assert result["workspace"][0]["role"] == "workspace_admin"
    assert result["project"] == []


def test_list_roles_after_bootstrap(bootstrapped_identity_dir: Path) -> None:
    roles = JsonIdentityStore(bootstrapped_identity_dir).list_roles()
    assert any(r["key"] == "workspace_admin" for r in roles)


def test_read_auth_migration_state_after_bootstrap(
    bootstrapped_identity_dir: Path,
) -> None:
    state = JsonIdentityStore(
        bootstrapped_identity_dir
    ).read_auth_migration_state()
    assert state["bootstrap_completed_at"] is not None


# ---------------------------------------------------------------------------
# write_auth_migration_state：唯一写入接口 + 幂等字节稳定
# ---------------------------------------------------------------------------


def test_write_auth_migration_state_persists(empty_identity_dir: Path) -> None:
    store = JsonIdentityStore(empty_identity_dir)
    new_state = {
        "_schema_version": 1,
        "bootstrap_completed_at": "2026-07-17T00:00:00+00:00",
        "legacy_mapping_completed_at": None,
        "notes": ["hello"],
    }
    store.write_auth_migration_state(new_state)
    reread = store.read_auth_migration_state()
    assert reread["bootstrap_completed_at"] == "2026-07-17T00:00:00+00:00"
    assert reread["notes"] == ["hello"]


def test_write_auth_migration_state_is_byte_stable(
    empty_identity_dir: Path,
) -> None:
    """两次写入相同内容产生**字节完全相同**的文件。"""
    store = JsonIdentityStore(empty_identity_dir)
    new_state = {
        "_schema_version": 1,
        "bootstrap_completed_at": "2026-07-17T00:00:00+00:00",
        "legacy_mapping_completed_at": None,
        "notes": ["hello"],
    }
    store.write_auth_migration_state(new_state)
    first = (empty_identity_dir / "auth_migration_state.json").read_bytes()
    store.write_auth_migration_state(new_state)
    second = (empty_identity_dir / "auth_migration_state.json").read_bytes()
    assert first == second


def test_write_auth_migration_state_rejects_bad_shape(
    empty_identity_dir: Path,
) -> None:
    store = JsonIdentityStore(empty_identity_dir)
    with pytest.raises(Exception):
        store.write_auth_migration_state(
            {
                "_schema_version": 1,
                "bootstrap_completed_at": None,
                "legacy_mapping_completed_at": None,
                "notes": [123],  # 反例：非字符串 note
            }
        )


# ---------------------------------------------------------------------------
# 缺文件时 FileNotFoundError
# ---------------------------------------------------------------------------


def test_missing_files_raise(tmp_path: Path) -> None:
    empty = tmp_path / "no-files"
    empty.mkdir()
    store = JsonIdentityStore(empty)
    with pytest.raises(FileNotFoundError):
        store.list_workspaces()


# ---------------------------------------------------------------------------
# SqliteIdentityStore — 占位空壳
# ---------------------------------------------------------------------------


def test_sqlite_store_init_raises_notimplemented() -> None:
    with pytest.raises(NotImplementedError):
        SqliteIdentityStore()


def test_sqlite_store_method_signatures_present() -> None:
    """确认 SqliteIdentityStore 定义了 IdentityStore 门面协议的所有方法名。"""
    expected = {
        "get_user",
        "find_alias",
        "list_user_aliases",
        "list_workspaces",
        "list_memberships",
        "list_roles",
        "list_role_permissions",
        "get_resource_acl",
        "read_auth_migration_state",
        "write_auth_migration_state",
    }
    for name in expected:
        assert callable(getattr(SqliteIdentityStore, name)), name
