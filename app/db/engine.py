"""`app.db.engine` — SQLAlchemy `Engine` 工厂 + Alembic migrate CLI dispatch。

设计要点（承接 [[50 决策记录/决策 - ORM 与迁移工具选型]] 使用规范 §3 Session 管理）：

- **数据库路径来源**：`get_settings().data_db_path`（读时求值）；本模块**不许**
  直接 `os.getenv("DATA_DB_PATH")` 或硬编码 `data/app.db`。
- **父目录保障**：`_ensure_parent_dir()` 在 engine 首次构造 / migrate 首次执行
  时把 `<data_db_path>.parent` 建好；`makedirs(exist_ok=True)`。
- **URL 规范化**：SQLite path → `sqlite:///` 绝对路径 URL。绝对路径开头 `/`
  会与 dialect 三个斜杠合成 `sqlite:////abs/path`（Unix）；Windows 绝对路径
  `C:\\...` 保留反斜杠或用 `os.fspath()` 归一后交给 SQLAlchemy 自行处理。
- **连接池**：SQLite 单进程用 `pool_size` 等参数无意义；使用默认 `NullPool`
  的 alternative——`sqlalchemy.create_engine` 对 sqlite 默认使用
  `SingletonThreadPool`，本 PR 保持默认。多线程读时 `connect_args=
  {"check_same_thread": False}` 允许跨线程共享连接对象（配合 session-scope
  单线程使用契约）。
- **PRAGMA**：`journal_mode=WAL` / `synchronous=NORMAL` / `foreign_keys=ON`
  / `busy_timeout=400` 在 `connect` 事件监听器上统一注入（PR-10 · CB-P5-08a）。
- **进程内单例**：`get_engine()` 返回本进程内首次构造后的同一 Engine。
  `reset_engine()` 供测试代码显式拆除。
- **签名冻结**：`create_engine(url=None, *, echo=False) -> Engine`；
  `get_engine() -> Engine`；`get_database_url() -> str`；`reset_engine() -> None`；
  `run_migrations(revision: str = "head") -> None`（供 CLI 与测试复用）。

**不做**：

- 不做 asyncio 引擎（治理期同步引擎更简单可 review，详见决策 §3）。
- 不定义任何 Table / Mapped 类。
- 不在 import 时连库；`get_engine()` 首次调用才实例化。

详见 [[40 实施计划/数据模型治理实施计划与PR清单]] PR-1。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine as _sa_create_engine
from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# 进程内单例；测试用 `reset_engine()` 拆除
_engine_singleton: Optional[Engine] = None


def get_database_url() -> str:
    """现读 `Settings.data_db_path` 并规范化为 SQLite URL。

    - `sqlite:///` 前缀 + 绝对路径。
    - 从 `app.shared.settings.get_settings()` 现读，**禁止**直接 `os.getenv`
      或字面常量；参见硬约束 2。
    """
    # 懒 import：规避 `main -> app.shared.settings -> main` 循环。
    from app.shared.settings import get_settings

    settings = get_settings()
    raw_path = settings.data_db_path
    if not raw_path:
        raise RuntimeError(
            "Settings.data_db_path 为空；请检查 main.py:DATA_DB_PATH 常量"
        )
    abs_path = os.path.abspath(raw_path)
    return f"sqlite:///{abs_path}"


def _ensure_parent_dir(url_or_path: str) -> None:
    """把 SQLite 数据库文件所在目录建好（`parents=True, exist_ok=True`）。

    - 传入既可以是 `sqlite:///<abs-path>` URL，也可以是纯路径。
    - 内存数据库 `sqlite:///:memory:` / `sqlite://` 直接跳过。
    """
    if not url_or_path:
        return
    if url_or_path.startswith("sqlite://") and (
        url_or_path.endswith(":memory:") or url_or_path == "sqlite://"
    ):
        return
    if url_or_path.startswith("sqlite:///"):
        raw = url_or_path[len("sqlite:///"):]
    else:
        raw = url_or_path
    if not raw or raw == ":memory:":
        return
    parent = Path(raw).parent
    if parent and str(parent) not in {"", "."}:
        parent.mkdir(parents=True, exist_ok=True)


def _apply_sqlite_pragmas(engine: Engine) -> None:
    """在每次新连接上注入 SQLite PRAGMA。

    详见 [[50 决策记录/决策 - ORM 与迁移工具选型]] 使用规范 §3。
    - `journal_mode=WAL`：并发读友好。
    - `synchronous=NORMAL`：治理期性能 / 一致性折中（Canvas PR-6/7 依赖此值）。
    - `foreign_keys=ON`：SQLite 默认关闭外键，需显式启用。
    - `busy_timeout=400`：单进程 web + 后台任务并发时缓解 `SQLITE_BUSY`
      （PR-10 · CB-P5-08a：从 5000ms 下调，防止用户可见 API stall 5s+）。
    """
    # 仅对 sqlite dialect 生效；PostgreSQL 迁移时本函数直接跳过。
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, connection_record):  # pragma: no cover - 依赖驱动
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=400")
        finally:
            cursor.close()


def create_engine(url: Optional[str] = None, *, echo: bool = False) -> Engine:
    """构造 SQLAlchemy `Engine`。

    - `url` 缺省时通过 `get_database_url()` 现读构造；否则按传入 URL 直连。
    - `connect_args={"check_same_thread": False}` 允许跨线程复用；上层调用
      需自行保证单线程 session-scope。
    - `future=True` 强制 SQLAlchemy 2.x 行为。
    - 无 pool 参数：SQLite 默认 `SingletonThreadPool` 已足够治理期使用。
    """
    resolved_url = url or get_database_url()
    _ensure_parent_dir(resolved_url)
    connect_args = {}
    if resolved_url.startswith("sqlite:"):
        connect_args["check_same_thread"] = False
    engine = _sa_create_engine(
        resolved_url,
        echo=echo,
        future=True,
        connect_args=connect_args,
    )
    _apply_sqlite_pragmas(engine)
    logger.info("db.engine.create_engine url=%s", resolved_url)
    return engine


def get_engine() -> Engine:
    """进程内单例。首次调用时构造并保存。"""
    global _engine_singleton
    if _engine_singleton is None:
        _engine_singleton = create_engine()
    return _engine_singleton


def reset_engine() -> None:
    """拆除并释放单例；供测试隔离用。"""
    global _engine_singleton
    if _engine_singleton is not None:
        try:
            _engine_singleton.dispose()
        except Exception:  # pragma: no cover
            logger.exception("db.engine.reset_engine dispose failed")
        _engine_singleton = None


def _alembic_config():
    """构造 Alembic `Config` 对象（本地 API，不通过 CLI）。

    - `script_location = app/db/migrations`（对应仓库根 `alembic.ini` 中的
      `script_location`；此处直接传绝对路径，避免依赖 CWD）。
    - `sqlalchemy.url` 由 `get_database_url()` 现读注入，覆盖 ini 内的占位符。
    """
    # 懒 import：避免顶层依赖 alembic 的模块加载路径。
    from alembic.config import Config

    from app.db import migrations as _migrations_pkg

    script_location = os.path.dirname(os.path.abspath(_migrations_pkg.__file__))
    cfg = Config()
    cfg.set_main_option("script_location", script_location)
    cfg.set_main_option("sqlalchemy.url", get_database_url())
    return cfg


def run_migrations(revision: str = "head") -> None:
    """通过 Alembic 内部 API 执行 `upgrade <revision>`。

    - 供 `python main.py migrate [head|<rev>]` CLI 与测试复用同一入口。
    - 建好数据库父目录，避免首次运行时 `sqlite3.OperationalError: unable to
      open database file`。
    """
    from alembic import command as alembic_command

    _ensure_parent_dir(get_database_url())
    cfg = _alembic_config()
    logger.info("db.engine.run_migrations revision=%s", revision)
    alembic_command.upgrade(cfg, revision)


__all__ = [
    "create_engine",
    "get_database_url",
    "get_engine",
    "reset_engine",
    "run_migrations",
]
