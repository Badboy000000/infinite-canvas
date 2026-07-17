"""`IdentityStore` 门面（权限 PR-0）。

对外暴露：
- 只读接口 9 个：`get_user / find_alias / list_workspaces / list_memberships /
  list_roles / list_role_permissions / get_resource_acl /
  read_auth_migration_state`（+ `list_user_aliases` 辅助）。
- 写入接口 1 个：`write_auth_migration_state`（供 bootstrap 使用；其它写路径
  由后续 PR 承接：PR-2 legacy_mapper、PR-3 认证入口、PR-4 PermissionService 等）。

实现：
- `JsonIdentityStore(base_dir: Path)`：读 `data/identity/*.json` 8 个文件。
- `SqliteIdentityStore()`：占位 stub；PR-1（数据模型治理 SQLAlchemy 脚手架）
  合入后再接。

签名冻结原则：只允许**新增**方法，禁止删除或改现有签名（下游 PR-BE-02 /
权限 PR-2 / PR-3 / PR-4 都会依赖这些方法名）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

from .schema import (
    AliasKind,
    AuthMigrationStateFile,
    MembershipsFile,
    ResourceAclEntry,
    ResourceAclFile,
    RolePermissionsFile,
    RoleRecord,
    RolesFile,
    UserAliasRecord,
    UserAliasesFile,
    UserRecord,
    UsersFile,
    WorkspaceRecord,
    WorkspacesFile,
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
# 门面协议
# ---------------------------------------------------------------------------


class IdentityStore(Protocol):
    """`IdentityStore` 门面协议。

    9 个只读接口 + 1 个写入接口（`write_auth_migration_state`）。

    - `get_user(user_id)` — 按 id 查用户；不存在返回 `None`。
    - `find_alias(kind, key)` — 按 kind + legacy_user_key 唯一定位 UserAlias。
    - `list_user_aliases()` — 列全部 UserAlias（PR-2 消费）。
    - `list_workspaces()` — 列全部 Workspace（顺序按 `created_at` 升序）。
    - `list_memberships(user_id)` — 返回 `{"workspace": [...], "project": [...]}`。
    - `list_roles()` — 列全部内置角色。
    - `list_role_permissions()` — 返回完整 role → action → bool 矩阵
      （本 PR 为空 dict；PR-4 承接）。
    - `get_resource_acl(resource_type, resource_id)` — 返回该资源的 ACL 条目列表。
    - `read_auth_migration_state()` — 返回 `auth_migration_state.json` 完整内容。
    - `write_auth_migration_state(state)` — **唯一**写入方法；供 bootstrap 使用。
    """

    def get_user(self, user_id: str) -> Optional[UserRecord]: ...
    def find_alias(
        self, kind: AliasKind, key: str
    ) -> Optional[UserAliasRecord]: ...
    def list_user_aliases(self) -> List[UserAliasRecord]: ...
    def list_workspaces(self) -> List[WorkspaceRecord]: ...
    def list_memberships(self, user_id: str) -> Dict[str, List[Dict[str, Any]]]: ...
    def list_roles(self) -> List[RoleRecord]: ...
    def list_role_permissions(self) -> Dict[str, Dict[str, bool]]: ...
    def get_resource_acl(
        self, resource_type: str, resource_id: str
    ) -> List[ResourceAclEntry]: ...
    def read_auth_migration_state(self) -> AuthMigrationStateFile: ...
    def write_auth_migration_state(
        self, state: AuthMigrationStateFile
    ) -> None: ...


# ---------------------------------------------------------------------------
# JSON 实现
# ---------------------------------------------------------------------------


class JsonIdentityStore:
    """基于 `data/identity/*.json` 的 IdentityStore 实现。

    - 每次调用都从磁盘重读（无内存缓存）：本 PR 无高并发场景，读延迟不敏感；
      避免与 bootstrap 脚本的写入产生缓存一致性问题。
    - 校验：读入后过 schema.validate_* 校验；不合法直接抛 SchemaValidationError。
    - 幂等：写入 `write_auth_migration_state` 使用"整体覆盖 + 稳定序列化"，
      同内容多次写入产生**字节完全相同**的文件（bootstrap 幂等的必要条件）。
    """

    USERS_FILE = "users.json"
    USER_ALIASES_FILE = "user_aliases.json"
    WORKSPACES_FILE = "workspaces.json"
    MEMBERSHIPS_FILE = "memberships.json"
    ROLES_FILE = "roles.json"
    ROLE_PERMISSIONS_FILE = "role_permissions.json"
    RESOURCE_ACL_FILE = "resource_acl.json"
    AUTH_MIGRATION_STATE_FILE = "auth_migration_state.json"
    AUDIT_LOGS_FILE = "audit_logs.jsonl"

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)

    # ---- 内部读写 helpers -------------------------------------------------

    def _read_json(self, name: str) -> Any:
        p = self.base_dir / name
        if not p.is_file():
            raise FileNotFoundError(
                f"identity JSON 文件缺失：{p}（请先跑 tools/migrate_identity_bootstrap.py）"
            )
        with p.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write_json(self, name: str, payload: Any) -> None:
        p = self.base_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        # 稳定序列化：`sort_keys=True` + `ensure_ascii=False` + 固定缩进
        # + 尾随换行；两次写同内容 → 字节完全相同（幂等）。
        text = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        # 原子替换：先写临时文件再 rename，避免半写状态
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.write("\n")
        tmp.replace(p)

    def _load_users(self) -> UsersFile:
        return validate_users_file(self._read_json(self.USERS_FILE))

    def _load_aliases(self) -> UserAliasesFile:
        return validate_user_aliases_file(self._read_json(self.USER_ALIASES_FILE))

    def _load_workspaces(self) -> WorkspacesFile:
        return validate_workspaces_file(self._read_json(self.WORKSPACES_FILE))

    def _load_memberships(self) -> MembershipsFile:
        return validate_memberships_file(self._read_json(self.MEMBERSHIPS_FILE))

    def _load_roles(self) -> RolesFile:
        return validate_roles_file(self._read_json(self.ROLES_FILE))

    def _load_role_permissions(self) -> RolePermissionsFile:
        return validate_role_permissions_file(
            self._read_json(self.ROLE_PERMISSIONS_FILE)
        )

    def _load_resource_acl(self) -> ResourceAclFile:
        return validate_resource_acl_file(self._read_json(self.RESOURCE_ACL_FILE))

    # ---- 只读接口 ---------------------------------------------------------

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        users = self._load_users()["users"]
        return users.get(user_id)

    def find_alias(self, kind: AliasKind, key: str) -> Optional[UserAliasRecord]:
        for entry in self._load_aliases()["aliases"]:
            if entry.get("kind") == kind and entry.get("legacy_user_key") == key:
                return entry
        return None

    def list_user_aliases(self) -> List[UserAliasRecord]:
        return list(self._load_aliases()["aliases"])

    def list_workspaces(self) -> List[WorkspaceRecord]:
        workspaces = self._load_workspaces()["workspaces"]
        # 按 created_at 升序稳定输出
        return sorted(
            workspaces.values(),
            key=lambda w: (w.get("created_at", ""), w.get("id", "")),
        )

    def list_memberships(
        self, user_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        data = self._load_memberships()
        return {
            "workspace": [
                m for m in data["workspace_memberships"] if m.get("user_id") == user_id
            ],
            "project": [
                m for m in data["project_memberships"] if m.get("user_id") == user_id
            ],
        }

    def list_roles(self) -> List[RoleRecord]:
        roles = self._load_roles()["roles"]
        return sorted(roles.values(), key=lambda r: r.get("key", ""))

    def list_role_permissions(self) -> Dict[str, Dict[str, bool]]:
        # 完整矩阵；本 PR 为空 dict，PR-4 填充
        return dict(self._load_role_permissions()["role_permissions"])

    def get_resource_acl(
        self, resource_type: str, resource_id: str
    ) -> List[ResourceAclEntry]:
        return [
            entry
            for entry in self._load_resource_acl()["acl"]
            if entry.get("resource_type") == resource_type
            and entry.get("resource_id") == resource_id
        ]

    def read_auth_migration_state(self) -> AuthMigrationStateFile:
        return validate_auth_migration_state_file(
            self._read_json(self.AUTH_MIGRATION_STATE_FILE)
        )

    # ---- 唯一写入接口 -----------------------------------------------------

    def write_auth_migration_state(
        self, state: AuthMigrationStateFile
    ) -> None:
        """整体覆盖 `auth_migration_state.json`。

        校验后原子写入，稳定序列化保证多次相同内容写入产生字节相同的文件。
        供 `tools/migrate_identity_bootstrap.py` 使用；其它调用点须走后续 PR。
        """
        validate_auth_migration_state_file(state)
        self._write_json(self.AUTH_MIGRATION_STATE_FILE, state)


# ---------------------------------------------------------------------------
# SQLite 空壳（PR-1 之后接入）
# ---------------------------------------------------------------------------


class SqliteIdentityStore:
    """`IdentityStore` 的 SQLite 实现占位。

    本 PR **不落任何 SQL**。所有方法直接 `raise NotImplementedError`，
    避免下游误用；由数据模型治理 PR-1（SQLAlchemy 2.x Core + Alembic 脚手架）
    合入后再接入，届时 schema 与 `app/db/tables/identity.py` 表结构对齐
    （identity 全表 UUID + `legacy_owner_label` / `legacy_user_key`
    见 [[决策 - 主键类型]]）。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError(
            "SqliteIdentityStore 由数据模型治理 PR-1 之后的 identity PR 承接；"
            "本 PR（权限 PR-0）只提供 JSON 实现。"
        )

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        raise NotImplementedError

    def find_alias(self, kind: AliasKind, key: str) -> Optional[UserAliasRecord]:
        raise NotImplementedError

    def list_user_aliases(self) -> List[UserAliasRecord]:
        raise NotImplementedError

    def list_workspaces(self) -> List[WorkspaceRecord]:
        raise NotImplementedError

    def list_memberships(
        self, user_id: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        raise NotImplementedError

    def list_roles(self) -> List[RoleRecord]:
        raise NotImplementedError

    def list_role_permissions(self) -> Dict[str, Dict[str, bool]]:
        raise NotImplementedError

    def get_resource_acl(
        self, resource_type: str, resource_id: str
    ) -> List[ResourceAclEntry]:
        raise NotImplementedError

    def read_auth_migration_state(self) -> AuthMigrationStateFile:
        raise NotImplementedError

    def write_auth_migration_state(
        self, state: AuthMigrationStateFile
    ) -> None:
        raise NotImplementedError


__all__ = ["IdentityStore", "JsonIdentityStore", "SqliteIdentityStore"]
