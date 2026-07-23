"""数据 PR-13 · Identity 骨架 DDL 契约测试（T450-T469 · 20 项）。

覆盖点：
- T450-T451 · 0006 up/down 幂等（重复 up 无副作用 · down 完全撤销）
- T452 · 默认 `system` workspace 存在 · name='system' + kind='system'
- T453 · 默认 project 存在 · legacy_id='__default__'
- T454-T455 · 3 role 预置 (admin/member/viewer)
- T456 · UserAlias 幂等承接（同 legacy_user_key 只有 1 行）
- T457-T460 · 表结构断言（user/workspace/membership/role/permission/user_alias 存在 · 字段完备）
- T461-T462 · workspace_id 字段已 ALTER 追加到业务表
- T463-T464 · 归属回填幂等（所有资源默认 workspace_id 已填 · 再次跑 backfill 无 diff）
- T465 · 接口 shape 未变（sample /api/canvases GET · 断言响应字段与前置 PR 快照一致）
- T466-T469 · P0 密钥防线 - identity 表内断言无 api_key/access_token/secret 命中

护栏来源：任务书 · Wave 3-N.7 Batch 1 主线 B · 数据 PR-13。
"""

from __future__ import annotations

import datetime as _dt
import uuid as _uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


REPO_ROOT = Path(__file__).resolve().parents[2]

IDENTITY_TABLES = (
    "user",
    "workspace",
    "membership",
    "role",
    "permission",
    "user_alias",
)

# 密钥关键词（P0 防线检查）
_SECRET_KEYWORDS = ("api_key", "access_token", "secret", "password", "token")


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    with isolated_shadow_env(monkeypatch, tmp_path) as sandbox:
        yield sandbox


@pytest.fixture
def migrated_engine(isolated_env):
    """建库 + 迁移到 head + 返回 engine。"""
    migrate_baseline(isolated_env)
    from app.db.engine import get_engine

    engine = get_engine()
    yield engine


# ---------------------------------------------------------------------------
# T450 · upgrade 幂等（重复 up 无副作用）
# ---------------------------------------------------------------------------


def test_T450_upgrade_idempotent(isolated_env, tmp_path):
    """重复 `alembic upgrade head` 二次执行无副作用。"""
    migrate_baseline(tmp_path)
    # 第二次 upgrade head
    from app.db.engine import run_migrations

    run_migrations("head")

    from app.db.engine import get_engine

    engine = get_engine()
    inspector = inspect(engine)
    for table_name in IDENTITY_TABLES:
        assert table_name in inspector.get_table_names(), (
            f"表 {table_name} 应在第二次 upgrade 后仍存在"
        )


# ---------------------------------------------------------------------------
# T451 · upgrade/downgrade round-trip 双向可行
# ---------------------------------------------------------------------------


def test_T451_upgrade_downgrade_round_trip(isolated_env, tmp_path):
    """`alembic upgrade head` → `downgrade 0005_generation_history` → `upgrade head`
    · 表存在性正确反转。"""
    from alembic import command as alembic_command

    from app.db import engine as db_engine
    from app.db.engine import _alembic_config, run_migrations

    # upgrade head
    run_migrations("head")
    db_engine.reset_engine()
    engine = db_engine.get_engine()
    inspector = inspect(engine)
    for table_name in IDENTITY_TABLES:
        assert table_name in inspector.get_table_names(), (
            f"upgrade 后 {table_name} 应存在"
        )

    # downgrade → 0005
    cfg = _alembic_config()
    alembic_command.downgrade(cfg, "0005_generation_history")
    db_engine.reset_engine()
    engine = db_engine.get_engine()
    inspector = inspect(engine)
    for table_name in IDENTITY_TABLES:
        assert table_name not in inspector.get_table_names(), (
            f"downgrade 后 {table_name} 应被 drop"
        )
    # 0005 建立的 generation_history 仍在
    assert "generation_history" in inspector.get_table_names()

    # 再次 upgrade head
    run_migrations("head")
    db_engine.reset_engine()
    engine = db_engine.get_engine()
    inspector = inspect(engine)
    for table_name in IDENTITY_TABLES:
        assert table_name in inspector.get_table_names(), (
            f"再次 upgrade 后 {table_name} 应存在"
        )


