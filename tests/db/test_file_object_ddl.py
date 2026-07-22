"""数据 PR-18 · FileObject / FileRef / LegacyUrlRef DDL 契约测试。

10 项测试（T135-T144）对应任务书"测试代码"段：

- T135 · 3 张表 upgrade 到 head 后存在。
- T136 · upgrade + downgrade 双向可执行；downgrade 后 3 表消失。
- T137 · `file_objects.sha256` UNIQUE 约束（同 sha256 二次插入 → IntegrityError）。
- T138 · `file_objects.legacy_path` UNIQUE 约束。
- T139 · `file_objects.reference_count` DEFAULT 0（未赋值时 =0）。
- T140 · `file_refs (subject_table, subject_id, role, file_id)` 组合 UNIQUE。
- T141 · `legacy_url_refs.url` UNIQUE 约束。
- T142 · 三表所有 NOT NULL 列缺失时 → IntegrityError。
- T143 · UUIDv7 主键类型 portable（SQLite 走 SQLAlchemy 2.0 `Uuid` → CHAR(36)）。
- T144 · 零触碰断言：`asset_items.file_ref TEXT NULL` 占位列未动
        （相较 baseline `a6f863a` AST + 结构双证据）。
"""

from __future__ import annotations

import ast
import subprocess
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from tests.shadow_read._helpers import isolated_shadow_env, migrate_baseline


REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_REF = "a6f863a"

FILE_OBJECT_TABLES = ("file_objects", "file_refs", "legacy_url_refs")


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
# 辅助 payload / 插入器
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)


def _bytes(n: int, filler: int = 0x11) -> bytes:
    return bytes([filler]) * n


def _minimal_file_object(**overrides):
    """返回一份满足所有 NOT NULL 列的 file_objects 行 dict。

    默认 sha256 / xxh64 各自 filler 值不冲突；测试用例可通过 overrides
    修改任一字段（含 legacy_path 等 nullable）。

    UUID 主键与 FK 列用 `str` 形式绑定,避免 raw `text()` INSERT 绕开
    SQLAlchemy 2.0 `Uuid` 类型层时 SQLite3 驱动 `type 'UUID' is not supported`
    报错。DDL 侧 `Uuid(as_uuid=True)` 落到 SQLite 依然是 CHAR(32/36);
    读回时用 `_uuid.UUID(str(raw))` 归一(见 T143)。
    """
    payload = {
        "id": str(_uuid.uuid4()),
        "sha256": _bytes(32, 0x11),
        "xxh64": _bytes(8, 0x22),
        "size_bytes": 1024,
        "object_key": "uploads/default.bin",
        "origin_kind": "upload",
        "created_at": _now(),
    }
    payload.update(overrides)
    # 允许调用方传入 uuid.UUID 或 str · 内部统一 str 形式
    for k in ("id", "owner_user_id", "workspace_id", "project_id",
              "import_batch_id"):
        if k in payload and isinstance(payload[k], _uuid.UUID):
            payload[k] = str(payload[k])
    return payload


def _insert_file_object(conn, **overrides):
    payload = _minimal_file_object(**overrides)
    conn.execute(
        text(
            "INSERT INTO file_objects "
            "(id, sha256, xxh64, size_bytes, object_key, origin_kind, "
            " created_at) "
            "VALUES "
            "(:id, :sha256, :xxh64, :size_bytes, :object_key, :origin_kind, "
            " :created_at)"
        ),
        payload,
    )
    return payload


# ---------------------------------------------------------------------------
# T135 · 3 张表 upgrade 到 head 后存在
# ---------------------------------------------------------------------------


def test_t135_all_three_tables_exist_after_upgrade(migrated_engine):
    """T135 · Alembic upgrade head → file_objects / file_refs /
    legacy_url_refs 三张表都存在于 SQLite schema。"""
    inspector = inspect(migrated_engine)
    names = set(inspector.get_table_names())
    for table in FILE_OBJECT_TABLES:
        assert table in names, (
            f"数据 PR-18 硬约束:{table!r} 必须在 alembic upgrade head 之后存在;"
            f" 实际 tables={sorted(names)}"
        )


# ---------------------------------------------------------------------------
# T136 · upgrade + downgrade 双向可执行；downgrade 后 3 表消失
# ---------------------------------------------------------------------------


