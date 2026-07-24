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
from typing import Literal, Optional, Tuple

AuthMode = Literal["anonymous_or_legacy", "authenticated_user", "legacy_alias"]

# 权限 PR-3 扩字段：`principal_kind` 派生自 `auth_mode + x_user_id + legacy_user_key`
# 三元组，与 [[70 开发过程跟踪/PR 状态总账/PR - 用户团队权限#权限 PR-1]] 内
# `_derive_principal_kind()` 派生表逐值对齐（user / session / anonymous 三态）。
PrincipalKind = Literal["user", "session", "anonymous"]


@dataclass(frozen=True)
class RequestContext:
    """请求上下文（frozen）。

    字段清单冻结（协调纲要 §"字段冻结契约" · Wave 0 最小契约）+
    Wave 3-N.8 Batch 4 权限 PR-3 扩 4 长期字段（decision - 认证栈选型 §
    "Principal 服务端传递（RequestContext）"清单落地）：

    **Wave 0 最小契约（9 字段 · 权限 PR-0 冻结 · 位置与顺序不许改）**：

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

    **权限 PR-3 尾附加长期字段（4 字段 · 全部 `Optional` 且默认 `None`
    · 位置在原 9 字段之后 · 只增不改 · Wave 0 消费方零破坏）**：

    - `principal_kind`：`"user"` / `"session"` / `"anonymous"`；由权限 PR-1
      `_derive_principal_kind()` 派生表在路由或本 PR PermissionService 前置
      派生并填充；middleware 直连构造时恒为 `None`（未派生）。
    - `scopes`：本请求携带的权限点位元组（frozen）；无则 `None`（等价"未派生"，
      与"空元组 = 显式无权限"区分）。
    - `session_id`：session cookie 派生的 session UUID；无则 `None`。
    - `api_key_id`：API key 派生的 key 记录 id；无则 `None`。

    **兼容承诺**：
    - 旧 9 字段位置 + 名字 + 类型完全冻结（Wave 0 契约不许破坏）。
    - 新 4 字段全部尾附加且带默认 `None` / 默认元组；现有 2 处
      `RequestContext(...)` 调用点（`_build_context` / `_fallback_context`
      / 现有测试 fixture）无需修改即可通过 dataclass 构造。
    - `scopes` 使用 `Tuple[str, ...]` 保证 frozen 语义（列表不 hashable）。
    """

    # Wave 0 最小契约（位置冻结）
    request_id: str
    legacy_user_key: Optional[str]
    x_user_id: Optional[str]
    workspace_id: Optional[str]
    project_id: Optional[str]
    client_id: Optional[str]
    ip: Optional[str]
    user_agent: Optional[str]
    auth_mode: AuthMode

    # 权限 PR-3 长期字段（尾附加 · 全部带默认值 · 只增不改）
    principal_kind: Optional[PrincipalKind] = None
    scopes: Optional[Tuple[str, ...]] = None
    session_id: Optional[str] = None
    api_key_id: Optional[str] = None


def derive_principal_kind(ctx: RequestContext) -> PrincipalKind:
    """从 `RequestContext` 派生 `principal_kind`（纯函数 · 无副作用）。

    派生表（与权限 PR-1 whoami 路由内 `_derive_principal_kind` 完全对齐）：

    1. `auth_mode == "authenticated_user"` → `"user"`（PR-3+ 认证入口启用）
    2. `auth_mode == "legacy_alias"` 且 `x_user_id` set → `"user"`
    3. `auth_mode == "legacy_alias"` 且 `x_user_id is None`
       且 `legacy_user_key` set → `"session"`
    4. `auth_mode == "anonymous_or_legacy"` 且 `legacy_user_key` set → `"session"`
    5. `auth_mode == "anonymous_or_legacy"` 且 `legacy_user_key is None`
       → `"anonymous"`

    该函数是 PermissionService / capabilities API / whoami 三处消费点共用的
    唯一派生入口，禁止在别处重复实现（GM-14 圆桌决议单一派生表约束）。
    """
    if ctx.auth_mode == "authenticated_user":
        return "user"
    if ctx.auth_mode == "legacy_alias":
        return "user" if ctx.x_user_id else "session"
    # anonymous_or_legacy
    return "session" if ctx.legacy_user_key else "anonymous"


__all__ = [
    "AuthMode",
    "PrincipalKind",
    "RequestContext",
    "derive_principal_kind",
]
