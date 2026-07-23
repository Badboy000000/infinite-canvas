"""`app.modules.identity` — 数据 PR-13 identity 骨架（仅骨架 · 无认证 · 无过滤）。

本模块提供 3 个只读/幂等 upsert 函数供启动时调用：
- `ensure_default_workspace()` — 幂等确保 system workspace 存在
- `ensure_default_project(workspace_id)` — 幂等确保 default project 存在
- `resolve_or_create_user_alias(legacy_user_key)` — 幂等承接旧身份

**硬约束**：
- 不引入任何认证/授权/过滤逻辑
- 不修改任何写路径
- 不引入登录 middleware / SSO / MFA / Session
"""
from __future__ import annotations

from .store import (
    ensure_default_project,
    ensure_default_workspace,
    resolve_or_create_user_alias,
)

__all__ = [
    "ensure_default_workspace",
    "ensure_default_project",
    "resolve_or_create_user_alias",
]