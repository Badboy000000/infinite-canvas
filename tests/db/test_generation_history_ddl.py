"""数据 PR-12 · GenerationHistory DDL 契约测试（T381-T386）。

覆盖点：
- T381 表 `generation_history` 在 upgrade head 后存在
- T382 upgrade/downgrade round-trip 双向可行（先 downgrade 到 0004 · 再 upgrade
  到 0005 · 表状态一致）
- T383 `legacy_id` UNIQUE 生效（重复插入抛 IntegrityError）
- T384 4 个索引齐（created_at / canvas_id / task_id / user_key）
- T385 NOT NULL 列（id / created_at）
- T386 UUIDv7 主键 portable round-trip（SQLite CHAR + PostgreSQL Uuid）

护栏来源：任务书 · Wave 3-N.6 Batch 2 主线 B · 数据 PR-12。
"""

from __future__ import annotations

import datetime as _dt
import uuid

import pytest
from sqlalchemy import inspect, text

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


# ---------------------------------------------------------------------------
# T381 · 表存在
# ---------------------------------------------------------------------------


def test_T381_generation_history_table_exists_after_upgrade(
    isolated_env, tmp_path
):
    """upgrade head 后 `generation_history` 表存在于 SQLite。"""

    migrate_baseline(tmp_path)

    from app.db.engine import get_engine

    engine = get_engine()
    inspector = inspect(engine)
    assert "generation_history" in inspector.get_table_names()


# ---------------------------------------------------------------------------
# T382 · upgrade/downgrade round-trip 双向可行
# ---------------------------------------------------------------------------


def test_T382_upgrade_downgrade_round_trip(isolated_env, tmp_path):
    """`alembic upgrade head` → `downgrade 0004_file_object_ddl` → `upgrade head`
    · 表存在性正确反转。"""

    from alembic import command as alembic_command

    from app.db import engine as db_engine
    from app.db.engine import _alembic_config, run_migrations

    # upgrade head
    run_migrations("head")
    db_engine.reset_engine()
    engine = db_engine.get_engine()
    inspector = inspect(engine)
    assert "generation_history" in inspector.get_table_names()

    # downgrade → 0004
    cfg = _alembic_config()
    alembic_command.downgrade(cfg, "0004_file_object_ddl")
    db_engine.reset_engine()
    engine = db_engine.get_engine()
    inspector = inspect(engine)
    assert "generation_history" not in inspector.get_table_names(), (
        "downgrade 后 generation_history 表应被 drop"
    )
    # 0004 建立的 file_objects 仍在
    assert "file_objects" in inspector.get_table_names()

    # 再次 upgrade head
    run_migrations("head")
    db_engine.reset_engine()
    engine = db_engine.get_engine()
    inspector = inspect(engine)
    assert "generation_history" in inspector.get_table_names()


# ---------------------------------------------------------------------------
# T383 · legacy_id UNIQUE 生效
# ---------------------------------------------------------------------------


def test_T383_legacy_id_unique_constraint(isolated_env, tmp_path):
    """`legacy_id UNIQUE` · 重复插入抛 IntegrityError。"""

    from sqlalchemy.exc import IntegrityError

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    migrate_baseline(tmp_path)

    engine = get_engine()
    now = _dt.datetime.now(_dt.timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            t.generation_history.insert().values(
                id=generate_id(),
                legacy_id="dup_key",
                created_at=now,
                schema_version="v1_legacy_json",
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                t.generation_history.insert().values(
                    id=generate_id(),
                    legacy_id="dup_key",
                    created_at=now,
                    schema_version="v1_legacy_json",
                )
            )


# ---------------------------------------------------------------------------
# T384 · 4 个索引齐
# ---------------------------------------------------------------------------


def test_T384_all_four_indexes_present(isolated_env, tmp_path):
    """索引齐 4 项：created_at / canvas_id / task_id / user_key。"""

    from app.db.engine import get_engine

    migrate_baseline(tmp_path)
    engine = get_engine()
    inspector = inspect(engine)
    indexes = inspector.get_indexes("generation_history")
    index_names = {ix["name"] for ix in indexes}
    expected = {
        "ix_generation_history_created_at",
        "ix_generation_history_canvas_id",
        "ix_generation_history_task_id",
        "ix_generation_history_user_key",
    }
    missing = expected - index_names
    assert not missing, f"index 缺失：{sorted(missing)} · actual={sorted(index_names)}"


# ---------------------------------------------------------------------------
# T385 · NOT NULL 列（id / created_at）
# ---------------------------------------------------------------------------


def test_T385_not_null_columns(isolated_env, tmp_path):
    """`id` / `created_at` 是 NOT NULL；null 插入抛 IntegrityError。"""

    from sqlalchemy.exc import IntegrityError

    from app.db.engine import get_engine

    migrate_baseline(tmp_path)
    engine = get_engine()
    inspector = inspect(engine)
    cols = {c["name"]: c for c in inspector.get_columns("generation_history")}
    assert cols["id"]["nullable"] is False
    assert cols["created_at"]["nullable"] is False
    # nullable 列
    assert cols["legacy_id"]["nullable"] is True
    assert cols["raw_json"]["nullable"] is True

    # 具体插入 null created_at → 抛错
    with pytest.raises((IntegrityError, Exception)):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO generation_history (id, legacy_id, schema_version) "
                    "VALUES (:id, :lid, 'v1_legacy_json')"
                ),
                {"id": str(uuid.uuid4()), "lid": "no_created_at"},
            )


# ---------------------------------------------------------------------------
# T386 · UUIDv7 主键 portable round-trip（SQLite CHAR + PG Uuid）
# ---------------------------------------------------------------------------


def test_T386_uuid_primary_key_portable_round_trip(isolated_env, tmp_path):
    """UUID 主键 SQLite CHAR(36) 存储 · SELECT 回 UUID 对象；
    与 SQLAlchemy Uuid 类型一致（PG 会用原生 uuid · SQLite 用 CHAR · 应用侧
    统一 UUID 语义）。"""

    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    migrate_baseline(tmp_path)
    engine = get_engine()
    row_id = generate_id()
    now = _dt.datetime.now(_dt.timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            t.generation_history.insert().values(
                id=row_id,
                legacy_id="uuid_round_trip",
                created_at=now,
                schema_version="v1_legacy_json",
            )
        )
        loaded = conn.execute(
            select(t.generation_history.c.id).where(
                t.generation_history.c.legacy_id == "uuid_round_trip"
            )
        ).scalar_one()

    assert isinstance(loaded, uuid.UUID), (
        f"UUID round-trip 破裂 · 期望 uuid.UUID · 实际 {type(loaded).__name__}"
    )
    assert loaded == row_id