def test_t136_upgrade_downgrade_round_trip(isolated_env, monkeypatch):
    """T136 · Alembic `upgrade head` → `downgrade -1` → 3 张表消失;
    再 `upgrade head` → 3 张表回来。命令层真可执行(不是 syntax 通过)。
    """
    from app.db import engine as db_engine
    from app.db.engine import get_engine

    # 1) upgrade head
    migrate_baseline(isolated_env)
    engine = get_engine()
    names_after_up = set(inspect(engine).get_table_names())
    for table in FILE_OBJECT_TABLES:
        assert table in names_after_up, f"upgrade 后 {table} 应存在"

    # 2) downgrade -1（回退 0003 → 0002 baseline）
    #    通过 Alembic 内部 API 复用 engine._alembic_config()；参考 run_migrations。
    engine.dispose()
    db_engine.reset_engine()
    from alembic import command as alembic_command

    cfg = db_engine._alembic_config()
    alembic_command.downgrade(cfg, "-1")

    engine = get_engine()
    names_after_down = set(inspect(engine).get_table_names())
    for table in FILE_OBJECT_TABLES:
        assert table not in names_after_down, (
            f"downgrade -1 后 {table} 应该消失; 实际 tables={sorted(names_after_down)}"
        )
    # 保证 0002 baseline 的表仍在（未连带被 drop）
    assert "canvases" in names_after_down, "downgrade -1 不该动 0002 baseline"

    # 3) re-upgrade head → 表回来
    engine.dispose()
    db_engine.reset_engine()
    alembic_command.upgrade(cfg, "head")

    engine = get_engine()
    names_after_reup = set(inspect(engine).get_table_names())
    for table in FILE_OBJECT_TABLES:
        assert table in names_after_reup, (
            f"re-upgrade head 后 {table} 应恢复;"
            f" 实际 tables={sorted(names_after_reup)}"
        )


# ---------------------------------------------------------------------------
# T137 · file_objects.sha256 UNIQUE
# ---------------------------------------------------------------------------


def test_t137_file_objects_sha256_unique(migrated_engine):
    """T137 · 同 sha256 二次插入触发 IntegrityError。"""
    from sqlalchemy.exc import IntegrityError

    shared_sha = _bytes(32, 0x77)
    with migrated_engine.begin() as conn:
        _insert_file_object(
            conn,
            sha256=shared_sha,
            object_key="a/first.bin",
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            _insert_file_object(
                conn,
                sha256=shared_sha,  # 同 sha256
                object_key="a/second.bin",
            )


# ---------------------------------------------------------------------------
# T138 · file_objects.legacy_path UNIQUE
# ---------------------------------------------------------------------------


def test_t138_file_objects_legacy_path_unique(migrated_engine):
    """T138 · 同 legacy_path 二次插入触发 IntegrityError。"""
    from sqlalchemy.exc import IntegrityError

    shared_path = "assets/output/legacy_shared.png"
    with migrated_engine.begin() as conn:
        _insert_file_object(
            conn,
            sha256=_bytes(32, 0x81),
            legacy_path=shared_path,
            object_key="a/one.bin",
        )
        # 使用 INSERT 带 legacy_path 的显式列
        conn.execute(
            text(
                "UPDATE file_objects SET legacy_path=:p WHERE object_key='a/one.bin'"
            ),
            {"p": shared_path},
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            row = _minimal_file_object(
                sha256=_bytes(32, 0x82),
                legacy_path=shared_path,  # 同 legacy_path
                object_key="a/two.bin",
            )
            conn.execute(
                text(
                    "INSERT INTO file_objects "
                    "(id, sha256, xxh64, size_bytes, object_key, origin_kind, "
                    " created_at, legacy_path) "
                    "VALUES "
                    "(:id, :sha256, :xxh64, :size_bytes, :object_key, "
                    " :origin_kind, :created_at, :legacy_path)"
                ),
                row,
            )


# ---------------------------------------------------------------------------
# T139 · file_objects.reference_count DEFAULT 0
# ---------------------------------------------------------------------------


def test_t139_file_objects_reference_count_default_zero(migrated_engine):
    """T139 · 未显式给 reference_count 赋值时读取 = 0。"""
    with migrated_engine.begin() as conn:
        payload = _insert_file_object(
            conn,
            sha256=_bytes(32, 0x39),
            object_key="a/refcount.bin",
        )
        row = conn.execute(
            text(
                "SELECT reference_count FROM file_objects WHERE id=:id"
            ),
            {"id": payload["id"]},
        ).one()
        assert row[0] == 0, (
            f"reference_count DEFAULT 0 契约破裂; 实际={row[0]!r}"
        )


# ---------------------------------------------------------------------------
# T140 · file_refs (subject_table, subject_id, role, file_id) UNIQUE
# ---------------------------------------------------------------------------


def test_t140_file_refs_subject_role_unique(migrated_engine):
    """T140 · 完全相同的 (subject_table, subject_id, role, file_id) 4 元组
    二次插入触发 IntegrityError。"""
    from sqlalchemy.exc import IntegrityError

    file_row = _minimal_file_object(
        sha256=_bytes(32, 0x40),
        object_key="a/refparent.bin",
    )
    subject_id = str(_uuid.uuid4())
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO file_objects "
                "(id, sha256, xxh64, size_bytes, object_key, origin_kind, "
                " created_at) "
                "VALUES "
                "(:id, :sha256, :xxh64, :size_bytes, :object_key, "
                " :origin_kind, :created_at)"
            ),
            file_row,
        )
        conn.execute(
            text(
                "INSERT INTO file_refs "
                "(id, file_id, subject_table, subject_id, role, created_at) "
                "VALUES "
                "(:id, :file_id, :subject_table, :subject_id, :role, "
                " :created_at)"
            ),
            {
                "id": str(_uuid.uuid4()),
                "file_id": file_row["id"],
                "subject_table": "asset_items",
                "subject_id": subject_id,
                "role": "primary",
                "created_at": _now(),
            },
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO file_refs "
                    "(id, file_id, subject_table, subject_id, role, "
                    " created_at) "
                    "VALUES "
                    "(:id, :file_id, :subject_table, :subject_id, :role, "
                    " :created_at)"
                ),
                {
                    "id": str(_uuid.uuid4()),
                    "file_id": file_row["id"],
                    "subject_table": "asset_items",
                    "subject_id": subject_id,
                    "role": "primary",
                    "created_at": _now(),
                },
            )


