"""PR-4a upload validation gate — hardened before FileService switch (PR-4b).

GM-14 圆桌决议:
- 拆分 PR-4 为 PR-4a(本 PR · 安全硬门槛前置)+ PR-4b(FileService 主写切换)
- Magic bytes 手写实现 · 无 filetype / python-magic 新依赖 · 分层防御

所有上限常量在此集中定义 · PR-4b 的 `FileService.create_from_upload` 会共享同一模
块,不许重复定义。5 个上传入口调用本模块进行前置校验,写路径与 FileService 不动。

参考:
- [[40 实施计划/文件对象与 MinIO 治理实施计划与PR清单]] PR-4a
- [[60 讨论记录/2026-07-23 Wave 3-N.3 圆桌/2026-07-23 filetype 依赖引入圆桌纪要]]
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import BinaryIO, Optional

from PIL import Image, UnidentifiedImageError

# ---------------------------------------------------------------------------
# A1 硬上限(GM-14 圆桌决议 · 治理方案原值 · zip DoS 4 项)
# ---------------------------------------------------------------------------
MAX_UPLOAD_BYTES = 200 * 1024 * 1024              # 200 MB · 单请求原始字节上限
MAX_ARCHIVE_UNPACK_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB · 单个 zip 总解压字节上限
MAX_SINGLE_UNPACK_BYTES = 500 * 1024 * 1024        # 500 MB · zip 内单文件解压上限
MAX_ARCHIVE_ENTRIES = 2000                          # zip 内 entry 数上限

# ---------------------------------------------------------------------------
# S8 硬上限(Pillow decompression bomb 防护 · 约 40 MP)
# main.py 顶部会集中设置 Pillow.MAX_IMAGE_PIXELS 到同一值,保证 16 处
# Image.open 全部自动继承此限制。T193 会锁死同源一致。
# ---------------------------------------------------------------------------
MAX_IMAGE_PIXELS = 40_000_000

# ---------------------------------------------------------------------------
# Magic bytes 白名单(GM-14 圆桌决议 · 手写实现 · 分层防御)
# 严格白名单 · 未识别 = 拒绝
# ---------------------------------------------------------------------------
MAGIC_ALLOWED_KINDS = frozenset({
    "png", "jpg", "webp", "gif", "mp4", "webm", "mov", "zip",
})

_IMAGE_KINDS = frozenset({"png", "jpg", "webp", "gif"})
_VIDEO_KINDS = frozenset({"mp4", "webm", "mov"})

# MP4 / MOV / M4V ftyp 家族最小白名单(要求 2)
# 未来发现新 brand 走白名单补丁 PR · 不许 Wildcard。
_MP4_FTYP_BRANDS_MP4 = frozenset({
    b"isom", b"mp41", b"mp42", b"iso2", b"iso5",
    b"avc1",
    b"3gp4", b"3gp5", b"3g2a",
})
_MP4_FTYP_BRANDS_MOV = frozenset({
    b"qt  ", b"M4V ", b"M4A ",
})

# ZIP 三签名(要求 3)
_ZIP_SIGNATURES = (b"\x03\x04", b"\x05\x06", b"\x07\x08")


class UploadRejected(ValueError):
    """Frontend-facing rejection with structured code + message.

    5 个入口捕获此异常后转为 HTTPException(400/413),前端错误 shape 不变。
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ---------------------------------------------------------------------------
# 尺寸校验
# ---------------------------------------------------------------------------
def validate_upload_size(data: bytes) -> None:
    """A1 · 单请求原始字节上限。"""
    if not data:
        raise UploadRejected("upload_empty", "内容为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadRejected(
            "upload_too_large",
            f"超过单请求上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )


# ---------------------------------------------------------------------------
# Magic bytes 手写实现(要求 1-4)
# ---------------------------------------------------------------------------
def _is_png(data: bytes) -> bool:
    return len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n"


def _is_jpg(data: bytes) -> bool:
    # JPEG: FF D8 FF ...
    return len(data) >= 3 and data[:3] == b"\xff\xd8\xff"


def _is_gif(data: bytes) -> bool:
    return len(data) >= 6 and data[:6] in (b"GIF87a", b"GIF89a")


def _is_webp(data: bytes) -> bool:
    """要求 1 · WebP 必须匹 12 字节:RIFF ???? WEBP。

    WAV(RIFF+WAVE)/ AVI(RIFF+AVI )/ ANI(RIFF+ACON)必须不通过。
    """
    return (
        len(data) >= 12
        and data[0:4] == b"RIFF"
        and data[8:12] == b"WEBP"
    )


def _is_webm(data: bytes) -> bool:
    # EBML head magic(WebM / Matroska 共用),深度校验留待后续 PR。
    return len(data) >= 4 and data[0:4] == b"\x1a\x45\xdf\xa3"


def _is_mp4_family(data: bytes) -> Optional[str]:
    """要求 2 · MP4 / MOV / M4V ftyp 家族最小白名单。

    ISO base media: bytes 4-8 = "ftyp" · bytes 8-12 = brand。
    - qt/M4V/M4A → "mov"
    - isom/mp4x/iso2/iso5/avc1/3gpx → "mp4"
    - 未知 brand → None(拒绝)
    """
    if len(data) < 12:
        return None
    if data[4:8] != b"ftyp":
        return None
    brand = data[8:12]
    if brand in _MP4_FTYP_BRANDS_MOV:
        return "mov"
    if brand in _MP4_FTYP_BRANDS_MP4:
        return "mp4"
    return None


def _is_zip(data: bytes) -> bool:
    """要求 3 · ZIP 三签名 · 仅 magic bytes 前置分流。

    结构合法性走 validate_archive_limits · zipfile.is_zipfile。
    """
    return (
        len(data) >= 4
        and data[0:2] == b"PK"
        and data[2:4] in _ZIP_SIGNATURES
    )


def detect_magic_kind(data: bytes) -> Optional[str]:
    """按 magic bytes 分类 · 未识别返回 None(严格白名单 · 拒绝)。

    返回值为 MAGIC_ALLOWED_KINDS 之一或 None。
    """
    if not data:
        return None
    if _is_png(data):
        return "png"
    if _is_jpg(data):
        return "jpg"
    if _is_gif(data):
        return "gif"
    if _is_webp(data):
        return "webp"
    mp4_kind = _is_mp4_family(data)
    if mp4_kind is not None:
        return mp4_kind
    if _is_webm(data):
        return "webm"
    if _is_zip(data):
        return "zip"
    return None


def validate_magic_whitelist(data: bytes, expected: Optional[str] = None) -> str:
    """按 magic bytes 白名单前置校验 · 分层防御第一层。

    - `expected` 传入时,识别到的 kind 必须与 expected 一致(可选二次断言)
    - 返回识别到的 kind · 供上层决定后续走 image / archive 深度校验
    """
    kind = detect_magic_kind(data)
    if kind is None or kind not in MAGIC_ALLOWED_KINDS:
        raise UploadRejected(
            "magic_not_allowed",
            "文件类型未识别或不在白名单",
        )
    if expected is not None and kind != expected:
        raise UploadRejected(
            "magic_mismatch",
            f"文件真实类型 {kind} 与预期 {expected} 不符",
        )
    return kind


# ---------------------------------------------------------------------------
# 深度校验 · 图片(要求 4 · 分层防御)
# ---------------------------------------------------------------------------
def validate_image_pixels(data: bytes) -> None:
    """S8 · 图片像素上限 + Pillow verify 深度校验。

    - 先 Image.open + verify(消耗流)
    - 再重新 open 取 size(verify 后 pointer 已废)
    - 单幅像素 > MAX_IMAGE_PIXELS 拒绝
    - 破损 PNG / 伪装 SVG 等在 verify / open 阶段抛异常 → 拒绝
    """
    try:
        with Image.open(BytesIO(data)) as im:
            im.verify()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, TypeError,
            Image.DecompressionBombError) as exc:
        raise UploadRejected("image_invalid", f"图片解码失败:{exc}") from exc
    # verify 已消耗流 · 重新 open 取尺寸(open 本身不 decode 数据,仅读头)
    try:
        with Image.open(BytesIO(data)) as im:
            width, height = im.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, TypeError,
            Image.DecompressionBombError) as exc:
        raise UploadRejected("image_invalid", f"图片解码失败:{exc}") from exc
    if width * height > MAX_IMAGE_PIXELS:
        raise UploadRejected(
            "image_too_large",
            f"图片像素 {width}x{height} 超过 {MAX_IMAGE_PIXELS // 1_000_000} MP 上限",
        )


