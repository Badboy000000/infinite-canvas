"""共享 fixtures：把影子层指向临时 sqlite。"""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def isolated_shadow_db(monkeypatch, tmp_path):
    """把 DATA_DB_PATH / registry singleton 指向 tmp 内的 sqlite。"""

    import main
    from app.db import engine as db_engine
    from app.db import session as db_session
    from app.task import shadow as shadow_module

    db_path = tmp_path / "shadow.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(db_path))
    db_engine.reset_engine()
    db_session._SessionLocal = None
    shadow_module.reset_shadow_registry()
    try:
        yield db_path
    finally:
        shadow_module.reset_shadow_registry()
        db_engine.reset_engine()
        db_session._SessionLocal = None