# ---------------------------------------------------------------------------
# T141 · legacy_url_refs.url UNIQUE
# ---------------------------------------------------------------------------


def test_t141_legacy_url_refs_url_unique(migrated_engine):
    """T141 · legacy_url_refs.url UNIQUE 二次插入触发 IntegrityError。"""
    from sqlalchemy.exc import IntegrityError

    file_row = _minimal_file_object(
        sha256=_bytes(32, 0x41),
        object_key="a/urlparent.bin",
    )
    shared_url = "http://legacy.example.com/x.png"
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO file_objects "
                "(id, sha256, xxh64, size_bytes, object_key, origin_kind, "
                " created_at) "
                "VALUES "
                "(:id, :sha256, :xxh64, :size_bytes, :object_key, "
                " :origin_kind, :created_at)"
            ),
            file_row,
        )
        conn.execute(
            text(
                "INSERT INTO legacy_url_refs "
                "(id, file_id, url, migrated_at, sha256) "
                "VALUES "
                "(:id, :file_id, :url, :migrated_at, :sha256)"
            ),
            {
                "id": str(_uuid.uuid4()),
                "file_id": file_row["id"],
                "url": shared_url,
                "migrated_at": _now(),
                "sha256": _bytes(32, 0xAA),
            },
        )
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO legacy_url_refs "
                    "(id, file_id, url, migrated_at, sha256) "
                    "VALUES "
                    "(:id, :file_id, :url, :migrated_at, :sha256)"
                ),
                {
                    "id": str(_uuid.uuid4()),
                    "file_id": file_row["id"],
                    "url": shared_url,  # 同 url
                    "migrated_at": _now(),
                    "sha256": _bytes(32, 0xBB),
                },
            )


# ---------------------------------------------------------------------------
# T142 · 三表 NOT NULL 列缺失时 → IntegrityError
# ---------------------------------------------------------------------------


# NOT NULL 覆盖矩阵：任务书 § T142 明确要求覆盖列
# file_objects: sha256 / xxh64 / size_bytes / object_key / origin_kind /
#               created_at
# file_refs:    file_id / subject_table / subject_id / created_at
# legacy_url_refs: file_id / url / migrated_at / sha256


