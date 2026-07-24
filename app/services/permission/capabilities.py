"""Capabilities API 骨架（权限 PR-6 · Wave 3-N.8 Batch 4）。

**定位**：只读 API 决策入口 · 前端根据用户 capabilities 显示 / 隐藏按钮 ·
后端根据 capabilities 决定路由行为。

**当前 PR skeleton 交付**：
- `build_capabilities(service, ctx)` 纯函数 · 输入 PermissionService + RequestContext
  → 返回 `CapabilitiesResponse`（含 `role` / `principal_kind` / `capabilities` 列表）。
- 未挂载路由（避免破坏冻结区）：`/api/me/capabilities` 由部署 PR 或后续路由
  挂载 PR 承接。本 PR 只提供纯函数消费入口。

**未来路由（Wave 3-N.9+ 承接）**：
```python
from fastapi import Depends
from app.api.context import request_context_dependency
from app.identity.request_context import RequestContext
from app.services.permission import DEFAULT_PERMISSION_SERVICE
from app.services.permission.capabilities import build_capabilities

@app.get("/api/me/capabilities")
def me_capabilities(ctx: RequestContext = Depends(request_context_dependency)):
    return build_capabilities(DEFAULT_PERMISSION_SERVICE, ctx)
```

**GM-16 pre-flight**：`build_capabilities` / `CapabilitiesResponse` 全部为新
公共符号 · `codegraph_explore` 确认 greenfield。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from app.identity.request_context import (
    PrincipalKind,
    RequestContext,
    derive_principal_kind,
)
from app.services.permission import PermissionService

__all__ = ["CapabilitiesResponse", "build_capabilities"]


@dataclass(frozen=True)
class CapabilitiesResponse:
    """`/api/me/capabilities` 响应契约（frozen · 稳定序列化）。

    字段：
    - `principal_kind`：`"user"` / `"session"` / `"anonymous"` 三态。
    - `role`：派生 role key（`viewer` / `member` / `workspace_admin` /
      `system_admin`）· 骨架期恒返回 `viewer` / `member` 之一。
    - `capabilities`：允许 action 列表 · **排序稳定**（sorted）· caller 可
      直接消费。空列表 = 无权限（匿名 + `viewer` 无权限 action 时）。
    - `workspace_id` / `project_id`：请求上下文的 workspace / project scope
      （未来 PR-6+ 承接 scope-specific role 派生时消费）。
    """

    principal_kind: PrincipalKind
    role: Optional[str]
    capabilities: List[str] = field(default_factory=list)
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None


def build_capabilities(
    service: PermissionService,
    ctx: RequestContext,
    *,
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> CapabilitiesResponse:
    """构造 capabilities 响应（纯函数 · 无副作用 · 无 IO）。

    - `principal_kind` 优先取 ctx 已派生值 · 未派生时由 `derive_principal_kind`
      派生（单一派生表约束 · GM-14 圆桌决议）。
    - `role` 通过 `service.resolve_role(ctx, workspace_id, project_id)` 派生。
    - `capabilities` 通过 `service.capabilities(role)` 派生 · sorted 稳定输出。
    - `workspace_id` / `project_id` 保留请求参数原值 · 不做校验（校验由未来
      PR 承接）。
    """
    principal_kind = ctx.principal_kind or derive_principal_kind(ctx)
    role = service.resolve_role(
        ctx, workspace_id=workspace_id, project_id=project_id
    )
    caps = sorted(service.capabilities(role))
    return CapabilitiesResponse(
        principal_kind=principal_kind,
        role=role,
        capabilities=caps,
        workspace_id=workspace_id,
        project_id=project_id,
    )
