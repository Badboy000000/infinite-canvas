"""共享 fixtures：把 shadow read 用的 SQLite 指向临时目录。

- `isolated_shadow_env(monkeypatch, tmp_path)`：
  * 把 `DATA_DB_PATH` 指到 `tmp_path/shadow.db`；
  * 把 `DATA_DIR` 指到 `tmp_path`（`data/shadow_diff/` 落到 tmp）；
  * reset engine + session singletons，保证测试隔离。
"""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def isolated_shadow_env(monkeypatch, tmp_path):
    import main
    from app.db import engine as db_engine
    from app.db import session as db_session

    db_path = tmp_path / "shadow.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(db_path))
    monkeypatch.setattr(main, "DATA_DIR", str(tmp_path))
    db_engine.reset_engine()
    db_session._SessionLocal = None
    try:
        yield tmp_path
    finally:
        db_engine.reset_engine()
        db_session._SessionLocal = None


def migrate_baseline(tmp_path):
    """Run alembic migrations up to head into the tmp DB."""

    from app.db.engine import run_migrations

    run_migrations("head")