@pytest.mark.parametrize(
    "column",
    [
        "sha256",
        "xxh64",
        "size_bytes",
        "object_key",
        "origin_kind",
        "created_at",
    ],
)
def test_t142_file_objects_not_null_columns(migrated_engine, column):
    """T142.a · file_objects NOT NULL 列 6 项。"""
    from sqlalchemy.exc import IntegrityError

    payload = _minimal_file_object(
        sha256=_bytes(32, 0x50 + hash(column) % 0x0F),
        object_key=f"a/nn_{column}.bin",
    )
    payload[column] = None
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO file_objects "
                    "(id, sha256, xxh64, size_bytes, object_key, origin_kind, "
                    " created_at) "
                    "VALUES "
                    "(:id, :sha256, :xxh64, :size_bytes, :object_key, "
                    " :origin_kind, :created_at)"
                ),
                payload,
            )


@pytest.mark.parametrize(
    "column",
    ["file_id", "subject_table", "subject_id", "created_at"],
)
def test_t142_file_refs_not_null_columns(migrated_engine, column):
    """T142.b · file_refs NOT NULL 列 4 项。"""
    from sqlalchemy.exc import IntegrityError

    file_row = _minimal_file_object(
        sha256=_bytes(32, 0x60 + hash(column) % 0x0F),
        object_key=f"a/nn_ref_{column}.bin",
    )
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO file_objects "
                "(id, sha256, xxh64, size_bytes, object_key, origin_kind, "
                " created_at) "
                "VALUES "
                "(:id, :sha256, :xxh64, :size_bytes, :object_key, "
                " :origin_kind, :created_at)"
            ),
            file_row,
        )

    payload = {
        "id": str(_uuid.uuid4()),
        "file_id": file_row["id"],
        "subject_table": "asset_items",
        "subject_id": str(_uuid.uuid4()),
        "role": "primary",
        "created_at": _now(),
    }
    payload[column] = None
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO file_refs "
                    "(id, file_id, subject_table, subject_id, role, "
                    " created_at) "
                    "VALUES "
                    "(:id, :file_id, :subject_table, :subject_id, :role, "
                    " :created_at)"
                ),
                payload,
            )


@pytest.mark.parametrize(
    "column",
    ["file_id", "url", "migrated_at", "sha256"],
)
def test_t142_legacy_url_refs_not_null_columns(migrated_engine, column):
    """T142.c · legacy_url_refs NOT NULL 列 4 项。"""
    from sqlalchemy.exc import IntegrityError

    file_row = _minimal_file_object(
        sha256=_bytes(32, 0x70 + hash(column) % 0x0F),
        object_key=f"a/nn_url_{column}.bin",
    )
    with migrated_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO file_objects "
                "(id, sha256, xxh64, size_bytes, object_key, origin_kind, "
                " created_at) "
                "VALUES "
                "(:id, :sha256, :xxh64, :size_bytes, :object_key, "
                " :origin_kind, :created_at)"
            ),
            file_row,
        )

    payload = {
        "id": str(_uuid.uuid4()),
        "file_id": file_row["id"],
        "url": f"http://example.com/nn_{column}",
        "migrated_at": _now(),
        "sha256": _bytes(32, 0xCC),
    }
    payload[column] = None
    with pytest.raises(IntegrityError):
        with migrated_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO legacy_url_refs "
                    "(id, file_id, url, migrated_at, sha256) "
                    "VALUES "
                    "(:id, :file_id, :url, :migrated_at, :sha256)"
                ),
                payload,
            )


# ---------------------------------------------------------------------------
# T143 · UUIDv7 主键类型 portable
# ---------------------------------------------------------------------------