# ---------------------------------------------------------------------------
# 深度校验 · ZIP(要求 4 · A1 4 上限)
# ---------------------------------------------------------------------------
def validate_archive_limits(data: bytes) -> None:
    """A1 · zip DoS 4 上限校验 · 分层防御第二层。

    - entry 数 > MAX_ARCHIVE_ENTRIES → archive_too_many_entries
    - 单文件解压后大小 > MAX_SINGLE_UNPACK_BYTES → archive_single_too_large
    - 总解压后大小 > MAX_ARCHIVE_UNPACK_BYTES → archive_total_too_large
    - 未通过 zipfile.is_zipfile → archive_invalid

    注:仅校验 zipinfo.file_size 声明值 · 实际解压时(如 import_canvas_workflow)
    仍需带累计字节数循环二次防御(声明值可被伪造)。
    """
    stream: BinaryIO = BytesIO(data)
    if not zipfile.is_zipfile(stream):
        raise UploadRejected("archive_invalid", "不是有效的 ZIP 压缩包")
    stream.seek(0)
    try:
        with zipfile.ZipFile(stream, "r") as zf:
            infos = zf.infolist()
    except zipfile.BadZipFile as exc:
        raise UploadRejected("archive_invalid", f"ZIP 读取失败:{exc}") from exc
    if len(infos) > MAX_ARCHIVE_ENTRIES:
        raise UploadRejected(
            "archive_too_many_entries",
            f"ZIP 条目数 {len(infos)} 超过 {MAX_ARCHIVE_ENTRIES}",
        )
    total = 0
    for info in infos:
        if info.file_size > MAX_SINGLE_UNPACK_BYTES:
            raise UploadRejected(
                "archive_single_too_large",
                f"ZIP 内单文件 {info.filename} 解压声明 {info.file_size} 字节 "
                f"超过 {MAX_SINGLE_UNPACK_BYTES // (1024 * 1024)} MB",
            )
        total += info.file_size
        if total > MAX_ARCHIVE_UNPACK_BYTES:
            raise UploadRejected(
                "archive_total_too_large",
                f"ZIP 总解压声明 {total} 字节超过 "
                f"{MAX_ARCHIVE_UNPACK_BYTES // (1024 * 1024)} MB",
            )


