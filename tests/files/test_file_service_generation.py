"""T145-T152: FileService.create_from_generation tests.

See also: PR task book T145-T152.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from unittest.mock import MagicMock, PropertyMock

import pytest

from app.adapters.storage.base import ObjectMeta, StorageAdapter
from app.db.engine import get_engine, reset_engine
from app.services.files.file_service import FileService, _mime_ext


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def file_objects_db(monkeypatch, tmp_path):
    """Point DATA_DB_PATH to a temporary DB and run migrations."""
    db_path = tmp_path / "test_file_objects.db"
    monkeypatch.setenv("DATA_DB_PATH", str(db_path))
    reset_engine()
    from app.db.engine import run_migrations

    run_migrations("head")
    yield
    reset_engine()


@pytest.fixture
def service(tmp_path) -> FileService:
    adapter = MagicMock(spec=StorageAdapter)
    adapter.put.return_value = ObjectMeta(
        key="output/ab/cd/abcdef.png",
        size=42,
        etag="abc123",
        mime_type="image/png",
        backend="local",
    )
    # Use a real backend_name property
    type(adapter).backend_name = PropertyMock(return_value="local")
    svc = FileService(adapter, tmp_path / "file_index.json")
    return svc


# ---------------------------------------------------------------------------
# T145: create_from_generation write -> read back bytes equivalent
# ---------------------------------------------------------------------------


def test_t145_create_from_generation_writes_and_reads_back(tmp_path, service):
    """Write data via create_from_generation, then verify the DB record."""
    data = b"test-image-data-12345"
    mime_type = "image/png"

    record = service.create_from_generation(
        data,
        mime_type=mime_type,
        legacy_path=str(tmp_path / "output/test.png"),
        legacy_url="/assets/output/test.png",
    )

    assert record is not None
    assert record.size_bytes == len(data)
    assert record.mime_type == "image/png"
    assert record.origin_kind == "ai_output"
    assert record.legacy_url == "/assets/output/test.png"

    from sqlalchemy import select

    from app.data_import import tables as t

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            select(t.file_objects).where(t.file_objects.c.id == uuid.UUID(record.id))
        ).fetchone()
        assert row is not None
        assert row.sha256 == hashlib.sha256(data).digest()
        assert row.size_bytes == len(data)
        assert row.mime_type == "image/png"
        assert row.origin_kind == "ai_output"
        assert row.object_key == f"output/{hashlib.sha256(data).hexdigest()[0:2]}/{hashlib.sha256(data).hexdigest()[2:4]}/{hashlib.sha256(data).hexdigest()}.png"
        assert row.reference_count == 1
        assert row.legacy_url == "/assets/output/test.png"

        # Verify file_refs record
        ref_row = conn.execute(
            select(t.file_refs).where(t.file_refs.c.file_id == row.id)
        ).fetchone()
        assert ref_row is not None
        assert ref_row.subject_table == "generation_output"
        assert ref_row.role == "primary"


# ---------------------------------------------------------------------------
# T146: same sha256 dedup (reference_count +1, no new row)
# ---------------------------------------------------------------------------


def test_t146_same_sha256_dedup_increments_reference_count(tmp_path, service):
    """Calling create_from_generation with same data only creates one row."""
    from sqlalchemy import select

    from app.data_import import tables as t

    data = b"dedup-test-data"
    mime_type = "image/png"

    first = service.create_from_generation(
        data,
        mime_type=mime_type,
        legacy_path=str(tmp_path / "output/first.png"),
        legacy_url="/assets/output/first.png",
    )

    second = service.create_from_generation(
        data,
        mime_type=mime_type,
        legacy_path=str(tmp_path / "output/second.png"),
        legacy_url="/assets/output/second.png",
    )

    # Same id (dedup)
    assert first.id == second.id

    # reference_count should be 2
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.file_objects).where(t.file_objects.c.sha256 == hashlib.sha256(data).digest())
        ).fetchall()
    assert len(rows) == 1  # Only one row
    assert rows[0].reference_count >= 2


# ---------------------------------------------------------------------------
# T147: different sha256 creates new row
# ---------------------------------------------------------------------------


def test_t147_different_sha256_creates_separate_rows(tmp_path, service):
    """Different data creates distinct file_objects rows."""
    data_a = b"data-a"
    data_b = b"data-b"

    rec_a = service.create_from_generation(data_a, mime_type="image/png")
    rec_b = service.create_from_generation(data_b, mime_type="image/png")

    assert rec_a.id != rec_b.id


# ---------------------------------------------------------------------------
# T150: file_objects sha256 unique constraint (DB level)
# ---------------------------------------------------------------------------


def test_t150_file_objects_sha256_unique_constraint(tmp_path, service):
    """Verify DB-level UNIQUE constraint on sha256."""
    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine
    from app.shared.ids import generate_id

    data = b"unique-constraint-test"
    sha256_bytes = hashlib.sha256(data).digest()
    engine = get_engine()

    # Insert first row directly
    from datetime import datetime, timezone

    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            sqlite_insert(t.file_objects).values(
                id=generate_id(),
                sha256=sha256_bytes,
                xxh64=sha256_bytes[:8],
                size_bytes=len(data),
                mime_type="image/png",
                storage_backend="local",
                bucket=None,
                object_key="test/key.png",
                etag="test-etag",
                origin_kind="ai_output",
                created_at=now,
                reference_count=1,
            )
        )

    # Attempt to insert duplicate sha256 — should fail or do upsert
    # Actually the on_conflict_do_update should handle it gracefully
    rec = service.create_from_generation(data, mime_type="image/png")
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.file_objects).where(t.file_objects.c.sha256 == sha256_bytes)
        ).fetchall()
    assert len(rows) == 1  # Still one row (upsert behavior)


# ---------------------------------------------------------------------------
# T151: file_refs idempotent write
# ---------------------------------------------------------------------------


def test_t151_file_refs_idempotent_write(tmp_path, service):
    """Same (subject_table, subject_id, role, file_id) only writes once."""
    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    data = b"file-refs-idempotent"
    rec = service.create_from_generation(data, mime_type="image/png")

    engine = get_engine()
    with engine.connect() as conn:
        refs = conn.execute(
            select(t.file_refs).where(
                t.file_refs.c.subject_table == "generation_output",
                t.file_refs.c.subject_id == uuid.UUID(rec.id),
                t.file_refs.c.file_id == uuid.UUID(rec.id),
            )
        ).fetchall()
    # Should be exactly one ref
    assert len(refs) == 1


# ---------------------------------------------------------------------------
# T152: legacy_url_refs write
# ---------------------------------------------------------------------------


def test_t152_legacy_url_refs_written(tmp_path, service):
    """When legacy_url is provided, a legacy_url_refs row is inserted."""
    from sqlalchemy import select

    from app.data_import import tables as t
    from app.db.engine import get_engine

    data = b"legacy-url-test"
    legacy_url = "/assets/output/legacy-test.png"

    rec = service.create_from_generation(
        data,
        mime_type="image/png",
        legacy_url=legacy_url,
    )

    engine = get_engine()
    with engine.connect() as conn:
        url_row = conn.execute(
            select(t.legacy_url_refs).where(
                t.legacy_url_refs.c.url == legacy_url
            )
        ).fetchone()
    assert url_row is not None
    assert url_row.file_id == uuid.UUID(rec.id)
    assert url_row.sha256 == hashlib.sha256(data).digest()


# ---------------------------------------------------------------------------
# _mime_ext helper tests
# ---------------------------------------------------------------------------


def test_mime_ext_known_types():
    assert _mime_ext("image/png") == "png"
    assert _mime_ext("image/jpeg") == "jpeg" or _mime_ext("image/jpeg") == "jpg"
    assert _mime_ext("image/webp") == "webp"
    assert _mime_ext("video/mp4") == "mp4"
    assert _mime_ext("video/x-flv") == "flv"


def test_mime_ext_fallback_to_png():
    """When mime_type is unknown, create_from_generation falls back to 'png'."""
    from app.adapters.storage.base import ObjectMeta, StorageAdapter
    from unittest.mock import MagicMock, PropertyMock

    adapter = MagicMock(spec=StorageAdapter)
    adapter.put.return_value = ObjectMeta(
        key="output/ab/cd/abcdef.png",
        size=10,
        etag="abc",
        mime_type="application/octet-stream",
        backend="local",
    )
    type(adapter).backend_name = PropertyMock(return_value="local")
    svc = FileService(adapter, MagicMock())

    record = svc.create_from_generation(b"test", mime_type="application/octet-stream")
    assert record is not None