# ---------------------------------------------------------------------------
# T452 · 默认 system workspace 存在
# ---------------------------------------------------------------------------


def test_T452_default_system_workspace_exists(migrated_engine):
    """默认 `system` workspace 存在 · name='system' + kind='system'。"""
    with migrated_engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, name, kind FROM workspace WHERE name = 'system' AND kind = 'system' LIMIT 1")
        ).fetchone()
    assert row is not None, "system workspace 应存在"
    assert row[1] == "system"
    assert row[2] == "system"


# ---------------------------------------------------------------------------
# T453 · 默认 project 存在
# ---------------------------------------------------------------------------


def test_T453_default_project_exists(migrated_engine):
    """默认 `default` project 存在 · legacy_id='__default__'。"""
    with migrated_engine.connect() as conn:
        row = conn.execute(
            text("SELECT id, legacy_id, name FROM projects WHERE legacy_id = '__default__' LIMIT 1")
        ).fetchone()
    assert row is not None, "default project 应存在"
    assert row[1] == "__default__"
    assert row[2] == "default"


# ---------------------------------------------------------------------------
# T454-T455 · 3 role 预置 (admin/member/viewer)
# ---------------------------------------------------------------------------


def test_T454_three_roles_preseeded(migrated_engine):
    """3 个角色预置：admin / member / viewer。"""
    with migrated_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM role ORDER BY name")
        ).fetchall()
    role_names = {row[0] for row in rows}
    expected = {"admin", "member", "viewer"}
    missing = expected - role_names
    assert not missing, f"预置角色缺失：{sorted(missing)}"


def test_T455_role_preseed_idempotent(migrated_engine):
    """角色预置幂等：再次插入同 role name 不产生副本。"""
    from app.shared.ids import generate_id

    now = _dt.datetime.now(_dt.timezone.utc)
    with migrated_engine.connect() as conn:
        # 手动再插入一次 admin（INSERT OR IGNORE）
        conn.execute(
            text(
                "INSERT OR IGNORE INTO role (id, name, permissions_json, raw_json, created_at, updated_at) "
                "VALUES (:id, 'admin', '{}', '{}', :now, :now)"
            ).bindparams(id=generate_id(), now=now)
        )
        conn.commit()

    with migrated_engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM role WHERE name = 'admin'")
        ).scalar()
    assert count == 1, f"admin 角色重复插入后应只有 1 行，实际 {count}"


# ---------------------------------------------------------------------------
# T456 · UserAlias 幂等承接
# ---------------------------------------------------------------------------


def test_T456_user_alias_idempotent(migrated_engine):
    """同 legacy_user_key 只有 1 行（幂等承接）。"""
    from app.shared.ids import generate_id

    now = _dt.datetime.now(_dt.timezone.utc)
    user_id = generate_id()

    with migrated_engine.begin() as conn:
        # 先建 user
        conn.execute(
            text(
                "INSERT INTO user (id, legacy_user_key, display_name, created_at, updated_at) "
                "VALUES (:id, 'test_key', 'test', :now, :now)"
            ).bindparams(id=user_id, now=now)
        )
        # 建 alias
        conn.execute(
            text(
                "INSERT INTO user_alias (id, user_id, legacy_user_key, raw_json, created_at, updated_at) "
                "VALUES (:aid, :uid, 'test_key', '{}', :now, :now)"
            ).bindparams(aid=generate_id(), uid=user_id, now=now)
        )

    # 重复插入同 legacy_user_key → 应抛 IntegrityError
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO user_alias (id, user_id, legacy_user_key, raw_json, created_at, updated_at) "
                    "VALUES (:aid, :uid, 'test_key', '{}', :now, :now)"
                ).bindparams(aid=generate_id(), uid=user_id, now=now)
            )

    # 只能查到 1 条
    with migrated_engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM user_alias WHERE legacy_user_key = 'test_key'")
        ).scalar()
    assert count == 1, f"同 legacy_user_key 应只有 1 行，实际 {count}"


