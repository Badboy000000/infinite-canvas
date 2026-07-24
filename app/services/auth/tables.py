"""`app.services.auth.tables` — Auth 层 SQLAlchemy `Table` 定义。

**硬约束**：本模块中所有 `Table` 都必须挂到 `from app.db.base import metadata`
单例上（禁自建 `MetaData()`）；否则 Alembic `autogenerate` 与 `env.py`
`target_metadata` 感知不到 schema drift。

设计要点：

- `sessions` 表：服务端 opaque session 存储，主键为 session_id（UUID4），
  cookie 值即 `sid.<session_id>` 格式，不包含用户信息。
- `user` 表已存在（0006_identity），本模块只定义 `auth_credentials` 表
  用于存储登录凭据，与 `user` 表通过 `user_id` FK 关联。
- 用户登录凭据从 `user` 表拆出为独立 `auth_credentials` 表，避免污染
  `user` 基础行（非所有用户都需要认证凭据，部分用户仅通过 legacy alias 存在）。

索引：
- `ix_auth_credentials_username`：username 登录查询
- `ix_sessions_user_id`：按用户查询活跃 session
- `ix_sessions_expires_at`：过期 session 清理扫描
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from app.db.base import metadata

# ---------------------------------------------------------------------------
# auth_credentials
# ---------------------------------------------------------------------------

auth_credentials = Table(
    "auth_credentials",
    metadata,
    Column("user_id", String(36), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True, nullable=False),
    Column("username", String(255), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("must_change_password", Integer, nullable=False, server_default="0"),
    Column("failed_attempts", Integer, nullable=False, server_default="0"),
    Column("locked_until", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("username", name="uq_auth_credentials_username"),
)

# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------

sessions = Table(
    "sessions",
    metadata,
    Column("session_id", String(36), primary_key=True, nullable=False),
    Column("user_id", String(36), ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("username", String(255), nullable=False),
    Column("ip", String(45), nullable=True),
    Column("user_agent", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=True),
)

#: 本 PR 引入的表名（供测试断言使用）。
AUTH_TABLE_NAMES = (
    "auth_credentials",
    "sessions",
)

__all__ = [
    "auth_credentials",
    "sessions",
    "AUTH_TABLE_NAMES",
]