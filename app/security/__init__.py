"""`app.security` — 部署与安全治理专题骨架包。

**定位**:安全护栏纯函数库。每个子模块提供 dataclass + 纯检查函数,
以 `is_*_enforce_enabled()` 判据 + env flag 默认关闭(与旧行为等价)。

**当前骨架成员**(Wave 3-N.8 Batch 5):

- ``upload_guard``:上传大小 / MIME / 双扩展名 / SVG 拒绝(部署 PR-03)
- ``zip_guard``:zip bomb / 路径穿越 / 符号链接防护(部署 PR-04)
- ``pillow_guard``:Pillow ``MAX_IMAGE_PIXELS`` / 内存预估(部署 PR-05)

**分层交付原则**:骨架层只暴露纯函数与决策结果对象;
生产切换(挂 middleware / 装饰路由)归后续 PR 承接。

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] M1 · 骨架层三 PR 合交付。
"""
from __future__ import annotations

from app.security.upload_guard import (
    DEFAULT_UPLOAD_POLICY,
    UPLOAD_GUARD_ENFORCE_ENV,
    UploadDecision,
    UploadGuardPolicy,
    UploadReason,
    check_upload,
    guess_mime_from_magic,
    is_upload_guard_enforce_enabled,
)
from app.security.zip_guard import (
    DEFAULT_ZIP_POLICY,
    ZIP_GUARD_ENFORCE_ENV,
    ZipDecision,
    ZipEntryMeta,
    ZipGuardPolicy,
    ZipReason,
    inspect_zip_entries,
    is_zip_guard_enforce_enabled,
    normalize_zip_entry_path,
)
from app.security.pillow_guard import (
    DEFAULT_PILLOW_POLICY,
    PILLOW_GUARD_ENFORCE_ENV,
    PillowDecision,
    PillowGuardPolicy,
    PillowReason,
    check_image_dimensions,
    estimate_pixel_bytes,
    is_pillow_guard_enforce_enabled,
)
from app.security.cors import (
    CORS_MODE_AWARE_ENABLED_ENV,
    CorsPolicy,
    DEFAULT_CORS_POLICY,
    DeploymentMode,
    build_cors_policy,
    is_cors_mode_aware_enabled,
    parse_allowed_origins,
)

__all__ = [
    # upload_guard
    "UPLOAD_GUARD_ENFORCE_ENV",
    "UploadGuardPolicy",
    "UploadDecision",
    "UploadReason",
    "DEFAULT_UPLOAD_POLICY",
    "check_upload",
    "guess_mime_from_magic",
    "is_upload_guard_enforce_enabled",
    # zip_guard
    "ZIP_GUARD_ENFORCE_ENV",
    "ZipGuardPolicy",
    "ZipDecision",
    "ZipEntryMeta",
    "ZipReason",
    "DEFAULT_ZIP_POLICY",
    "inspect_zip_entries",
    "is_zip_guard_enforce_enabled",
    "normalize_zip_entry_path",
    # pillow_guard
    "PILLOW_GUARD_ENFORCE_ENV",
    "PillowGuardPolicy",
    "PillowDecision",
    "PillowReason",
    "DEFAULT_PILLOW_POLICY",
    "check_image_dimensions",
    "estimate_pixel_bytes",
    "is_pillow_guard_enforce_enabled",
    # cors
    "CORS_MODE_AWARE_ENABLED_ENV",
    "CorsPolicy",
    "DEFAULT_CORS_POLICY",
    "DeploymentMode",
    "build_cors_policy",
    "is_cors_mode_aware_enabled",
    "parse_allowed_origins",
]