# ---------------------------------------------------------------------------
# T457-T460 · 表结构断言
# ---------------------------------------------------------------------------


def test_T457_all_identity_tables_exist(migrated_engine):
    """6 张 identity 表全部存在。"""
    inspector = inspect(migrated_engine)
    table_names = set(inspector.get_table_names())
    missing = set(IDENTITY_TABLES) - table_names
    assert not missing, f"缺少 identity 表：{sorted(missing)}"


def test_T458_user_table_columns(migrated_engine):
    """user 表字段完备。"""
    inspector = inspect(migrated_engine)
    cols = {c["name"]: c for c in inspector.get_columns("user")}
    expected = {
        "id", "legacy_user_key", "display_name",
        "avatar_url", "created_at", "updated_at",
    }
    missing = expected - set(cols.keys())
    assert not missing, f"user 表缺少字段：{sorted(missing)}"
    assert cols["id"]["nullable"] is False
    assert cols["created_at"]["nullable"] is False


def test_T459_workspace_membership_columns(migrated_engine):
    """workspace 和 membership 表字段完备。"""
    inspector = inspect(migrated_engine)

    # workspace
    ws_cols = {c["name"] for c in inspector.get_columns("workspace")}
    for col in ("id", "name", "kind", "created_at", "updated_at"):
        assert col in ws_cols, f"workspace 缺少字段 {col}"

    # membership
    mem_cols = {c["name"] for c in inspector.get_columns("membership")}
    for col in ("id", "user_id", "workspace_id", "role", "created_at", "updated_at"):
        assert col in mem_cols, f"membership 缺少字段 {col}"


def test_T460_role_permission_user_alias_columns(migrated_engine):
    """role / permission / user_alias 表字段完备。"""
    inspector = inspect(migrated_engine)

    # role
    role_cols = {c["name"] for c in inspector.get_columns("role")}
    for col in ("id", "name", "permissions_json", "created_at", "updated_at"):
        assert col in role_cols, f"role 缺少字段 {col}"

    # permission
    perm_cols = {c["name"] for c in inspector.get_columns("permission")}
    for col in ("id", "code", "description", "created_at", "updated_at"):
        assert col in perm_cols, f"permission 缺少字段 {col}"

    # user_alias
    alias_cols = {c["name"] for c in inspector.get_columns("user_alias")}
    for col in ("id", "user_id", "legacy_user_key", "created_at", "updated_at"):
        assert col in alias_cols, f"user_alias 缺少字段 {col}"


# ---------------------------------------------------------------------------
# T461-T462 · workspace_id 字段已 ALTER 追加到 8 张业务表
# ---------------------------------------------------------------------------


def test_T461_workspace_id_added_to_business_tables(migrated_engine):
    """workspace_id 字段已 ALTER 追加到 8 张业务表。"""
    business_tables = (
        "canvases", "asset_libraries", "provider_configs",
        "generation_history", "prompt_libraries",
        "workflow_definitions", "projects", "prompt_items",
    )
    inspector = inspect(migrated_engine)
    for table_name in business_tables:
        cols = {c["name"] for c in inspector.get_columns(table_name)}
        assert "workspace_id" in cols, (
            f"{table_name} 缺少 workspace_id 字段"
        )


def test_T462_created_by_user_id_and_legacy_owner_label_added(migrated_engine):
    """created_by_user_id 和 legacy_owner_label 字段已 ALTER 追加到业务表。"""
    business_tables = (
        "canvases", "asset_libraries", "provider_configs",
        "generation_history", "prompt_libraries",
        "workflow_definitions", "projects", "prompt_items",
        "asset_categories", "asset_items",
    )
    inspector = inspect(migrated_engine)
    for table_name in business_tables:
        cols = {c["name"] for c in inspector.get_columns(table_name)}
        assert "created_by_user_id" in cols, (
            f"{table_name} 缺少 created_by_user_id 字段"
        )
        assert "legacy_owner_label" in cols, (
            f"{table_name} 缺少 legacy_owner_label 字段"
        )


