"""`app.security.upload_guard` — 上传安全护栏(部署 PR-03 骨架层)。

**定位**:纯函数 + frozen dataclass 决策对象 · env flag 默认关闭 · 与旧行为等价。

**骨架契约**:
- ``UploadGuardPolicy``:每类上传上限(image / video / zip / generic)
- ``UploadDecision``:结果 frozen dataclass(``accepted`` / ``reason`` / ``matched_mime``)
- ``UploadReason``:拒绝原因 Literal 枚举(6 值)
- ``guess_mime_from_magic(head_bytes)``:签名回退 MIME 判断(离线 · 纯 Python)
- ``check_upload(...)``:主入口 · 返回 ``UploadDecision``
- ``is_upload_guard_enforce_enabled()``:env flag ``UPLOAD_GUARD_ENFORCE`` 判据

**默认宽松策略**(与治理方案 M1 `local_personal` 对齐):
- image: 200 MB
- video: 500 MB
- zip: 200 MB
- generic: 200 MB
- SVG 默认拒绝(骨架 flag off 时不 enforce · 返回 reason=svg_disabled 供上层决策)

**不做**:
- 不接入 ``/api/upload*`` / ``/api/asset-library/*`` 等路由(生产切换归后续 PR)
- 不接入 audit(``file.upload.rejected`` 归 PR-11)
- 不引入 ``python-magic``(离线签名回退表 + Content-Type 双检)
- 不做病毒扫描

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] PR-03。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple


# ---------------------------------------------------------------------------
# env flag
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})

UPLOAD_GUARD_ENFORCE_ENV = "UPLOAD_GUARD_ENFORCE"


def is_upload_guard_enforce_enabled() -> bool:
    """``UPLOAD_GUARD_ENFORCE`` 是否已开启(默认 false)。

    骨架层只暴露判据;实际接入点由生产 PR 消费此判据决定是否拒绝请求。
    """
    return os.environ.get(UPLOAD_GUARD_ENFORCE_ENV, "").strip() in _TRUTHY


# ---------------------------------------------------------------------------
# Reason 枚举 & 决策对象
# ---------------------------------------------------------------------------

UploadReason = Literal[
    "accepted",
    "oversize",
    "mime_mismatch",
    "ext_double",
    "svg_disabled",
    "magic_unknown",
    "ext_disallowed",
]


@dataclass(frozen=True)
class UploadDecision:
    """上传护栏决策结果 · frozen。

    Attributes:
        accepted: 是否通过。
        reason: 拒绝原因(accepted=True 时为 ``"accepted"``)。
        matched_mime: 从 magic bytes 推断的 MIME(可选)。
        detected_size: 实际字节数。
        limit_bytes: 匹配的类别上限(用于 error message)。
    """

    accepted: bool
    reason: UploadReason
    matched_mime: Optional[str] = None
    detected_size: Optional[int] = None
    limit_bytes: Optional[int] = None


# ---------------------------------------------------------------------------
# 策略 dataclass
# ---------------------------------------------------------------------------

# 双扩展名黑名单 · 出现即拒绝
_DOUBLE_EXT_PATTERNS: Tuple[str, ...] = (
    ".jpg.exe", ".png.exe", ".gif.exe", ".jpeg.exe",
    ".zip.exe", ".rar.exe", ".7z.exe",
    ".png.svg", ".jpg.svg",
    ".pdf.exe", ".doc.exe", ".xls.exe",
    ".php.jpg", ".php.png", ".jsp.jpg", ".asp.jpg",
    ".html.exe", ".htm.exe",
)


@dataclass(frozen=True)
class UploadGuardPolicy:
    """上传护栏策略 · frozen dataclass。

    默认上限对齐 `local_personal` 宽松 policy(治理方案 M1 明示等价原行为)。
    生产 PR 通过 Settings 覆盖。
    """

    image_max_bytes: int = 200 * 1024 * 1024
    video_max_bytes: int = 500 * 1024 * 1024
    zip_max_bytes: int = 200 * 1024 * 1024
    generic_max_bytes: int = 200 * 1024 * 1024
    allow_svg: bool = False
    # image MIME 白名单
    allowed_image_mimes: Tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
    )
    allowed_video_mimes: Tuple[str, ...] = (
        "video/mp4",
        "video/quicktime",
        "video/webm",
    )
    allowed_zip_mimes: Tuple[str, ...] = (
        "application/zip",
        "application/x-zip-compressed",
    )


DEFAULT_UPLOAD_POLICY = UploadGuardPolicy()


# ---------------------------------------------------------------------------
# magic bytes 签名回退表(手写 · 离线可用)
# ---------------------------------------------------------------------------

# (prefix_bytes, matched_mime, category)
_MAGIC_SIGNATURES: Tuple[Tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg", "image"),
    (b"\x89PNG\r\n\x1a\n", "image/png", "image"),
    (b"GIF87a", "image/gif", "image"),
    (b"GIF89a", "image/gif", "image"),
    (b"BM", "image/bmp", "image"),
    (b"II*\x00", "image/tiff", "image"),
    (b"MM\x00*", "image/tiff", "image"),
    (b"RIFF", "image/webp", "image"),  # WEBP 需二次校验 · 骨架层放行
    (b"PK\x03\x04", "application/zip", "zip"),
    (b"PK\x05\x06", "application/zip", "zip"),  # 空 zip
    (b"PK\x07\x08", "application/zip", "zip"),  # 分卷
    (b"\x00\x00\x00\x18ftypmp4", "video/mp4", "video"),
    (b"\x00\x00\x00\x20ftypisom", "video/mp4", "video"),
    (b"\x00\x00\x00\x1cftyp", "video/mp4", "video"),
)


def guess_mime_from_magic(head_bytes: bytes) -> Optional[Tuple[str, str]]:
    """从文件头字节推断 MIME + 大类。

    Returns:
        ``(mime, category)`` 元组 · 例如 ``("image/jpeg", "image")``;
        无法识别时返回 ``None``。

    Args:
        head_bytes: 至少 16 字节的文件头(不足亦可 · 短前缀部分命中即返回)。
    """
    if not head_bytes:
        return None

    for prefix, mime, category in _MAGIC_SIGNATURES:
        if head_bytes.startswith(prefix):
            return (mime, category)

    # mp4 变体 · box header 在偏移 4 位置
    if len(head_bytes) >= 12 and head_bytes[4:8] == b"ftyp":
        return ("video/mp4", "video")

    # SVG 侦测(XML/text 前缀)· 用于返回 svg_disabled reason
    head_text = head_bytes[:512].lstrip()
    if head_text.startswith(b"<?xml") or head_text.startswith(b"<svg"):
        return ("image/svg+xml", "svg")

    return None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def _has_double_extension(filename: str) -> bool:
    """检测文件名是否命中双扩展名黑名单(大小写不敏感)。"""
    low = filename.lower()
    return any(pat in low for pat in _DOUBLE_EXT_PATTERNS)


def check_upload(
    *,
    filename: str,
    size: int,
    head_bytes: bytes,
    declared_mime: Optional[str] = None,
    policy: UploadGuardPolicy = DEFAULT_UPLOAD_POLICY,
) -> UploadDecision:
    """上传安全护栏主检查 · 纯函数 · 无副作用。

    检查顺序:
        1. 双扩展名黑名单 → ``ext_double``
        2. magic bytes 识别 → 若不识别 → ``magic_unknown``
        3. SVG 且 ``policy.allow_svg=False`` → ``svg_disabled``
        4. declared_mime 与 magic 大类冲突 → ``mime_mismatch``
        5. 按大类应用 size 上限 → ``oversize``
        6. 均通过 → ``accepted``

    Args:
        filename: 上传文件名(仅用于扩展名判断)。
        size: 实际字节数。
        head_bytes: 至少前 16 字节。
        declared_mime: 客户端声明的 Content-Type(可选 · None 时跳过一致性检查)。
        policy: 策略;缺省 ``DEFAULT_UPLOAD_POLICY``。

    Returns:
        ``UploadDecision``。
    """
    if _has_double_extension(filename):
        return UploadDecision(
            accepted=False,
            reason="ext_double",
            detected_size=size,
        )

    match = guess_mime_from_magic(head_bytes)
    if match is None:
        return UploadDecision(
            accepted=False,
            reason="magic_unknown",
            detected_size=size,
        )

    matched_mime, category = match

    if category == "svg" and not policy.allow_svg:
        return UploadDecision(
            accepted=False,
            reason="svg_disabled",
            matched_mime=matched_mime,
            detected_size=size,
        )

    # declared_mime 与 magic 大类冲突(粗粒度)
    if declared_mime:
        declared_low = declared_mime.lower().split(";")[0].strip()
        if category == "image" and not declared_low.startswith("image/"):
            return UploadDecision(
                accepted=False,
                reason="mime_mismatch",
                matched_mime=matched_mime,
                detected_size=size,
            )
        if category == "video" and not declared_low.startswith("video/"):
            return UploadDecision(
                accepted=False,
                reason="mime_mismatch",
                matched_mime=matched_mime,
                detected_size=size,
            )
        if category == "zip" and "zip" not in declared_low:
            return UploadDecision(
                accepted=False,
                reason="mime_mismatch",
                matched_mime=matched_mime,
                detected_size=size,
            )

    # size 上限
    if category == "image":
        limit = policy.image_max_bytes
    elif category == "video":
        limit = policy.video_max_bytes
    elif category == "zip":
        limit = policy.zip_max_bytes
    else:
        limit = policy.generic_max_bytes

    if size > limit:
        return UploadDecision(
            accepted=False,
            reason="oversize",
            matched_mime=matched_mime,
            detected_size=size,
            limit_bytes=limit,
        )

    return UploadDecision(
        accepted=True,
        reason="accepted",
        matched_mime=matched_mime,
        detected_size=size,
        limit_bytes=limit,
    )


__all__ = [
    "UPLOAD_GUARD_ENFORCE_ENV",
    "UploadGuardPolicy",
    "UploadDecision",
    "UploadReason",
    "DEFAULT_UPLOAD_POLICY",
    "check_upload",
    "guess_mime_from_magic",
    "is_upload_guard_enforce_enabled",
]
