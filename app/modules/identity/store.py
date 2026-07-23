"""`app.modules.identity.store` — 3 个只读/幂等 upsert 函数。

**设计原则**：
- 所有函数都是"骨架 API"：纯读 / 幂等 upsert，不修改任何业务写路径。
- 不在本模块内引入 Session / 事务管理 —— 调用方负责连接生命周期。
- 所有函数可重入（幂等）：多次调用不产生副作用。
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.engine import Connection

from app.shared.ids import generate_id


def _now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def ensure_default_workspace(conn: Connection) -> dict[str, Any]:
    """幂等确保 `system` workspace 存在。

    通过 `legacy_id='__system__'`（实际使用 name='system' + kind='system' 做幂等）
    检查已存在则返回现有行；否则插入一行。

    返回 dict 包含 `id`/`name`/`kind` 字段。
    """
    stmt = select(
        text("id, name, kind")
    ).select_from(
        text("workspace")
    ).where(
        text("name = 'system' AND kind = 'system'")
    ).limit(1)
    row = conn.execute(stmt).fetchone()
    if row is not None:
        return {"id": row[0], "name": row[1], "kind": row[2]}

    now = _now_utc()
    ws_id = generate_id()
    conn.execute(
        text(
            "INSERT INTO workspace (id, name, kind, raw_json, created_at, updated_at) "
            "VALUES (:id, 'system', 'system', '{}', :now, :now)"
        ).bindparams(id=ws_id, now=now)
    )
    return {"id": ws_id, "name": "system", "kind": "system"}


def ensure_default_project(conn: Connection, workspace_id: Any) -> dict[str, Any]:
    """幂等确保 default project 存在。

    通过 `legacy_id='__default__'` 做幂等；已存在则返回现有行。

    返回 dict 包含 `id`/`legacy_id`/`name` 字段。
    """
    stmt = select(
        text("id, legacy_id, name")
    ).select_from(
        text("projects")
    ).where(
        text("legacy_id = '__default__'")
    ).limit(1)
    row = conn.execute(stmt).fetchone()
    if row is not None:
        return {"id": row[0], "legacy_id": row[1], "name": row[2]}

    now = _now_utc()
    proj_id = generate_id()
    conn.execute(
        text(
            "INSERT INTO projects (id, legacy_id, name, raw_json, schema_version, "
            "imported_at, created_at, updated_at) "
            "VALUES (:id, '__default__', 'default', '{}', 'v1_legacy_json', :now, :now, :now)"
        ).bindparams(id=proj_id, now=now)
    )
    return {"id": proj_id, "legacy_id": "__default__", "name": "default"}


def resolve_or_create_user_alias(
    conn: Connection,
    legacy_user_key: str,
    *,
    user_id: Any | None = None,
) -> dict[str, Any]:
    """幂等承接旧身份（legacy_user_key → UserAlias）。

    如果 `legacy_user_key` 已存在，返回现有行。
    如果不存在，创建一个新用户 + 新 UserAlias 行。

    - `user_id`：可选，指定用户 ID（多 alias 指向同一用户时使用）。
      不提供时自动生成新 UUID。

    返回 dict 包含 `user_alias_id`/`user_id`/`legacy_user_key` 字段。
    """
    if not legacy_user_key or not legacy_user_key.strip():
        raise ValueError("legacy_user_key 不能为空")

    # 查已存在的 alias
    stmt = select(
        text("id, user_id, legacy_user_key")
    ).select_from(
        text("user_alias")
    ).where(
        text("legacy_user_key = :key")
    ).bindparams(key=legacy_user_key.strip())
    row = conn.execute(stmt).fetchone()
    if row is not None:
        return {
            "user_alias_id": row[0],
            "user_id": row[1],
            "legacy_user_key": row[2],
        }

    now = _now_utc()
    actual_user_id = user_id if user_id is not None else generate_id()
    alias_id = generate_id()

    # 检查 user 是否存在
    user_stmt = select(
        text("id")
    ).select_from(
        text("user")
    ).where(
        text("id = :uid")
    ).bindparams(uid=actual_user_id)
    user_row = conn.execute(user_stmt).fetchone()

    if user_row is None:
        conn.execute(
            text(
                "INSERT INTO user (id, legacy_user_key, display_name, created_at, updated_at) "
                "VALUES (:id, :key, :key, :now, :now)"
            ).bindparams(id=actual_user_id, key=legacy_user_key.strip(), now=now)
        )

    conn.execute(
        text(
            "INSERT INTO user_alias (id, user_id, legacy_user_key, raw_json, created_at, updated_at) "
            "VALUES (:id, :uid, :key, '{}', :now, :now)"
        ).bindparams(
            id=alias_id,
            uid=actual_user_id,
            key=legacy_user_key.strip(),
            now=now,
        )
    )

    return {
        "user_alias_id": alias_id,
        "user_id": actual_user_id,
        "legacy_user_key": legacy_user_key.strip(),
    }