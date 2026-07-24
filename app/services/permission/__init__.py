"""PermissionService 骨架（权限 PR-4 · Wave 3-N.8 Batch 4）。

**定位**：`role → action → bool` 静态矩阵消费的**只读决策服务**。当前
`role_permissions.json` 内 role_permissions map 为空（权限 PR-0 落下的空
matrix + PR-4 skeleton 首次填 4 内置角色 × 5 默认 action 白名单），
PermissionService 在其上提供：

1. 单点决策 API：`allow(role, action) -> bool` / `check(role, action)` 抛
   `PermissionDenied`。
2. 多点决策 API：`capabilities(role) -> frozenset[str]` 返回该角色的全部允许 action。
3. Membership 派生 role：`resolve_role(ctx, workspace_id, project_id)` 返回
   有效 role key（未来 PR-6 承接高精度 workspace-scoped / project-scoped 派生，
   本 PR skeleton 只做占位：认证用户 → member；匿名 → viewer）。

**默认关闭 flag（GM-22 defaults-off pattern 复用）**:
- `PERMISSION_SERVICE_ENFORCE=false`（默认）：所有 `check()` 调用直接 return
  等价旧行为；`allow()` 返回配置矩阵结果但**不**在路由挂载点强制拦截。
- 生产切换：显式设 `PERMISSION_SERVICE_ENFORCE=true` 由部署 PR 承接。

**5 默认 action 白名单**（与 [[30 治理方案/用户团队权限治理方案]] §权限点位对齐）：
- `canvas:read` / `canvas:write` / `canvas:delete`
- `provider:manage`
- `workspace:admin`

**4 内置角色的默认权限**（`system_admin` / `workspace_admin` / `member` / `viewer`）：
- `system_admin`：全部允许（5/5）
- `workspace_admin`：canvas:* + workspace:admin（4/5，不含 provider:manage）
- `member`：canvas:read + canvas:write（2/5）
- `viewer`：canvas:read（1/5）

**GM-16 pre-flight**：`PermissionService` / `PermissionDenied` / `allow` /
`check` / `capabilities` / `resolve_role` / `DEFAULT_PERMISSION_MATRIX`
全部为新公共符号，`codegraph_explore` 确认 greenfield。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, FrozenSet, Mapping, Optional

from app.identity.request_context import RequestContext, derive_principal_kind

__all__ = [
    "PermissionDenied",
    "PermissionService",
    "DEFAULT_PERMISSION_MATRIX",
    "DEFAULT_ACTIONS",
    "DEFAULT_ROLES",
    "is_enforce_enabled",
]

# ---------------------------------------------------------------------------
# 常量：默认权限矩阵 + action 白名单 + role 白名单
# ---------------------------------------------------------------------------

DEFAULT_ACTIONS: FrozenSet[str] = frozenset(
    {
        "canvas:read",
        "canvas:write",
        "canvas:delete",
        "provider:manage",
        "workspace:admin",
    }
)
"""5 个默认 action 白名单 · 与治理方案 §权限点位对齐 · 冻结增量走 PR-5+。"""

DEFAULT_ROLES: FrozenSet[str] = frozenset(
    {"system_admin", "workspace_admin", "member", "viewer"}
)
"""4 内置角色 key 白名单 · 与权限 PR-0 `BUILTIN_ROLES` 对齐。"""

DEFAULT_PERMISSION_MATRIX: Dict[str, FrozenSet[str]] = {
    "system_admin": frozenset(DEFAULT_ACTIONS),  # 全部允许（5/5）
    "workspace_admin": frozenset(
        {"canvas:read", "canvas:write", "canvas:delete", "workspace:admin"}
    ),  # 4/5
    "member": frozenset({"canvas:read", "canvas:write"}),  # 2/5
    "viewer": frozenset({"canvas:read"}),  # 1/5
}
"""role → 允许 action frozenset 静态矩阵。

