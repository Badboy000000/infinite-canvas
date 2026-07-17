"""`app.db.session` — 同步 `Session` 工厂 + 上下文管理器。

设计要点（承接 [[50 决策记录/决策 - ORM 与迁移工具选型]] 使用规范 §3 Session 管理）：

- **`SessionLocal`**：`sessionmaker` 工厂，惰性绑定到 `engine.get_engine()`。
  当 `_SessionLocal` 尚未配置时，第一次调用 `SessionLocal()` 自动从
  `engine.get_engine()` 拿 Engine 并配置。
- **`expire_on_commit=False`**、**`autoflush=False`**：硬要求（决策 §3）。
  确保聚合根 typed 属性在事务提交后仍可读，且不发生隐式 flush 打乱事务边界。
- **`get_session()`**：`contextmanager`，提供 try/commit/except/rollback/finally
  close 模板。Service / Store 层显式 `with get_session() as session:` 即可。
- **不引入 FastAPI 依赖注入耦合**：`get_session()` 是纯 Python context manager，
  不依赖 `Depends()` / `Request` / `request.state`。未来 PR 如需 FastAPI DI，
  可在 `app/api/dependencies.py` 中另建 `def get_db_session(): ...` 包装器。

**本 PR 不做**：

- 不定义 asyncio session。
- 不定义 `Session` 子类或自定义 `Session` 行为。
- 不接入任何 Store facade。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-1。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)

# 模块级 sessionmaker（惰性绑定）；`SessionLocal()` 首次调用时自动配置。
_SessionLocal: Optional[sessionmaker] = None


def _ensure_local() -> sessionmaker:
    """确保 `_SessionLocal` 已绑定 engine；未绑定则从 `engine.get_engine()` 获取。"""
    global _SessionLocal
    if _SessionLocal is None:
        from app.db.engine import get_engine

        _SessionLocal = sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
        )
    return _SessionLocal


def SessionLocal() -> Session:
    """构造一个新的同步 `Session`。

    - 每次调用创建新会话，调用方负责 `session.close()`。
    - 首选使用 `get_session()` context manager 自动管理生命周期。
    """
    return _ensure_local()()


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """`Session` 生命周期管理 context manager。

    用法示例::

        from app.db.session import get_session

        with get_session() as session:
            result = session.execute(select(...))
            session.commit()  # 显式提交，或取决于事务边界策略

    模板：
    - 进入：`SessionLocal()` 开新会话。
    - 退出正常：`session.commit()` 自动提交（除非调用方已 `session.rollback()`）。
    - 退出异常：`session.rollback()` 回滚未尽事务。
    - finally：`session.close()` 释放连接回连接池。
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["SessionLocal", "get_session"]