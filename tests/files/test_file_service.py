from __future__ import annotations

import io
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import pytest

from app.adapters.storage.base import StorageAdapter
from app.services.files.file_service import (
    EVENT_RETENTION_SECONDS,
    FileRecord,
    FileService,
    LegacyPathConflictError,
)


def service(tmp_path, **kwargs):
    adapter = MagicMock(spec=StorageAdapter)
    return FileService(adapter, tmp_path / "file_index.json", **kwargs), adapter


def test_interface_registers_existing_bytes_without_adapter_write(tmp_path):
    target = tmp_path / "legacy.bin"
    target.write_bytes(b"legacy-authoritative")
    subject, adapter = service(tmp_path)

    record = subject.create_from_bytes(
        b"deliberately-different-input",
        legacy_path=target,
        legacy_url="/assets/legacy.bin",
        origin_kind="upload",
        mime_type="application/octet-stream",
    )

    assert record.size_bytes == len(b"legacy-authoritative")
    assert subject.resolve_by_id(record.id) == record
    assert subject.stat(record.id) == record
    assert subject.build_public_url(record.id) == "/assets/legacy.bin"
    assert subject.resolve_by_id(str(uuid.uuid4())) is None
    assert subject.build_public_url(str(uuid.uuid4())) is None
    adapter.put.assert_not_called()
    adapter.open_writable_stream.assert_not_called()


def test_stream_is_not_consumed_and_file_record_is_frozen(tmp_path):
    target = tmp_path / "stream.bin"
    target.write_bytes(b"on-disk")
    subject, _ = service(tmp_path)
    supplied = io.BytesIO(b"not-on-disk")

    record = subject.create_from_stream(supplied, legacy_path=target, origin_kind="ai_output")

    assert supplied.tell() == 0
    with pytest.raises(FrozenInstanceError):
        record.size_bytes = 0


def test_normalized_path_is_idempotent_and_conflict_preserves_old_record(tmp_path):
    target = tmp_path / "nested" / "same.bin"
    target.parent.mkdir()
    target.write_bytes(b"one")
    subject, _ = service(tmp_path)

    first = subject.create_from_bytes(b"ignored", legacy_path=target, origin_kind="upload")
    second = subject.create_from_bytes(b"ignored", legacy_path=target.parent / "." / target.name, origin_kind="upload")
    assert second.id == first.id

    target.write_bytes(b"two")
    with pytest.raises(LegacyPathConflictError):
        subject.create_from_bytes(b"ignored", legacy_path=target, origin_kind="upload")

    payload = json.loads((tmp_path / "file_index.json").read_text(encoding="utf-8"))
    assert len(payload["files"]) == 1
    assert payload["files"][first.id]["sha256"] == first.sha256
    assert payload["shadow_events"][-1]["error"] == "digest_conflict"


def test_cross_thread_registration_keeps_one_record_and_valid_json(tmp_path):
    target = tmp_path / "concurrent.bin"
    target.write_bytes(os.urandom(128 * 1024))
    subject, _ = service(tmp_path, max_events=100)

    def register(_):
        return subject.create_from_bytes(b"", legacy_path=target, origin_kind="upload").id

    with ThreadPoolExecutor(max_workers=12) as pool:
        ids = list(pool.map(register, range(40)))

    assert len(set(ids)) == 1
    payload = json.loads((tmp_path / "file_index.json").read_text(encoding="utf-8"))
    assert len(payload["files"]) == 1
    assert len(payload["shadow_events"]) == 40


def test_atomic_replace_failure_leaves_previous_index_intact(tmp_path, monkeypatch):
    target = tmp_path / "atomic.bin"
    target.write_bytes(b"first")
    subject, _ = service(tmp_path)
    record = subject.create_from_bytes(b"", legacy_path=target, origin_kind="upload")
    before = (tmp_path / "file_index.json").read_bytes()

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr("app.services.files.file_service.os.replace", fail_replace)
    with pytest.raises(OSError):
        subject.create_from_bytes(b"", legacy_path=target, origin_kind="upload")

    assert (tmp_path / "file_index.json").read_bytes() == before
    assert FileRecord(**json.loads(before)["files"][record.id]) == record
    assert not list(tmp_path.glob("*.tmp"))


def test_events_are_pruned_after_eight_days_and_capped(tmp_path):
    clock = [1_700_000_000.0]
    target = tmp_path / "prune.bin"
    target.write_bytes(b"same")
    subject, _ = service(tmp_path, now=lambda: clock[0], max_events=3)

    for _ in range(4):
        subject.create_from_bytes(b"", legacy_path=target, origin_kind="upload")
    payload = json.loads((tmp_path / "file_index.json").read_text(encoding="utf-8"))
    assert len(payload["shadow_events"]) == 3

    clock[0] += EVENT_RETENTION_SECONDS + 1
    subject.create_from_bytes(b"", legacy_path=target, origin_kind="upload")
    payload = json.loads((tmp_path / "file_index.json").read_text(encoding="utf-8"))
    assert len(payload["shadow_events"]) == 1


def test_alignment_summary_aggregates_only_sanitized_dimensions(tmp_path):
    target = tmp_path / "summary.bin"
    target.write_bytes(b"ok")
    subject, _ = service(tmp_path)
    subject.create_from_bytes(b"", legacy_path=target, legacy_url="/secret/url", origin_kind="upload")
    subject.record_failure("ai_output", "registration_error")

    summary = subject.alignment_summary()

    assert summary["recorded_attempts"] == 2
    assert summary["recorded_aligned"] == 1
    assert summary["recorded_failed"] == 1
    assert summary["recorded_rate"] == 0.5
    assert summary["by_error"] == {"registration_error": 1}
    serialized = json.dumps(summary)
    assert str(target) not in serialized
    assert "/secret/url" not in serialized


def test_alignment_summary_normalizes_origin_and_error_codes(tmp_path):
    subject, _ = service(tmp_path)

    subject.record_failure("C:/secret/path.png", "raw exception with /secret/url")

    summary = subject.alignment_summary()
    assert summary["by_origin"] == {"unknown": {"attempted": 1, "aligned": 0, "failed": 1}}
    assert summary["by_error"] == {"registration_error": 1}
    assert "secret" not in json.dumps(summary)
