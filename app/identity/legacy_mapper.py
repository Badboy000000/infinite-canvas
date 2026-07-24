"""Legacy semantics mapper — 权限 PR-2 承接（Wave 3-N.8 Batch 1 主线 A）。

对齐：
- [[40 实施计划/用户团队权限治理实施计划与PR清单]] PR-2 "弱语义承接"。
- [[50 决策记录/决策 - 主键类型]]（identity 全表 UUID + `legacy_owner_label`
  / `legacy_user_key`）。
- [[60 讨论记录/2026-07-17 第二批开工/2026-07-17 第二批 PR 开工协调纲要]]
  §"字段冻结契约"。

本模块提供**纯函数**（无副作用、可静态测试）：

1. `resolve_legacy_owner(owner_str, aliases)` — 从旧 `owner` 字符串定位
   `UserAliasRecord`（`kind ∈ {conversation_dir, cookie_user, ip_derived}`
   兼容匹配；本模块只做字符串匹配，不判断类型语义）。
2. `resolve_legacy_user_key(user_key, aliases)` — 从 `x_user_id` 值精确匹配
   `kind="x_user_id"` alias。
3. `fill_default_workspace_project(record, *, default_workspace_id,
   default_project_id)` — 缺失 `workspace_id` / `project_id` 字段回填默认；
   已有字段保留不动。

**明确不做**：
- 不接入 middleware（PR-1 / PR-3 承接）。
- 不做权限判定（PR-4 承接）。
- 不落盘、不改现有文件、不 import `IdentityStore`（保持纯函数以便被
  `tools/migrate_legacy_semantics.py` 与运行时代码复用而无循环依赖）。
- 不删除任何旧字段（`owner` / `x_user_id` 均保留）。
"""
from __future__ import annotations

from typing import Iterable, Mapping, MutableMapping, Optional

from .schema import UserAliasRecord

DEFAULT_WORKSPACE_ID = "ws-default-00000000-0000-0000-0000-000000000000"
DEFAULT_PROJECT_ID = "proj-default-00000000-0000-0000-0000-000000000000"


def resolve_legacy_owner(
    owner_str: Optional[str],
    aliases: Iterable[UserAliasRecord],
) -> Optional[UserAliasRecord]:
    """从旧 `owner` 字符串（画布 / 素材 / 项目分组的 owner 字段）定位 UserAlias。

    - `owner_str is None` 或空 / 纯空白 → 返回 `None`。
    - 与 alias.legacy_user_key **精确匹配**（去首尾空白后比较）；匹配到多个
      时返回**第一个**（`aliases` 由调用方决定顺序，通常按 `created_at` 升序）。
    - 未匹配 → 返回 `None`。

    本函数**不做**类型推断（不判断 `owner_str` 是 conversation_dir 还是
    cookie_user），因为旧 `owner` 字段本身即是弱语义字符串；语义分类由
    `tools/migrate_legacy_semantics.py` 扫描阶段决定并写入 alias.kind。
    """

    if owner_str is None:
        return None
    key = owner_str.strip()
    if not key:
        return None
    for alias in aliases:
        legacy_key = alias.get("legacy_user_key")
        if isinstance(legacy_key, str) and legacy_key.strip() == key:
            return alias
    return None


def resolve_legacy_user_key(
    user_key: Optional[str],
    aliases: Iterable[UserAliasRecord],
) -> Optional[UserAliasRecord]:
    """从 `x_user_id` 值精确定位 `kind="x_user_id"` alias。

    - `user_key is None` 或空 / 纯空白 → 返回 `None`。
    - 只匹配 `kind == "x_user_id"` 且 `legacy_user_key == user_key.strip()`。
    - 未匹配 → 返回 `None`。
    """

    if user_key is None:
        return None
    key = user_key.strip()
    if not key:
        return None
    for alias in aliases:
        if (
            alias.get("kind") == "x_user_id"
            and isinstance(alias.get("legacy_user_key"), str)
            and alias["legacy_user_key"].strip() == key
        ):
            return alias
    return None


def fill_default_workspace_project(
    record: Mapping[str, object],
    *,
    default_workspace_id: str = DEFAULT_WORKSPACE_ID,
    default_project_id: str = DEFAULT_PROJECT_ID,
) -> MutableMapping[str, object]:
    """回填 `workspace_id` / `project_id` 默认值。

    - 输入 `record` 视为 mapping（画布 / 素材 / 项目 / 对话 / provider 等
      任意资源记录）。
    - 返回**新** dict（不改动原对象；便于测试等价断言）。
    - 已有的 `workspace_id` / `project_id` 字段**保留不动**，不覆盖用户已设定值。
    - **不删除**任何字段；只**新增**缺失的 `workspace_id` / `project_id`。

    与其它 `resolve_*` 函数一样保持纯函数：不落盘、不 import store。
    """

    result: MutableMapping[str, object] = dict(record)
    ws = result.get("workspace_id")
    if ws is None or (isinstance(ws, str) and not ws.strip()):
        result["workspace_id"] = default_workspace_id
    pj = result.get("project_id")
    if pj is None or (isinstance(pj, str) and not pj.strip()):
        result["project_id"] = default_project_id
    return result


__all__ = [
    "DEFAULT_WORKSPACE_ID",
    "DEFAULT_PROJECT_ID",
    "resolve_legacy_owner",
    "resolve_legacy_user_key",
    "fill_default_workspace_project",
]
