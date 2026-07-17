"""`RequestContext` frozen dataclass — 唯一定义位置。

字段清单**严格按第二批协调纲要"字段冻结契约"章节冻结**，不许再加字段、
不许改 `Optional` 语义、不许改 `auth_mode` 三个字面量。

消费方（后续 PR）：
- PR-BE-02：`app/api/context.py` 内 `import` 本模块，落地 `contextvars` 存取
  与 `X-Request-Id` middleware。
- PR-BE-04：JSON Store facade 强化时读取 `request_id` / `x_user_id`
  用于日志与审计埋点。
- PR-BE-12：全局 `RequestValidationError` handler 用 `request_id` 回填错误响应。
- 权限 PR-1/PR-3/PR-4：认证入口 + PermissionService 消费 `auth_mode` 判定 principal。

冻结原因：本 dataclass 是 Wave 0 内的软合入 A（权限 PR-0），
后续 PR 都从这里 import；任何字段变更都会破坏下游 PR 的 rebase 假设。
如需扩字段：走 CB 候选流程，不许自行扩。

对齐：
- [[60 讨论记录/2026-07-17 第二批开工/2026-07-17 第二批 PR 开工协调纲要]]
  §"字段冻结契约"
- [[50 决策记录/决策 - 认证栈选型]] §"Principal 服务端传递（RequestContext）"
  （决策文档给出的更丰富字段清单是**长期目标**；PR-0 冻结的是**Wave 0 最小契约**，
  两者互不冲突：本 PR-0 契约是决策文档字段的一个子集 + `auth_mode` 三态。
  长期字段（如 `principal_kind` / `scopes` / `session_id` / `api_key_id`）
  由 PR-3 / PR-4 落地时另加。）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

AuthMode = Literal["anonymous_or_legacy", "authenticated_user", "legacy_alias"]


@dataclass(frozen=True)
class RequestContext:
    """请求上下文（frozen）。

    字段清单冻结（协调纲要 §"字段冻结契约"）：

    - `request_id`：`X-Request-Id` header 复用或 uuid4，恒非空字符串。
    - `legacy_user_key`：兼容 legacy 通道的用户键（来自 cookie `x_user_id`
      / query `user` / 对话目录名派生）；无则 `None`。
    - `x_user_id`：`X-User-Id` header 原值；无则 `None`。
    - `workspace_id`：当前作用域 workspace UUID；无则 `None`。
    - `project_id`：当前作用域 project UUID；无则 `None`。
    - `client_id`：WebSocket / 前端 `X-Client-Id`；无则 `None`。
    - `ip`：反向代理下取 `X-Forwarded-For` 首段，否则 socket peer；无则 `None`。
    - `user_agent`：`User-Agent` header 原值；无则 `None`。
    - `auth_mode`：`"anonymous_or_legacy"` / `"authenticated_user"` / `"legacy_alias"`
      三态字面量；不许扩展。
    """

    request_id: str
    legacy_user_key: Optional[str]
    x_user_id: Optional[str]
    workspace_id: Optional[str]
    project_id: Optional[str]
    client_id: Optional[str]
    ip: Optional[str]
    user_agent: Optional[str]
    auth_mode: AuthMode


__all__ = ["AuthMode", "RequestContext"]
