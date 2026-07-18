"""PR-2 shadow-only file registration service.

Legacy writers remain authoritative in this phase. The service hashes an existing
file and atomically records metadata; it never writes file content through the
injected storage adapter.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Callable, Optional

from app.adapters.storage.base import StorageAdapter
from app.shared.ids import generate_id


SCHEMA_VERSION = 1
EVENT_RETENTION_SECONDS = 8 * 24 * 60 * 60
MAX_SHADOW_EVENTS = 10_000
HASH_CHUNK_SIZE = 1024 * 1024
ALLOWED_ORIGINS = {
    "ai_input",
    "ai_output",
    "comfy_output",
    "library_copy",
    "upload",
    "workflow_export",
    "workflow_import",
}
ALLOWED_ERROR_CODES = {
    "background_queue_full",
    "background_start_failed",
    "digest_conflict",
    "invalid_registration",
    "legacy_file_missing",
    "legacy_file_unreadable",
    "registration_error",
    "unknown",
}


class LegacyPathConflictError(RuntimeError):
    """The same legacy path now points at different content."""


@dataclass(frozen=True)
class FileRecord:
    id: str
    sha256: str
    size_bytes: int
    mime_type: Optional[str]
    origin_kind: str
    legacy_path: str
    legacy_url: Optional[str]
    created_at: str


_LOCKS_GUARD = threading.Lock()
_INDEX_LOCKS: dict[str, threading.RLock] = {}


def _thread_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(os.path.abspath(path))
    with _LOCKS_GUARD:
        return _INDEX_LOCKS.setdefault(key, threading.RLock())


class _CrossProcessLock:
    def __init__(self, path: Path, timeout_seconds: float = 10.0) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._acquired = False

    def __enter__(self) -> "_CrossProcessLock":
        deadline = time.monotonic() + self.timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, f"{os.getpid()}\n".encode("ascii"))
                finally:
                    os.close(fd)
                self._acquired = True
                return self
            except FileExistsError:
                if self._is_stale_lock():
                    try:
                        self.path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out waiting for file index lock")
                time.sleep(0.02)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._acquired:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def _is_stale_lock(self) -> bool:
        try:
            stale_by_age = time.time() - self.path.stat().st_mtime > 30.0
        except FileNotFoundError:
            return False
        if not stale_by_age:
            return False
        try:
            raw_pid = self.path.read_text(encoding="ascii").strip()
            pid = int(raw_pid)
        except (OSError, ValueError):
            return True
        if pid <= 0 or pid == os.getpid():
            return True
        if os.name == "nt":
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        except (AttributeError, PermissionError):
            return False
        return False


class FileService:
    def __init__(
        self,
        adapter: StorageAdapter,
        index_path: str | os.PathLike[str],
        *,
        now: Callable[[], float] = time.time,
        max_events: int = MAX_SHADOW_EVENTS,
    ) -> None:
        self.adapter = adapter
        self.index_path = Path(index_path).resolve()
        self.lock_path = Path(f"{self.index_path}.lock")
        self._now = now
        self._max_events = max(1, int(max_events))
        self._lock = _thread_lock(self.index_path)

    def create_from_bytes(
        self,
        data: bytes,
        *,
        legacy_path: str | os.PathLike[str],
        legacy_url: Optional[str] = None,
        origin_kind: str,
        mime_type: Optional[str] = None,
    ) -> FileRecord:
        """Register content already persisted by a legacy writer."""

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data must be bytes-like")
        return self._register_existing(legacy_path, legacy_url, origin_kind, mime_type)

    def create_from_stream(
        self,
        stream: BinaryIO,
        *,
        legacy_path: str | os.PathLike[str],
        legacy_url: Optional[str] = None,
        origin_kind: str,
        mime_type: Optional[str] = None,
    ) -> FileRecord:
        """Register a legacy file without consuming or copying the supplied stream."""

        if not hasattr(stream, "read"):
            raise TypeError("stream must be binary-readable")
        return self._register_existing(legacy_path, legacy_url, origin_kind, mime_type)

    def resolve_by_id(self, file_id: str) -> Optional[FileRecord]:
        with self._lock, _CrossProcessLock(self.lock_path):
            payload = self._read_index()
            raw = payload["files"].get(str(file_id))
            return FileRecord(**raw) if raw else None

    def build_public_url(self, file_id: str) -> Optional[str]:
        record = self.resolve_by_id(file_id)
        if record is None:
            return None
        return record.legacy_url or f"/api/files/{record.id}"

    def stat(self, file_id: str) -> Optional[FileRecord]:
        return self.resolve_by_id(file_id)

    def alignment_summary(self, window_seconds: int = 24 * 60 * 60) -> dict:
        now = self._now()
        cutoff = now - max(0, int(window_seconds))
        with self._lock, _CrossProcessLock(self.lock_path):
            payload = self._read_index()
        events = [event for event in payload["shadow_events"] if float(event.get("timestamp", 0)) >= cutoff]
        attempted = len(events)
        aligned = sum(event.get("status") == "aligned" for event in events)
        failed = attempted - aligned
        by_origin: dict[str, dict[str, int]] = {}
        by_error: dict[str, int] = {}
        for event in events:
            origin = str(event.get("origin") or "unknown")
            bucket = by_origin.setdefault(origin, {"attempted": 0, "aligned": 0, "failed": 0})
            bucket["attempted"] += 1
            bucket["aligned" if event.get("status") == "aligned" else "failed"] += 1
            if event.get("status") != "aligned":
                error = str(event.get("error") or "unknown")
                by_error[error] = by_error.get(error, 0) + 1
        return {
            "recorded_attempts": attempted,
            "recorded_aligned": aligned,
            "recorded_failed": failed,
            "recorded_rate": aligned / attempted if attempted else None,
            "window_seconds": int(window_seconds),
            "by_origin": by_origin,
            "by_error": by_error,
        }

    def record_failure(self, origin_kind: str, error_code: str) -> None:
        """Record a sanitized failed shadow attempt when registration cannot start."""

        now = self._now()
        with self._lock, _CrossProcessLock(self.lock_path):
            payload = self._read_index()
            self._append_event(payload, now, "failed", origin_kind, error_code)
            self._write_index(payload)

    def _register_existing(
        self,
        legacy_path: str | os.PathLike[str],
        legacy_url: Optional[str],
        origin_kind: str,
        mime_type: Optional[str],
    ) -> FileRecord:
        normalized_path = os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(legacy_path))))
        digest, size = self._hash_existing(normalized_path)
        now = self._now()
        with self._lock, _CrossProcessLock(self.lock_path):
            payload = self._read_index()
            existing_id = payload["legacy_path_index"].get(normalized_path)
            if existing_id:
                existing = FileRecord(**payload["files"][existing_id])
                if existing.sha256 != digest or existing.size_bytes != size:
                    self._append_event(payload, now, "failed", origin_kind, "digest_conflict")
                    self._write_index(payload)
                    raise LegacyPathConflictError("legacy path content changed after registration")
                self._append_event(payload, now, "aligned", origin_kind)
                self._write_index(payload)
                return existing

            record = FileRecord(
                id=str(generate_id()),
                sha256=digest,
                size_bytes=size,
                mime_type=mime_type or None,
                origin_kind=self._normalize_origin(origin_kind),
                legacy_path=normalized_path,
                legacy_url=legacy_url or None,
                created_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
            )
            payload["files"][record.id] = asdict(record)
            payload["legacy_path_index"][normalized_path] = record.id
            self._append_event(payload, now, "aligned", record.origin_kind)
            self._write_index(payload)
            return record

    @staticmethod
    def _hash_existing(path: str) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as source:
            while chunk := source.read(HASH_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    def _empty_index(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "files": {}, "legacy_path_index": {}, "shadow_events": []}

    def _read_index(self) -> dict:
        if not self.index_path.exists():
            return self._empty_index()
        with self.index_path.open("r", encoding="utf-8") as source:
            payload = json.load(source)
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported file index schema_version")
        if not isinstance(payload.get("files"), dict) or not isinstance(payload.get("legacy_path_index"), dict) or not isinstance(payload.get("shadow_events"), list):
            raise ValueError("invalid file index shape")
        return payload

    def _append_event(self, payload: dict, now: float, status: str, origin: str, error: Optional[str] = None) -> None:
        cutoff = now - EVENT_RETENTION_SECONDS
        events = [event for event in payload["shadow_events"] if float(event.get("timestamp", 0)) >= cutoff]
        event = {"timestamp": now, "status": status, "origin": self._normalize_origin(origin)}
        if error:
            event["error"] = self._normalize_error(error)
        events.append(event)
        payload["shadow_events"] = events[-self._max_events :]

    @staticmethod
    def _normalize_origin(origin: str) -> str:
        value = str(origin or "unknown").strip().lower()
        return value if value in ALLOWED_ORIGINS else "unknown"

    @staticmethod
    def _normalize_error(error: str) -> str:
        value = str(error or "unknown").strip().lower()
        return value if value in ALLOWED_ERROR_CODES else "registration_error"

    def _write_index(self, payload: dict) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.index_path.name}.", suffix=".tmp", dir=self.index_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as target:
                json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_name, self.index_path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
