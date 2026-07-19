"""共享 fixtures：把 History writer 指向临时 sqlite。"""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def isolated_history_db(monkeypatch, tmp_path):
    """把 DATA_DB_PATH / writer singleton 指向 tmp 内的 sqlite。"""

    import main
    from app.db import engine as db_engine
    from app.db import session as db_session
    from app.task import history as history_module

    db_path = tmp_path / "history.db"
    monkeypatch.setattr(main, "DATA_DB_PATH", str(db_path))
    db_engine.reset_engine()
    db_session._SessionLocal = None
    history_module.reset_history_writer()
    try:
        yield db_path
    finally:
        history_module.reset_history_writer()
        db_engine.reset_engine()
        db_session._SessionLocal = None