PermissionService 用途：
- 消费方通过 `permission_service.allow(role, action)` 决策 · 复用不重新计算。
- 未来切 `role_permissions.json` DB 源时 · matrix 从 store 加载 · 接口签名不变。
"""


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PermissionDenied(Exception):
    """PermissionService 决策拒绝异常。

    - `role`：请求携带的 role key（可为 `None` · 表示未派生）。
    - `action`：请求的 action 权限点位。
    - `reason`：拒绝原因（`"unknown_role"` / `"unknown_action"` /
      `"role_action_not_allowed"` / `"principal_anonymous"` / 自定义 str）。

    frozen dataclass → hashable + 稳定 equality（便于测试断言）。
    """

    role: Optional[str]
    action: str
    reason: str = "role_action_not_allowed"

    def __str__(self) -> str:  # pragma: no cover - 简单委托
        return (
            f"permission_denied(role={self.role!r}, action={self.action!r}, "
            f"reason={self.reason!r})"
        )


# ---------------------------------------------------------------------------
# 环境 flag（默认关闭 · GM-22 pattern 复用）
# ---------------------------------------------------------------------------

_TRUTHY: FrozenSet[str] = frozenset({"1", "true", "yes", "on"})
_ENV_FLAG = "PERMISSION_SERVICE_ENFORCE"


def is_enforce_enabled() -> bool:
    """读取 `PERMISSION_SERVICE_ENFORCE` env flag（默认 false）。

    truthy 值集合（大小写不敏感）：`"1"` / `"true"` / `"yes"` / `"on"`。
    其他值（含未设置 / `"false"` / `"0"` / `"no"` / `"off"`）→ `False`。
    """
    raw = os.environ.get(_ENV_FLAG, "").strip().lower()
    return raw in _TRUTHY


# ---------------------------------------------------------------------------
# PermissionService（骨架）
# ---------------------------------------------------------------------------


class PermissionService:
    """静态矩阵消费的只读决策服务。

    - 无状态：本实例只持有一份 matrix + action 白名单 + role 白名单，
      构造后不可变。
    - 线程安全：所有查询都是纯函数（frozenset lookup），无锁。
    - 未来演进：切 `role_permissions.json` DB 源时，`matrix` 参数变为 store
      引用即可，本服务接口签名不变（`allow` / `check` / `capabilities`）。
    """

    def __init__(
        self,
        matrix: Optional[Mapping[str, FrozenSet[str]]] = None,
        *,
        allowed_actions: Optional[FrozenSet[str]] = None,
        allowed_roles: Optional[FrozenSet[str]] = None,
    ) -> None:
        # 允许注入自定义 matrix（测试 fixture / 未来切 store）；默认取常量。
        self._matrix: Dict[str, FrozenSet[str]] = dict(
            matrix if matrix is not None else DEFAULT_PERMISSION_MATRIX
        )
        self._allowed_actions: FrozenSet[str] = (
            allowed_actions if allowed_actions is not None else DEFAULT_ACTIONS
        )
        self._allowed_roles: FrozenSet[str] = (
            allowed_roles if allowed_roles is not None else DEFAULT_ROLES
        )

    # ---- 单点决策 ---------------------------------------------------------

    def allow(self, role: Optional[str], action: str) -> bool:
        """判定 `role` 是否被授权执行 `action`（不抛异常）。

        - `role is None` → 恒 `False`（未派生 role 视为无权限）。
        - `role not in allowed_roles` → 恒 `False`（未知 role）。
        - `action not in allowed_actions` → 恒 `False`（未知 action · 严禁
          wildcard 通过）。
        - 其他 → `action in matrix.get(role, frozenset())`。
        """
        if role is None:
            return False
        if role not in self._allowed_roles:
            return False
        if action not in self._allowed_actions:
            return False
        return action in self._matrix.get(role, frozenset())

    def check(self, role: Optional[str], action: str) -> None:
        """`allow` 的抛异常版本 · `False` → `raise PermissionDenied(...)`。

        `PERMISSION_SERVICE_ENFORCE=false`（默认）时**仍**抛异常 · 调用方
        需要区分 skeleton 期 flag 语义应显式先查 `is_enforce_enabled()` 或
        用 `allow()`。本方法用于测试骨架契约锁定 · 未来路由挂载点消费。
        """
        if role is None:
            raise PermissionDenied(role, action, "principal_anonymous")
        if role not in self._allowed_roles:
            raise PermissionDenied(role, action, "unknown_role")
        if action not in self._allowed_actions:
            raise PermissionDenied(role, action, "unknown_action")
        if action not in self._matrix.get(role, frozenset()):
            raise PermissionDenied(role, action, "role_action_not_allowed")

    # ---- 多点决策 ---------------------------------------------------------

    def capabilities(self, role: Optional[str]) -> FrozenSet[str]:
        """返回 `role` 被允许的全部 action 集合（frozenset · 只读）。

        - `role is None` → 空 frozenset（未派生 role）。
        - `role not in allowed_roles` → 空 frozenset（未知 role）。
        - 其他 → `matrix[role]`（frozenset · 已冻结 · caller 不能修改）。
        """
        if role is None or role not in self._allowed_roles:
            return frozenset()
        return self._matrix.get(role, frozenset())

    # ---- Membership 派生 role（skeleton · 占位） --------------------------

    def resolve_role(
        self,
        ctx: RequestContext,
        *,
        workspace_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        """从 `RequestContext` 派生有效 role key（骨架期占位实现）。

        **权限 PR-4 skeleton 定义**：
        - `principal_kind` 未派生（`None`）→ 先调 `derive_principal_kind(ctx)` 派生。
        - `derive_principal_kind == "anonymous"` → `"viewer"`（匿名读兜底）。
        - `derive_principal_kind == "session"` → `"member"`（legacy 会话默认 member）。
        - `derive_principal_kind == "user"` → `"member"`（认证用户默认 member ·
          未来 PR-6 承接 workspace-scoped `workspace_admin` / `system_admin`
          派生）。

        **未来演进**（PR-6 承接 · 本 PR skeleton 不实现）：
        - workspace_id 传入时查 `memberships.workspace_memberships` 找该用户
          在该 workspace 的 role。
        - project_id 传入时查 `memberships.project_memberships` 找该用户在
          该 project 的 role · 优先级高于 workspace-level。
        - `system_admin` 从 `roles.system_admin_users` 派生（PR-6 落地）。

        `workspace_id` / `project_id` 参数**目前不消费**但**保留位置** · 未来 PR
        承接时无需改签名。
        """
        # `workspace_id` / `project_id` 保留位置 · 未来消费 · 抑制 lint
        _ = workspace_id
        _ = project_id
        pk = ctx.principal_kind
        if pk is None:
            pk = derive_principal_kind(ctx)
        if pk == "anonymous":
            return "viewer"
        # user / session 都默认 member（未来 PR-6 承接 workspace-scoped 提升）
        return "member"

    # ---- 内部只读属性（测试 / 后续 PR-5 消费） -------------------------

    @property
    def allowed_actions(self) -> FrozenSet[str]:
        return self._allowed_actions

    @property
    def allowed_roles(self) -> FrozenSet[str]:
        return self._allowed_roles


# 全局默认实例（消费方可 import · 也可注入自定义 matrix 实例做测试）
DEFAULT_PERMISSION_SERVICE = PermissionService()