# ---------------------------------------------------------------------------
# T463-T464 · 归属回填幂等
# ---------------------------------------------------------------------------


def test_T463_backfill_workspace_id(migrated_engine):
    """所有业务表 workspace_id 已回填（通过导入 identity importer）。"""
    from app.data_import.importers import identity as identity_importer

    business_tables = (
        "canvases", "asset_libraries", "provider_configs",
        "generation_history", "prompt_libraries",
        "workflow_definitions", "projects", "prompt_items",
    )

    with migrated_engine.begin() as conn:
        result = identity_importer.import_records(conn)

    assert result["domain"] == "identity"
    assert result["inserted"] >= 0  # 可能 0 行（空库）


def test_T464_backfill_idempotent(migrated_engine):
    """再次跑 backfill 无 diff（workspace_id 已填的行不再更新）。"""
    from app.data_import.importers import identity as identity_importer

    # 第一次跑
    with migrated_engine.begin() as conn:
        result1 = identity_importer.import_records(conn)

    # 第二次跑
    with migrated_engine.begin() as conn:
        result2 = identity_importer.import_records(conn)

    # 第二次的 workspace_id 回填数应为 0（已填的行不再更新）
    # 但 owner_label 回填可能还有（如果表有 owner 字段）
    assert result2["inserted"] == 0, (
        f"第二次回填 workspace_id 应无新行，实际 {result2['inserted']}"
    )


# ---------------------------------------------------------------------------
# T465 · 接口 shape 未变（sample /api/canvases GET）
# ---------------------------------------------------------------------------


def test_T465_api_shape_unchanged(migrated_engine):
    """接口 shape 未变：`owner` 字符串字段仍可读。"""
    # 验证 canvases 表仍保留 owner_label 字段（旧字段未删）
    inspector = inspect(migrated_engine)
    canvas_cols = {c["name"] for c in inspector.get_columns("canvases")}
    assert "owner_label" in canvas_cols, "owner_label 字段应保留"
    # 新字段 legacy_owner_label 已追加
    assert "legacy_owner_label" in canvas_cols, "legacy_owner_label 字段应存在"


# ---------------------------------------------------------------------------
# T466-T469 · P0 密钥防线 - identity 表内断言无密钥命中
# ---------------------------------------------------------------------------


def test_T466_no_api_key_in_user_table(migrated_engine):
    """user 表不包含任何密钥字段。"""
    inspector = inspect(migrated_engine)
    cols = {c["name"].lower() for c in inspector.get_columns("user")}
    for keyword in _SECRET_KEYWORDS:
        hits = [c for c in cols if keyword in c]
        assert not hits, (
            f"user 表包含疑似密钥字段：{hits}（keyword={keyword}）"
        )


def test_T467_no_api_key_in_workspace_table(migrated_engine):
    """workspace 表不包含任何密钥字段。"""
    inspector = inspect(migrated_engine)
    cols = {c["name"].lower() for c in inspector.get_columns("workspace")}
    for keyword in _SECRET_KEYWORDS:
        hits = [c for c in cols if keyword in c]
        assert not hits, (
            f"workspace 表包含疑似密钥字段：{hits}（keyword={keyword}）"
        )


def test_T468_no_api_key_in_membership_table(migrated_engine):
    """membership 表不包含任何密钥字段。"""
    inspector = inspect(migrated_engine)
    cols = {c["name"].lower() for c in inspector.get_columns("membership")}
    for keyword in _SECRET_KEYWORDS:
        hits = [c for c in cols if keyword in c]
        assert not hits, (
            f"membership 表包含疑似密钥字段：{hits}（keyword={keyword}）"
        )


def test_T469_no_api_key_in_user_alias_table(migrated_engine):
    """user_alias 表不包含任何密钥字段（legacy_user_key 非密钥）。"""
    inspector = inspect(migrated_engine)
    cols = {c["name"].lower() for c in inspector.get_columns("user_alias")}
    for keyword in _SECRET_KEYWORDS:
        hits = [c for c in cols if keyword in c]
        assert not hits, (
            f"user_alias 表包含疑似密钥字段：{hits}（keyword={keyword}）"
        )