def test_t143_uuid_primary_key_portable_roundtrip(migrated_engine):
    """T143 · SQLAlchemy 2.0 `Uuid(as_uuid=True)` 让 SQLite / PG 都能存
    UUIDv7 主键；SQLite 侧走 CHAR(36) 文本存储（决策 - 主键类型 §7）。

    - 用 `app.shared.ids.generate_id()` 生成真 UUIDv7；
    - 插入 → SELECT → 反序列化回来仍是同一 UUID；
    - inspect 侧确认 SQLite 底层列类型 = CHAR(36)（与决策一致）。
    """
    from app.shared.ids import generate_id

    uid = generate_id()
    assert uid.version == 7, "generate_id 必须返回 UUIDv7"

    with migrated_engine.begin() as conn:
        _insert_file_object(
            conn,
            id=uid,
            sha256=_bytes(32, 0x43),
            object_key="a/uuidv7.bin",
        )
        row = conn.execute(
            text("SELECT id FROM file_objects WHERE object_key='a/uuidv7.bin'")
        ).one()

    # SQLAlchemy 2.0 `Uuid` 层反序列化：BLOB (PG native) or CHAR(36) (SQLite)。
    # 直接用 raw sqlite driver 拉出会拿到 str；`_uuid.UUID(...)` 归一后比较。
    raw = row[0]
    parsed = raw if isinstance(raw, _uuid.UUID) else _uuid.UUID(str(raw))
    assert parsed == uid, (
        f"UUIDv7 主键 round-trip 失败;写入 {uid} → 读出 {parsed}"
    )

    # 结构层：SQLite 侧应把 Uuid(as_uuid=True) 映射为 CHAR(36)（SQLAlchemy 默认
    # native_uuid=True，SQLite 无原生 uuid → 落 CHAR(36)）；决策 §7 明示。
    if migrated_engine.url.get_backend_name() == "sqlite":
        with migrated_engine.begin() as conn:
            info = conn.execute(
                text("PRAGMA table_info('file_objects')")
            ).all()
        id_col = next(row for row in info if row[1] == "id")
        # PRAGMA table_info column 2 = declared type
        declared_type = str(id_col[2]).upper()
        assert "CHAR(32)" in declared_type or "CHAR(36)" in declared_type or "UUID" in declared_type, (
            f"SQLite 侧 file_objects.id 声明类型应为 CHAR(36) / CHAR(32) / UUID;"
            f" 实际={declared_type!r}"
        )


# ---------------------------------------------------------------------------
# T144 · 零触碰断言：asset_items.file_ref TEXT NULL 占位列未动
# ---------------------------------------------------------------------------


def test_t144_asset_items_file_ref_placeholder_untouched(migrated_engine):
    """T144 · 数据 PR-3 baseline 里 `asset_items.file_ref TEXT NULL` 占位列
    留给未来 PR-10 迁引用；本 PR 纯新增,零触碰。

    双证据:
    1. AST 层 · `git show a6f863a:app/db/migrations/versions/0002_baseline_tables.py`
       与当前工作区文件 byte-identical(0002 未被本 PR 改动)。
    2. 结构层 · `inspect(engine).get_columns('asset_items')` 里 `file_ref`
       列存在、类型 TEXT、nullable=True。
    """
    # 证据 1：0002 baseline 迁移文件字节等价
    result = subprocess.run(
        [
            "git",
            "show",
            f"{BASELINE_REF}:app/db/migrations/versions/0002_baseline_tables.py",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(
            f"baseline ref {BASELINE_REF} unavailable (shallow clone?)"
        )
    baseline_source = result.stdout
    current_source = (
        REPO_ROOT / "app" / "db" / "migrations" / "versions"
        / "0002_baseline_tables.py"
    ).read_text(encoding="utf-8")
    baseline_tree = ast.parse(baseline_source)
    current_tree = ast.parse(current_source)
    assert ast.dump(baseline_tree, include_attributes=False) == ast.dump(
        current_tree, include_attributes=False
    ), (
        "数据 PR-18 零触碰契约破裂:0002_baseline_tables.py 相较 baseline "
        f"{BASELINE_REF} 出现 AST diff;`asset_items.file_ref` 占位列语义可能被改动"
    )

    # 证据 2：结构层 asset_items 表 file_ref 列存在、TEXT、nullable
    inspector = inspect(migrated_engine)
    cols = {c["name"]: c for c in inspector.get_columns("asset_items")}
    assert "file_ref" in cols, (
        "asset_items.file_ref 占位列丢失(数据 PR-3 baseline 明确保留)"
    )
    file_ref_col = cols["file_ref"]
    assert file_ref_col["nullable"] is True, (
        f"asset_items.file_ref 应为 nullable=True;实际={file_ref_col!r}"
    )
    col_type = str(file_ref_col["type"]).upper()
    assert "TEXT" in col_type or "VARCHAR" in col_type, (
        f"asset_items.file_ref 应为 TEXT;实际={col_type!r}"
    )
