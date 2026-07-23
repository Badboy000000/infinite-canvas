"""Generate real-byte fixture corpus for PR-4a magic bytes tests.

Run once to (re)generate all fixture files under tests/files/fixtures/magic/.
Fixtures are committed to the repo — this script is documentation of
provenance, not a runtime dependency of the test suite.

Categories (each has >=3 legal + >=2 attack variants):
- png · jpg · webp · gif (image · small / medium / boundary)
- mp4 · webm · mov (video · isom / mp42 / qt · minimum ftyp header)
- zip (empty / normal / spanned signature)
- attacks (WAV / AVI / ANI RIFF confusion · SVG-as-PNG · truncated · unknown ftyp brand)
"""

from __future__ import annotations

import io
import struct
import wave
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


# ---------------------------------------------------------------------------
# 图片(Pillow 生成真实字节)
# ---------------------------------------------------------------------------
def _pil_bytes(fmt: str, size: tuple[int, int], color: tuple[int, int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def build_png() -> None:
    _write(ROOT / "png" / "small_16x16.png", _pil_bytes("PNG", (16, 16), (255, 0, 0)))
    _write(ROOT / "png" / "medium_512x512.png", _pil_bytes("PNG", (512, 512), (0, 255, 0)))
    _write(ROOT / "png" / "boundary_1024x1024.png", _pil_bytes("PNG", (1024, 1024), (0, 0, 255)))


def build_jpg() -> None:
    _write(ROOT / "jpg" / "small_16x16.jpg", _pil_bytes("JPEG", (16, 16), (255, 128, 0)))
    _write(ROOT / "jpg" / "medium_512x512.jpg", _pil_bytes("JPEG", (512, 512), (128, 255, 0)))
    _write(ROOT / "jpg" / "boundary_1024x1024.jpg", _pil_bytes("JPEG", (1024, 1024), (0, 128, 255)))


def build_webp() -> None:
    _write(ROOT / "webp" / "small_16x16.webp", _pil_bytes("WEBP", (16, 16), (255, 0, 128)))
    _write(ROOT / "webp" / "medium_512x512.webp", _pil_bytes("WEBP", (512, 512), (0, 255, 128)))
    _write(ROOT / "webp" / "boundary_1024x1024.webp", _pil_bytes("WEBP", (1024, 1024), (128, 0, 255)))


def build_gif() -> None:
    _write(ROOT / "gif" / "small_16x16.gif", _pil_bytes("GIF", (16, 16), (200, 100, 50)))
    _write(ROOT / "gif" / "medium_512x512.gif", _pil_bytes("GIF", (512, 512), (50, 200, 100)))
    _write(ROOT / "gif" / "boundary_1024x1024.gif", _pil_bytes("GIF", (1024, 1024), (100, 50, 200)))


# ---------------------------------------------------------------------------
# 视频(手写最小 ISO base media / EBML head · magic bytes 前置识别 · 不深度校验)
# ---------------------------------------------------------------------------
def _mp4_ftyp(brand: bytes, compatible: tuple[bytes, ...] = ()) -> bytes:
    """最小 ftyp box · 用于 magic bytes 前置识别单测。

    box size(4) + "ftyp"(4) + major_brand(4) + minor_version(4=0) + compat[N*4]
    """
    payload = brand + b"\x00\x00\x00\x00" + b"".join(compatible)
    size = 8 + len(payload)
    box = struct.pack(">I", size) + b"ftyp" + payload
    # 追加 32 字节 mdat box 占位使其看起来更像真实文件
    mdat_payload = b"\x00" * 32
    mdat = struct.pack(">I", 8 + len(mdat_payload)) + b"mdat" + mdat_payload
    return box + mdat


def build_mp4() -> None:
    _write(ROOT / "mp4" / "brand_isom.mp4", _mp4_ftyp(b"isom", (b"iso2", b"mp41", b"mp42")))
    _write(ROOT / "mp4" / "brand_mp42.mp4", _mp4_ftyp(b"mp42", (b"isom",)))
    _write(ROOT / "mp4" / "brand_iso5.mp4", _mp4_ftyp(b"iso5", (b"isom", b"avc1")))


def build_mov() -> None:
    _write(ROOT / "mov" / "brand_qt.mov", _mp4_ftyp(b"qt  "))
    _write(ROOT / "mov" / "brand_m4v.mov", _mp4_ftyp(b"M4V "))
    _write(ROOT / "mov" / "brand_m4a.mov", _mp4_ftyp(b"M4A "))


def build_webm() -> None:
    # EBML head magic · 后随一个占位 body
    ebml_magic = b"\x1a\x45\xdf\xa3"
    for tag, size in [("small", 128), ("medium", 512), ("boundary", 1024)]:
        _write(ROOT / "webm" / f"{tag}.webm", ebml_magic + b"\x00" * size)


# ---------------------------------------------------------------------------
# ZIP(三签名 · zipfile 生成真实字节)
# ---------------------------------------------------------------------------
def build_zip() -> None:
    # 常规 zip · PK\x03\x04 起
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", b"hello world")
    _write(ROOT / "zip" / "normal.zip", buf.getvalue())

    # 多文件 zip
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(5):
            zf.writestr(f"item_{i}.txt", f"payload {i}".encode())
    _write(ROOT / "zip" / "multi_entries.zip", buf.getvalue())

    # 空 zip · PK\x05\x06 起(zipfile 空归档)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    _write(ROOT / "zip" / "empty.zip", buf.getvalue())

    # spanned 签名 PK\x07\x08(手工头 · zipfile 拒读 · 但 magic bytes 通过)
    _write(ROOT / "zip" / "spanned_signature.bin", b"PK\x07\x08" + b"\x00" * 32)


# ---------------------------------------------------------------------------
# 攻击语料库(≥2 每类型的原则由测试参数化覆盖到 attacks 目录)
# ---------------------------------------------------------------------------
def build_attacks() -> None:
    # RIFF 混淆(要求 1)
    _write(ROOT / "attacks" / "wav_riff.wav",
           b"RIFF" + struct.pack("<I", 36) + b"WAVE" + b"\x00" * 32)
    _write(ROOT / "attacks" / "avi_riff.avi",
           b"RIFF" + struct.pack("<I", 36) + b"AVI " + b"\x00" * 32)
    _write(ROOT / "attacks" / "ani_riff.ani",
           b"RIFF" + struct.pack("<I", 36) + b"ACON" + b"\x00" * 32)

    # SVG 伪装 .png(magic 头是 <?xml / <svg)
    svg_body = b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'><rect width='10' height='10'/></svg>"
    _write(ROOT / "attacks" / "svg_as.png", svg_body)

    # PHP 伪装 .png
    _write(ROOT / "attacks" / "php_as.png", b"<?php echo 'pwned'; ?>")

    # 未知 ftyp brand(要求 2 · 拒绝)
    _write(ROOT / "attacks" / "unknown_ftyp.mp4", _mp4_ftyp(b"xxxx"))

    # 头字节篡改(PNG 前 4 字节改写)
    png = _pil_bytes("PNG", (8, 8), (10, 20, 30))
    _write(ROOT / "attacks" / "png_head_tampered.png", b"\x00\x00\x00\x00" + png[4:])

    # PNG 头合法但主体被破坏(magic 层通过 · Pillow verify 拒)
    _write(ROOT / "attacks" / "png_body_corrupt.png", png[:16] + b"\x00" * (len(png) - 16))

    # 截断样本(仅前 6 字节 · 无法识别)
    _write(ROOT / "attacks" / "truncated.bin", b"\x89PNG\r\n")


def build_pr4a1_attacks() -> None:
    """PR-4a.1 · CB-P5-23 类型专属 attack fixtures + CB-P5-24 zip entry-name attacks.

    所有 fixture 为可解析真实字节:
    - 类型专属截断 / 头篡改:magic bytes 差一字节或首字节篡改 · detect_magic_kind 返回 None
    - Zip entry-name attacks:zipfile.writestr 真实构造 · namelist 保留恶意名字供 sanitize 验证
    """
    # ------------------------------------------------------------------
    # CB-P5-23 · 类型专属 attack fixtures
    # ------------------------------------------------------------------
    # WebP 12 字节头缺 1 字节(RIFF ???? WEB · 只有 11 字节)
    # `_is_webp` 要求 data[8:12] == b"WEBP" 且总长 >= 12 · 11 字节直接不通过 len 检查
    riff_size = struct.pack("<I", 4)
    _write(ROOT / "attacks" / "webp_11byte_truncated.bin",
           b"RIFF" + riff_size + b"WEB")  # 恰好 11 字节 · WEBP 少最后一个 P

    # MOV 未知 brand(qt / M4V / M4A 之外)· 构造 ftyp box + 未知 brand "XXXX"
    _write(ROOT / "attacks" / "mov_unknown_brand.mov", _mp4_ftyp(b"XXXX"))

    # JPG 头首字节篡改(合法 JPG 是 FF D8 FF · 篡改后 00 D8 FF)
    jpg = _pil_bytes("JPEG", (16, 16), (200, 100, 50))
    _write(ROOT / "attacks" / "jpg_head_tampered.jpg", b"\x00" + jpg[1:])

    # GIF 头缺 1 字节(合法 6 字节 GIF89a → 只写 GIF89)
    gif = _pil_bytes("GIF", (16, 16), (50, 100, 200))
    _write(ROOT / "attacks" / "gif_truncated.gif", b"GIF89" + gif[6:])

    # WebM/EBML 头首字节篡改(合法 1A 45 DF A3 → 00 45 DF A3)
    ebml_magic = b"\x1a\x45\xdf\xa3"
    tampered_ebml = b"\x00" + ebml_magic[1:] + b"\x00" * 128
    _write(ROOT / "attacks" / "webm_head_tampered.webm", tampered_ebml)

    # ------------------------------------------------------------------
    # CB-P5-24 · Zip entry-name path traversal attacks
    # ------------------------------------------------------------------
    def _make_zip_with_name(name: str, filename: str) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
            # zipfile.writestr 允许任意 entry name · 真实字节输出
            zf.writestr(name, b"payload-for-" + name.encode("utf-8", errors="replace"))
        _write(ROOT / "attacks" / filename, buf.getvalue())

    _make_zip_with_name("../../etc/passwd", "zip_entry_traversal.zip")
    _make_zip_with_name("/tmp/evil", "zip_entry_absolute.zip")
    # NUL byte 混入 · zipfile 允许 · 供 sanitize 层验证
    _make_zip_with_name("evil.png\x00.php", "zip_entry_nullbyte.zip")
    # Windows 保留名 CON.png
    _make_zip_with_name("CON.png", "zip_entry_windows_reserved.zip")


def main() -> None:
    build_png()
    build_jpg()
    build_webp()
    build_gif()
    build_mp4()
    build_mov()
    build_webm()
    build_zip()
    build_attacks()
    build_pr4a1_attacks()
    print("fixtures generated at", ROOT)


if __name__ == "__main__":
    main()
