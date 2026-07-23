"""File object service facade."""

from .file_service import FileRecord, FileService, LegacyPathConflictError
from .validation import (
    MAGIC_ALLOWED_KINDS,
    MAX_ARCHIVE_ENTRIES,
    MAX_ARCHIVE_UNPACK_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_SINGLE_UNPACK_BYTES,
    MAX_UPLOAD_BYTES,
    UploadRejected,
    detect_magic_kind,
    guard_to_http_status,
    guard_upload_bytes,
    validate_archive_limits,
    validate_image_pixels,
    validate_magic_whitelist,
    validate_upload_size,
)

__all__ = [
    "FileRecord",
    "FileService",
    "LegacyPathConflictError",
    "MAGIC_ALLOWED_KINDS",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_ARCHIVE_UNPACK_BYTES",
    "MAX_IMAGE_PIXELS",
    "MAX_SINGLE_UNPACK_BYTES",
    "MAX_UPLOAD_BYTES",
    "UploadRejected",
    "detect_magic_kind",
    "guard_to_http_status",
    "guard_upload_bytes",
    "validate_archive_limits",
    "validate_image_pixels",
    "validate_magic_whitelist",
    "validate_upload_size",
]
