"""Identity JSON schema — TypedDict 定义与最小校验（权限 PR-0）。

8 类 identity JSON 文件（在 `data/identity/`）：

| 文件 | 顶层 shape |
|---|---|
| `users.json` | `{"_schema_version": 1, "users": {<user_id>: UserRecord}}` |
| `user_aliases.json` | `{"_schema_version": 1, "aliases": [UserAliasRecord]}` |
| `workspaces.json` | `{"_schema_version": 1, "workspaces": {<ws_id>: WorkspaceRecord}}` |
| `memberships.json` | `{"_schema_version": 1, "workspace_memberships": [WorkspaceMembership], "project_memberships": [ProjectMembership]}` |
| `roles.json` | `{"_schema_version": 1, "roles": {<role_key>: RoleRecord}}` |
| `role_permissions.json` | `{"_schema_version": 1, "role_permissions": {<role_key>: {<action>: bool}}}` |
| `resource_acl.json` | `{"_schema_version": 1, "acl": [ResourceAclEntry]}` |
| `auth_migration_state.json` | `{"_schema_version": 1, "bootstrap_completed_at": None|str, "legacy_mapping_completed_at": None|str, "notes": [str]}` |

设计约束：
- 全表 UUID 字符串主键（[[50 决策记录/决策 - 主键类型]]，SQLite 治理期
  `TEXT(36)` / PostgreSQL 稳定期 `uuid` 原生）。
- `legacy_owner_label` / `legacy_user_key` 承接旧身份线索
  （UserAlias.legacy_user_key 独立列，不复用主键）。
- 时间戳统一 ISO 8601 UTC 字符串（`YYYY-MM-DDTHH:MM:SS+00:00` / `...Z`）。
- 本 PR **不落任何权限矩阵内容**（`role_permissions.json` 只写空 map）；
  五档内置角色（system_admin / workspace_admin / project_admin / editor / viewer）
  由 bootstrap 脚本落 `roles.json` 骨架，`role_permissions` 的填充由权限 PR-4 承接。

`SCHEMA_VERSION` 常量：整数 `1`（本 PR 建立；后续 breaking 变更递增，并需在
`app/identity/schema.py` 内加迁移逻辑）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

SCHEMA_VERSION: int = 1

# 用户状态：`active`（正常）/ `bootstrap_pending`（bootstrap 空位，无密码）/
# `disabled`（管理员禁用）。PR-3 认证入口才会写 `active`。
UserStatus = Literal["active", "bootstrap_pending", "disabled"]

# UserAlias 类型枚举；PR-2 legacy 承接时会填数据。
AliasKind = Literal["x_user_id", "cookie_user", "ip_derived", "conversation_dir"]

# ACL 主体类型；本 PR 只落表结构，PR-4 消费。
AclSubjectKind = Literal["user", "workspace_membership", "project_membership"]


# ---------------------------------------------------------------------------
# TypedDict 记录形状
# ---------------------------------------------------------------------------


class UserRecord(TypedDict, total=False):
    """`users.json` 内每条记录。

    必填：`id / username / created_at / status`；
    可选：`password_hash / email / display_name / updated_at / legacy_owner_label`。
    """

    id: str
    username: str
    password_hash: Optional[str]
    email: Optional[str]
    display_name: Optional[str]
    status: UserStatus
    created_at: str
    updated_at: Optional[str]
    legacy_owner_label: Optional[str]


class UserAliasRecord(TypedDict, total=False):
    id: str
    user_id: Optional[str]  # None 表示尚未 claim 到具体 user
    kind: AliasKind
    legacy_user_key: str  # 原字符串（`x_user_id` 值 / 目录名 / 派生 hash）
    workspace_id: Optional[str]
    created_at: str


class WorkspaceRecord(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]
    default_project_id: Optional[str]
    legacy_owner_label: Optional[str]
    created_at: str
    updated_at: Optional[str]


class WorkspaceMembership(TypedDict, total=False):
    workspace_id: str
    user_id: str
    role: str  # 五档角色 key 之一
    created_at: str


class ProjectMembership(TypedDict, total=False):
    project_id: str
    workspace_id: str
    user_id: str
    role: str
    created_at: str


class RoleRecord(TypedDict, total=False):
    key: str
    display_name: str
    description: str
    scope: Literal["system", "workspace", "project"]
    created_at: str


class ResourceAclEntry(TypedDict, total=False):
    id: str
    resource_type: str  # `canvas` / `project` / `provider` / `asset` / `workspace` / `file`
    resource_id: str
    subject_kind: AclSubjectKind
    subject_id: str
    role: str
    created_at: str


class AuthMigrationState(TypedDict, total=False):
    _schema_version: int
    bootstrap_completed_at: Optional[str]
    legacy_mapping_completed_at: Optional[str]
    notes: List[str]


# 顶层文件 shape TypedDicts —— 仅用于类型注解与文档，运行时校验走
# `validate_*` 函数（避免 pydantic 依赖）。


class UsersFile(TypedDict):
    _schema_version: int
    users: Dict[str, UserRecord]


class UserAliasesFile(TypedDict):
    _schema_version: int
    aliases: List[UserAliasRecord]


class WorkspacesFile(TypedDict):
    _schema_version: int
    workspaces: Dict[str, WorkspaceRecord]


class MembershipsFile(TypedDict):
    _schema_version: int
    workspace_memberships: List[WorkspaceMembership]
    project_memberships: List[ProjectMembership]


class RolesFile(TypedDict):
    _schema_version: int
    roles: Dict[str, RoleRecord]


class RolePermissionsFile(TypedDict):
    _schema_version: int
    role_permissions: Dict[str, Dict[str, bool]]


class ResourceAclFile(TypedDict):
    _schema_version: int
    acl: List[ResourceAclEntry]


class AuthMigrationStateFile(TypedDict):
    _schema_version: int
    bootstrap_completed_at: Optional[str]
    legacy_mapping_completed_at: Optional[str]
    notes: List[str]


# ---------------------------------------------------------------------------
# 内置五档角色（scope + 中文说明）
#
# 本 PR 只落 `roles.json` 内的元数据；权限动作矩阵由 PR-4 填 `role_permissions.json`。
# ---------------------------------------------------------------------------

BUILTIN_ROLES: Dict[str, Dict[str, str]] = {
    "system_admin": {
        "display_name": "系统管理员",
        "description": "部署级最高权限；可跨 Workspace 管理系统配置、Provider、"
        "存储设置与用户账号。首任由 bootstrap 脚本创建为空位。",
        "scope": "system",
    },
    "workspace_admin": {
        "display_name": "工作区管理员",
        "description": "Workspace 内最高权限；可管理成员、项目、Provider 凭据、"
        "画布/素材/文件删除、共享文件夹与审计查看。",
        "scope": "workspace",
    },
    "project_admin": {
        "display_name": "项目管理员",
        "description": "Project 内权限；可管理项目内画布/素材/任务，邀请协作者，"
        "无法管理 Provider 凭据或 Workspace 成员。",
        "scope": "project",
    },
    "editor": {
        "display_name": "编辑者",
        "description": "可读写画布、素材、提交生成任务、下载文件；不可删除资源，"
        "不可管理成员与 Provider。",
        "scope": "project",
    },
    "viewer": {
        "display_name": "查看者",
        "description": "只读；可查看画布、素材、任务历史、下载已授权文件；"
        "不可编辑、不可提交任务、不可修改任何配置。",
        "scope": "project",
    },
}


# ---------------------------------------------------------------------------
# 最小校验函数（不引入 pydantic）
# ---------------------------------------------------------------------------


class SchemaValidationError(ValueError):
    """Identity JSON 文件不符合本 PR 冻结的 schema。"""


def _require_dict(name: str, payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise SchemaValidationError(
            f"{name} 顶层必须是 JSON 对象，实际得到 {type(payload).__name__}"
        )
    return payload


def _require_schema_version(name: str, payload: Dict[str, Any]) -> None:
    if payload.get("_schema_version") != SCHEMA_VERSION:
        raise SchemaValidationError(
            f"{name}._schema_version 必须是 {SCHEMA_VERSION}，"
            f"实际得到 {payload.get('_schema_version')!r}"
        )


def _require_field(name: str, entry: Dict[str, Any], field: str, kind: type) -> None:
    if field not in entry:
        raise SchemaValidationError(f"{name} 缺失必填字段 `{field}`")
    if not isinstance(entry[field], kind):
        raise SchemaValidationError(
            f"{name}.{field} 类型必须是 {kind.__name__}，"
            f"实际得到 {type(entry[field]).__name__}"
        )


def validate_users_file(payload: Any) -> UsersFile:
    data = _require_dict("users.json", payload)
    _require_schema_version("users.json", data)
    users = data.get("users")
    if not isinstance(users, dict):
        raise SchemaValidationError("users.json.users 必须是 object")
    for uid, record in users.items():
        if not isinstance(record, dict):
            raise SchemaValidationError(
                f"users.json.users[{uid!r}] 必须是 object"
            )
        _require_field(f"users[{uid!r}]", record, "id", str)
        _require_field(f"users[{uid!r}]", record, "username", str)
        _require_field(f"users[{uid!r}]", record, "status", str)
        _require_field(f"users[{uid!r}]", record, "created_at", str)
        if record["status"] not in ("active", "bootstrap_pending", "disabled"):
            raise SchemaValidationError(
                f"users[{uid!r}].status 必须是 active/bootstrap_pending/disabled，"
                f"实际得到 {record['status']!r}"
            )
        if record["id"] != uid:
            raise SchemaValidationError(
                f"users.json.users[{uid!r}].id 与 map key 不一致：{record['id']!r}"
            )
    return data  # type: ignore[return-value]


def validate_user_aliases_file(payload: Any) -> UserAliasesFile:
    data = _require_dict("user_aliases.json", payload)
    _require_schema_version("user_aliases.json", data)
    aliases = data.get("aliases")
    if not isinstance(aliases, list):
        raise SchemaValidationError("user_aliases.json.aliases 必须是 list")
    for i, entry in enumerate(aliases):
        if not isinstance(entry, dict):
            raise SchemaValidationError(
                f"user_aliases.json.aliases[{i}] 必须是 object"
            )
        _require_field(f"aliases[{i}]", entry, "id", str)
        _require_field(f"aliases[{i}]", entry, "kind", str)
        _require_field(f"aliases[{i}]", entry, "legacy_user_key", str)
        _require_field(f"aliases[{i}]", entry, "created_at", str)
        if entry["kind"] not in (
            "x_user_id",
            "cookie_user",
            "ip_derived",
            "conversation_dir",
        ):
            raise SchemaValidationError(
                f"aliases[{i}].kind 必须是 x_user_id/cookie_user/ip_derived/"
                f"conversation_dir，实际得到 {entry['kind']!r}"
            )
    return data  # type: ignore[return-value]


def validate_workspaces_file(payload: Any) -> WorkspacesFile:
    data = _require_dict("workspaces.json", payload)
    _require_schema_version("workspaces.json", data)
    workspaces = data.get("workspaces")
    if not isinstance(workspaces, dict):
        raise SchemaValidationError("workspaces.json.workspaces 必须是 object")
    for wid, record in workspaces.items():
        if not isinstance(record, dict):
            raise SchemaValidationError(
                f"workspaces.json.workspaces[{wid!r}] 必须是 object"
            )
        _require_field(f"workspaces[{wid!r}]", record, "id", str)
        _require_field(f"workspaces[{wid!r}]", record, "name", str)
        _require_field(f"workspaces[{wid!r}]", record, "created_at", str)
        if record["id"] != wid:
            raise SchemaValidationError(
                f"workspaces[{wid!r}].id 与 map key 不一致：{record['id']!r}"
            )
    return data  # type: ignore[return-value]


def validate_memberships_file(payload: Any) -> MembershipsFile:
    data = _require_dict("memberships.json", payload)
    _require_schema_version("memberships.json", data)
    ws_memberships = data.get("workspace_memberships")
    proj_memberships = data.get("project_memberships")
    if not isinstance(ws_memberships, list):
        raise SchemaValidationError(
            "memberships.json.workspace_memberships 必须是 list"
        )
    if not isinstance(proj_memberships, list):
        raise SchemaValidationError(
            "memberships.json.project_memberships 必须是 list"
        )
    for i, entry in enumerate(ws_memberships):
        if not isinstance(entry, dict):
            raise SchemaValidationError(
                f"workspace_memberships[{i}] 必须是 object"
            )
        _require_field(f"workspace_memberships[{i}]", entry, "workspace_id", str)
        _require_field(f"workspace_memberships[{i}]", entry, "user_id", str)
        _require_field(f"workspace_memberships[{i}]", entry, "role", str)
        _require_field(f"workspace_memberships[{i}]", entry, "created_at", str)
    for i, entry in enumerate(proj_memberships):
        if not isinstance(entry, dict):
            raise SchemaValidationError(
                f"project_memberships[{i}] 必须是 object"
            )
        _require_field(f"project_memberships[{i}]", entry, "project_id", str)
        _require_field(f"project_memberships[{i}]", entry, "workspace_id", str)
        _require_field(f"project_memberships[{i}]", entry, "user_id", str)
        _require_field(f"project_memberships[{i}]", entry, "role", str)
        _require_field(f"project_memberships[{i}]", entry, "created_at", str)
    return data  # type: ignore[return-value]


def validate_roles_file(payload: Any) -> RolesFile:
    data = _require_dict("roles.json", payload)
    _require_schema_version("roles.json", data)
    roles = data.get("roles")
    if not isinstance(roles, dict):
        raise SchemaValidationError("roles.json.roles 必须是 object")
    for key, record in roles.items():
        if not isinstance(record, dict):
            raise SchemaValidationError(f"roles.json.roles[{key!r}] 必须是 object")
        _require_field(f"roles[{key!r}]", record, "key", str)
        _require_field(f"roles[{key!r}]", record, "display_name", str)
        _require_field(f"roles[{key!r}]", record, "description", str)
        _require_field(f"roles[{key!r}]", record, "scope", str)
        _require_field(f"roles[{key!r}]", record, "created_at", str)
        if record["scope"] not in ("system", "workspace", "project"):
            raise SchemaValidationError(
                f"roles[{key!r}].scope 必须是 system/workspace/project，"
                f"实际得到 {record['scope']!r}"
            )
    return data  # type: ignore[return-value]


def validate_role_permissions_file(payload: Any) -> RolePermissionsFile:
    data = _require_dict("role_permissions.json", payload)
    _require_schema_version("role_permissions.json", data)
    matrix = data.get("role_permissions")
    if not isinstance(matrix, dict):
        raise SchemaValidationError(
            "role_permissions.json.role_permissions 必须是 object（本 PR 内为空 map，"
            "由权限 PR-4 填内容）"
        )
    for role, actions in matrix.items():
        if not isinstance(actions, dict):
            raise SchemaValidationError(
                f"role_permissions[{role!r}] 必须是 object"
            )
        for action, allow in actions.items():
            if not isinstance(allow, bool):
                raise SchemaValidationError(
                    f"role_permissions[{role!r}][{action!r}] 必须是 bool，"
                    f"实际得到 {type(allow).__name__}"
                )
    return data  # type: ignore[return-value]


def validate_resource_acl_file(payload: Any) -> ResourceAclFile:
    data = _require_dict("resource_acl.json", payload)
    _require_schema_version("resource_acl.json", data)
    acl = data.get("acl")
    if not isinstance(acl, list):
        raise SchemaValidationError("resource_acl.json.acl 必须是 list")
    for i, entry in enumerate(acl):
        if not isinstance(entry, dict):
            raise SchemaValidationError(f"acl[{i}] 必须是 object")
        _require_field(f"acl[{i}]", entry, "id", str)
        _require_field(f"acl[{i}]", entry, "resource_type", str)
        _require_field(f"acl[{i}]", entry, "resource_id", str)
        _require_field(f"acl[{i}]", entry, "subject_kind", str)
        _require_field(f"acl[{i}]", entry, "subject_id", str)
        _require_field(f"acl[{i}]", entry, "role", str)
        _require_field(f"acl[{i}]", entry, "created_at", str)
        if entry["subject_kind"] not in (
            "user",
            "workspace_membership",
            "project_membership",
        ):
            raise SchemaValidationError(
                f"acl[{i}].subject_kind 必须是 user/workspace_membership/"
                f"project_membership，实际得到 {entry['subject_kind']!r}"
            )
    return data  # type: ignore[return-value]


def validate_auth_migration_state_file(payload: Any) -> AuthMigrationStateFile:
    data = _require_dict("auth_migration_state.json", payload)
    _require_schema_version("auth_migration_state.json", data)
    bootstrap = data.get("bootstrap_completed_at")
    legacy = data.get("legacy_mapping_completed_at")
    notes = data.get("notes")
    if bootstrap is not None and not isinstance(bootstrap, str):
        raise SchemaValidationError(
            "auth_migration_state.bootstrap_completed_at 必须是 str 或 null"
        )
    if legacy is not None and not isinstance(legacy, str):
        raise SchemaValidationError(
            "auth_migration_state.legacy_mapping_completed_at 必须是 str 或 null"
        )
    if not isinstance(notes, list):
        raise SchemaValidationError("auth_migration_state.notes 必须是 list")
    for i, note in enumerate(notes):
        if not isinstance(note, str):
            raise SchemaValidationError(
                f"auth_migration_state.notes[{i}] 必须是 str"
            )
    return data  # type: ignore[return-value]


__all__ = [
    "SCHEMA_VERSION",
    "UserStatus",
    "AliasKind",
    "AclSubjectKind",
    "UserRecord",
    "UserAliasRecord",
    "WorkspaceRecord",
    "WorkspaceMembership",
    "ProjectMembership",
    "RoleRecord",
    "ResourceAclEntry",
    "AuthMigrationState",
    "UsersFile",
    "UserAliasesFile",
    "WorkspacesFile",
    "MembershipsFile",
    "RolesFile",
    "RolePermissionsFile",
    "ResourceAclFile",
    "AuthMigrationStateFile",
    "BUILTIN_ROLES",
    "SchemaValidationError",
    "validate_users_file",
    "validate_user_aliases_file",
    "validate_workspaces_file",
    "validate_memberships_file",
    "validate_roles_file",
    "validate_role_permissions_file",
    "validate_resource_acl_file",
    "validate_auth_migration_state_file",
]