__all__ = [
    "MAX_UPLOAD_BYTES",
    "MAX_ARCHIVE_UNPACK_BYTES",
    "MAX_SINGLE_UNPACK_BYTES",
    "MAX_ARCHIVE_ENTRIES",
    "MAX_IMAGE_PIXELS",
    "MAGIC_ALLOWED_KINDS",
    "UploadRejected",
    "validate_upload_size",
    "detect_magic_kind",
    "validate_magic_whitelist",
    "validate_image_pixels",
    "validate_archive_limits",
    "guard_upload_bytes",
    "guard_to_http_status",
]


# ---------------------------------------------------------------------------
# 5 入口共用的一次性 guard(A1 尺寸 + magic 白名单 + 图片深度校验 + 可选 zip 4 上限)
# ---------------------------------------------------------------------------
def guard_upload_bytes(
    data: bytes,
    *,
    allow_archive: bool = False,
    require_archive: bool = False,
    archive_only: bool = False,
) -> Optional[str]:
    """一次性执行 PR-4a 全部前置校验 · 供 main.py 5 入口调用。

    - `allow_archive=True`:接受 zip magic · 命中时走 archive_limits
    - `require_archive=True`:强制要求 magic == "zip"
    - `archive_only=True`:如 magic != "zip" 则跳过深度校验(供入口按 filename 后缀
      单独识别 JSON payload 场景)

    返回识别到的 magic kind(或 None · 仅当 archive_only 未命中 zip 时)。
    失败抛 UploadRejected · 由入口层通过 guard_to_http_status 转 HTTPException。
    """
    validate_upload_size(data)
    if archive_only:
        kind = detect_magic_kind(data)
        if kind == "zip":
            validate_archive_limits(data)
        return kind
    kind = validate_magic_whitelist(data)
    if require_archive and kind != "zip":
        raise UploadRejected("magic_mismatch", f"需要 ZIP · 实际 {kind}")
    if kind in _IMAGE_KINDS:
        validate_image_pixels(data)
    elif kind == "zip":
        if allow_archive or require_archive:
            validate_archive_limits(data)
        else:
            raise UploadRejected("magic_not_allowed", "此入口不接受 ZIP")
    return kind


_HTTP_413_CODES = frozenset({
    "upload_too_large",
    "image_too_large",
    "archive_too_many_entries",
    "archive_single_too_large",
    "archive_total_too_large",
})


def guard_to_http_status(exc: UploadRejected) -> int:
    """UploadRejected code → HTTP 状态码(413 for size · 400 otherwise)。"""
    return 413 if exc.code in _HTTP_413_CODES else 400
