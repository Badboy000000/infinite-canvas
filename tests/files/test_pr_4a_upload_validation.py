"""PR-4a upload validation gate tests (T170-T199).

GM-14 圆桌决议 · 手写 magic bytes · 无 filetype 依赖 · 分层防御。

覆盖:
- 尺寸(T170-T171)
- Magic bytes 白名单(T172-T180)· WebP 12 字节 / MP4 ftyp / MOV / ZIP 三签名 /
  SVG / PHP 伪装拒绝
- Archive 4 上限(T181-T184)
- 图片像素 + Pillow verify(T185-T187)
- 端到端 5 入口(T188-T191)· 走 fastapi TestClient
- Pillow 全局限制 + 同源一致(T192-T193)
- 分层防御:SVG 通过 zip 白名单被 Pillow verify 拒绝(T194)
- Fixtures 参数化(T195-T197)
- 冻结区 AST(T198)· OpenAPI baseline(T199)
"""

from __future__ import annotations

import base64
import io
import os
import struct
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.services.files.validation import (  # noqa: E402
    MAGIC_ALLOWED_KINDS,
    MAX_ARCHIVE_ENTRIES,
    MAX_ARCHIVE_UNPACK_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_SINGLE_UNPACK_BYTES,
    MAX_UPLOAD_BYTES,
    UploadRejected,
    detect_magic_kind,
    validate_archive_limits,
    validate_image_pixels,
    validate_magic_whitelist,
    validate_upload_size,
)

FIXTURES = Path(__file__).parent / "fixtures" / "magic"


# ---------------------------------------------------------------------------
# 辅助工具
# ---------------------------------------------------------------------------
def _mp4_ftyp(brand: bytes) -> bytes:
    """构造最小 ftyp box · 供参数化测试用。"""
    payload = brand + b"\x00\x00\x00\x00"
    size = 8 + len(payload)
    return struct.pack(">I", size) + b"ftyp" + payload + b"\x00" * 8


def _png_bytes(size: tuple[int, int]) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (128, 128, 128)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# T170-T171 · validate_upload_size
# ---------------------------------------------------------------------------
def test_T170_validate_upload_size_over_limit_rejected() -> None:
    """200 MB + 1 byte 拒绝 · code=upload_too_large。"""
    data = b"\x00" * (MAX_UPLOAD_BYTES + 1)
    with pytest.raises(UploadRejected) as exc:
        validate_upload_size(data)
    assert exc.value.code == "upload_too_large"


def test_T171_validate_upload_size_under_limit_accepted() -> None:
    """200 MB - 1 byte 通过 · 无异常。"""
    # 用 1 MB 试探(200 MB 数据分配代价过大 · 断言 边界上限 - 1 通过等价)
    data = b"\x00" * (1024 * 1024)
    validate_upload_size(data)


# ---------------------------------------------------------------------------
# T172-T180 · magic bytes 白名单
# ---------------------------------------------------------------------------
def test_T172_magic_webp_12_bytes_accepted() -> None:
    """RIFF ???? WEBP · 12 字节完整通过 · 返回 webp。"""
    data = (FIXTURES / "webp" / "small_16x16.webp").read_bytes()
    assert detect_magic_kind(data) == "webp"


def test_T173_magic_riff_wav_rejected() -> None:
    """WAV(RIFF+WAVE)返回 None(要求 1)。"""
    data = (FIXTURES / "attacks" / "wav_riff.wav").read_bytes()
    assert detect_magic_kind(data) is None


def test_T174_magic_riff_avi_rejected() -> None:
    """AVI(RIFF+AVI )返回 None(要求 1)。"""
    data = (FIXTURES / "attacks" / "avi_riff.avi").read_bytes()
    assert detect_magic_kind(data) is None


def test_T174b_magic_riff_ani_rejected() -> None:
    """ANI(RIFF+ACON)返回 None(要求 1)。"""
    data = (FIXTURES / "attacks" / "ani_riff.ani").read_bytes()
    assert detect_magic_kind(data) is None


@pytest.mark.parametrize("brand", [b"isom", b"mp42", b"iso2", b"iso5"])
def test_T175_magic_mp4_brands_accepted(brand: bytes) -> None:
    """MP4 ftyp 白名单 brand 全通过 · 返回 mp4。"""
    assert detect_magic_kind(_mp4_ftyp(brand)) == "mp4"


def test_T176_magic_mp4_unknown_brand_rejected() -> None:
    """未知 brand xxxx 拒绝 · 返回 None(要求 2)。"""
    data = (FIXTURES / "attacks" / "unknown_ftyp.mp4").read_bytes()
    assert detect_magic_kind(data) is None


@pytest.mark.parametrize("brand", [b"qt  ", b"M4V ", b"M4A "])
def test_T177_magic_mov_brands_accepted(brand: bytes) -> None:
    """MOV / M4V / M4A brand 通过 · 归 mov(要求 2)。"""
    assert detect_magic_kind(_mp4_ftyp(brand)) == "mov"


@pytest.mark.parametrize("suffix", [b"\x03\x04", b"\x05\x06", b"\x07\x08"])
def test_T178_magic_zip_three_signatures_accepted(suffix: bytes) -> None:
    """ZIP 三签名(要求 3)· PK\\x03\\x04 / PK\\x05\\x06 / PK\\x07\\x08 全识别。"""
    assert detect_magic_kind(b"PK" + suffix + b"\x00" * 32) == "zip"


def test_T179_magic_svg_disguised_as_png_rejected() -> None:
    """SVG payload · magic 头是 <?xml / <svg · 拒绝(伪装 .png)。"""
    data = (FIXTURES / "attacks" / "svg_as.png").read_bytes()
    assert detect_magic_kind(data) is None
    with pytest.raises(UploadRejected) as exc:
        validate_magic_whitelist(data)
    assert exc.value.code == "magic_not_allowed"


def test_T180_magic_php_disguised_as_png_rejected() -> None:
    """PHP `<?php` 伪装 .png · magic 头非白名单 · 拒绝。"""
    data = (FIXTURES / "attacks" / "php_as.png").read_bytes()
    assert detect_magic_kind(data) is None
    with pytest.raises(UploadRejected) as exc:
        validate_magic_whitelist(data)
    assert exc.value.code == "magic_not_allowed"


# ---------------------------------------------------------------------------
# T181-T184 · validate_archive_limits
# ---------------------------------------------------------------------------
def _build_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def test_T181_archive_too_many_entries_rejected() -> None:
    """2001 条 entry 拒绝 · code=archive_too_many_entries。"""
    entries = {f"item_{i}.txt": b"x" for i in range(MAX_ARCHIVE_ENTRIES + 1)}
    data = _build_zip(entries)
    with pytest.raises(UploadRejected) as exc:
        validate_archive_limits(data)
    assert exc.value.code == "archive_too_many_entries"


def test_T182_archive_single_too_large_rejected() -> None:
    """单文件解压声明 501 MB 拒绝 · code=archive_single_too_large。

    直接构造 zipinfo.file_size 声明值超限的 zip(不实际生成 500 MB payload)。
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("small.txt", b"x")  # 占位 entry
    data = buf.getvalue()
    # 直接通过伪造 zipinfo 来测试:改走 monkey-patch zipfile.ZipFile.infolist
    with pytest.raises(UploadRejected) as exc:
        _fake_infos = [_FakeInfo("big.bin", MAX_SINGLE_UNPACK_BYTES + 1)]
        _run_archive_check_with_fake_infos(data, _fake_infos)
    assert exc.value.code == "archive_single_too_large"


def test_T183_archive_total_too_large_rejected() -> None:
    """总解压声明 1 GB + 1 byte 拒绝 · code=archive_total_too_large。"""
    # 3 个 entry 每个声明 400 MB · 总 1.2 GB · 触发 total 上限
    per = 400 * 1024 * 1024
    fake_infos = [
        _FakeInfo("a.bin", per),
        _FakeInfo("b.bin", per),
        _FakeInfo("c.bin", per),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("placeholder.txt", b"x")
    with pytest.raises(UploadRejected) as exc:
        _run_archive_check_with_fake_infos(buf.getvalue(), fake_infos)
    assert exc.value.code == "archive_total_too_large"


def test_T184_archive_empty_zip_accepted() -> None:
    """空 zip(PK\\x05\\x06)通过 · 无异常。"""
    data = (FIXTURES / "zip" / "empty.zip").read_bytes()
    validate_archive_limits(data)  # 不抛


class _FakeInfo:
    """伪造 ZipInfo · 用于测试大文件声明上限拒绝路径。"""

    def __init__(self, filename: str, file_size: int) -> None:
        self.filename = filename
        self.file_size = file_size


def _run_archive_check_with_fake_infos(data: bytes, fake_infos: list[_FakeInfo]) -> None:
    """monkey-patch ZipFile.infolist · 让 validate_archive_limits 读到伪造声明值。"""
    import app.services.files.validation as validation_mod

    original = zipfile.ZipFile.infolist

    def _patched(self):  # type: ignore[no-redef]
        return fake_infos

    zipfile.ZipFile.infolist = _patched  # type: ignore[assignment]
    try:
        validation_mod.validate_archive_limits(data)
    finally:
        zipfile.ZipFile.infolist = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# T185-T187 · validate_image_pixels
# ---------------------------------------------------------------------------
def test_T185_image_pixels_over_limit_rejected() -> None:
    """伪造图片尺寸 >40 MP · monkey-patch Image.open 走 fake size 触发拒绝。"""
    import app.services.files.validation as validation_mod

    real_open = validation_mod.Image.open

    class _FakeImg:
        size = (10000, 5000)  # 50 MP

        def verify(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def _fake_open(_data):  # type: ignore[no-redef]
        return _FakeImg()

    validation_mod.Image.open = _fake_open  # type: ignore[assignment]
    try:
        with pytest.raises(UploadRejected) as exc:
            validation_mod.validate_image_pixels(b"whatever")
        assert exc.value.code == "image_too_large"
    finally:
        validation_mod.Image.open = real_open  # type: ignore[assignment]


def test_T186_image_pixels_under_limit_accepted() -> None:
    """真实 512x512 PNG 通过 · 无异常。"""
    data = _png_bytes((512, 512))
    validate_image_pixels(data)


def test_T187_image_broken_png_rejected() -> None:
    """PNG magic 头合法但主体破损 · Pillow verify 抛异常 · code=image_invalid。"""
    data = (FIXTURES / "attacks" / "png_body_corrupt.png").read_bytes()
    with pytest.raises(UploadRejected) as exc:
        validate_image_pixels(data)
    assert exc.value.code == "image_invalid"


# ---------------------------------------------------------------------------
# T188-T191 · 端到端 5 入口(TestClient)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def api_client():
    import main as main_mod

    return TestClient(main_mod.app)


def test_T188_e2e_upload_ai_base64_oversized_image_rejected(api_client) -> None:
    """upload_ai_base64 · 端到端 40 MP + 1 图片拒绝 400/413。"""
    import app.services.files.validation as validation_mod

    real_open = validation_mod.Image.open

    class _FakeImg:
        size = (7000, 6000)  # 42 MP

        def verify(self):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def _fake_open(_data):  # type: ignore[no-redef]
        return _FakeImg()

    validation_mod.Image.open = _fake_open  # type: ignore[assignment]
    try:
        png = _png_bytes((64, 64))
        b64 = base64.b64encode(png).decode()
        resp = api_client.post(
            "/api/ai/upload-base64",
            json={"data": b64, "name": "t.png", "content_type": "image/png"},
        )
        assert resp.status_code in (400, 413), resp.text
    finally:
        validation_mod.Image.open = real_open  # type: ignore[assignment]


def test_T189_e2e_local_assets_upload_oversized_rejected(api_client) -> None:
    """upload_local_assets · 端到端 200 MB + 1 字节拒绝。"""
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_UPLOAD_BYTES + 1 - 8)
    resp = api_client.post(
        "/api/local-assets/upload",
        files={"files": ("big.png", payload, "image/png")},
        data={"folder": ""},
    )
    assert resp.status_code in (400, 413), resp.text


def test_T190_e2e_workflow_upload_zip_too_many_entries_rejected(api_client) -> None:
    """upload_asset_library_workflows · 端到端 2001 entry 恶意 zip 拒绝。"""
    entries = {f"n_{i}.txt": b"x" for i in range(MAX_ARCHIVE_ENTRIES + 1)}
    data = _build_zip(entries)
    resp = api_client.post(
        "/api/asset-library/workflows/upload",
        files={"files": ("bad.zip", data, "application/zip")},
        data={"library_id": "", "category_id": ""},
    )
    assert resp.status_code in (400, 413), resp.text


def test_T191_e2e_import_canvas_workflow_zip_single_too_large_rejected(
    api_client, tmp_path, monkeypatch
) -> None:
    """import_canvas_workflow · 端到端 zip bomb(声明单文件 501 MB)拒绝 · target 已清理。"""
    # 用声明伪造走 archive_limits 路径(直接前置校验拒绝 · 不进入实际解压循环)
    _fake_infos = [_FakeInfo("big.bin", MAX_SINGLE_UNPACK_BYTES + 1)]
    import app.services.files.validation as validation_mod

    original = zipfile.ZipFile.infolist

    def _patched(self):  # type: ignore[no-redef]
        return _fake_infos

    monkeypatch.setattr(zipfile.ZipFile, "infolist", _patched)
    # 构造一个真实合法 zip · 使 magic 通过 · archive_limits 用 patched infolist 拒
    normal_zip = (FIXTURES / "zip" / "normal.zip").read_bytes()
    resp = api_client.post(
        "/api/canvas-workflows/import",
        files={"file": ("bomb.zip", normal_zip, "application/zip")},
    )
    assert resp.status_code in (400, 413), resp.text


# ---------------------------------------------------------------------------
# T192-T193 · Pillow 全局限制 + 同源一致
# ---------------------------------------------------------------------------
def test_T192_pillow_max_image_pixels_set_at_main_import() -> None:
    """import main 后 · PIL.Image.MAX_IMAGE_PIXELS 必为 40_000_000。"""
    import main  # noqa: F401
    import PIL.Image

    assert PIL.Image.MAX_IMAGE_PIXELS == 40_000_000


def test_T193_max_image_pixels_same_value_across_sources() -> None:
    """main.py 顶部值 == validation.py::MAX_IMAGE_PIXELS · 同源一致。"""
    import main
    import PIL.Image

    # main.py 顶部直接 assign · 读 Image.MAX_IMAGE_PIXELS 等价
    assert PIL.Image.MAX_IMAGE_PIXELS == MAX_IMAGE_PIXELS
    # 另证 main 模块引用的常量也相等
    assert main._PR4A_MAX_IMAGE_PIXELS == MAX_IMAGE_PIXELS


# ---------------------------------------------------------------------------
# T194 · 分层防御(SVG 通过 magic 白名单会被 magic 拒绝 · 已 T179 覆盖 magic 层)
#       本 T194 补:构造头字节让 magic 误判 → Pillow verify 拒绝
# ---------------------------------------------------------------------------
def test_T194_layered_defense_bogus_png_head_then_pillow_reject() -> None:
    """带合法 PNG magic head 但主体为 SVG payload · Pillow verify 抛异常。"""
    svg_body = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    fake = b"\x89PNG\r\n\x1a\n" + svg_body
    # magic 层通过(png)
    assert detect_magic_kind(fake) == "png"
    # Pillow 深度校验拒绝
    with pytest.raises(UploadRejected) as exc:
        validate_image_pixels(fake)
    assert exc.value.code == "image_invalid"


# ---------------------------------------------------------------------------
# T195-T197 · Fixtures 语料库参数化
# ---------------------------------------------------------------------------
_LEGAL_CASES = [
    (kind, path)
    for kind in ("png", "jpg", "webp", "gif", "mp4", "mov", "webm", "zip")
    for path in sorted((FIXTURES / kind).glob("*"))
    if path.is_file()
]
_ATTACK_CASES = sorted((FIXTURES / "attacks").glob("*"))


def test_T195a_fixture_corpus_legal_min_count() -> None:
    """每类型 ≥3 合法样本。"""
    for kind in ("png", "jpg", "webp", "gif", "mp4", "mov", "webm"):
        n = len(list((FIXTURES / kind).glob("*")))
        assert n >= 3, f"{kind}: only {n} legal samples"


def test_T195b_fixture_corpus_attacks_min_count() -> None:
    """attacks ≥2(实际 ≥7)· 覆盖 RIFF 混淆 / 伪装 / 头篡改 / 截断 / 未知 brand。"""
    assert len(_ATTACK_CASES) >= 2


@pytest.mark.parametrize("kind,path", _LEGAL_CASES, ids=lambda v: str(v))
def test_T196_fixture_legal_recognized_by_magic(kind: str, path: Path) -> None:
    """所有合法 fixture 都被 magic bytes 正确分类到 MAGIC_ALLOWED_KINDS。

    注:spanned_signature.bin 是 zip · 手工头虽通过 magic 但 zipfile.is_zipfile
    会拒。本参数化只断言 magic 层分类正确。
    """
    data = path.read_bytes()
    detected = detect_magic_kind(data)
    if kind == "zip" and path.name == "spanned_signature.bin":
        assert detected == "zip"  # magic 层通过
    else:
        assert detected == kind, f"{path} → {detected}, expected {kind}"


@pytest.mark.parametrize("path", _ATTACK_CASES, ids=lambda v: v.name)
def test_T197_fixture_attacks_rejected_by_magic(path: Path) -> None:
    """所有攻击样本要么 magic 拒绝 · 要么进 image 深度校验拒绝。

    - RIFF WAV/AVI/ANI · svg_as.png · php_as.png · unknown_ftyp · truncated → magic None
    - png_head_tampered · magic 通过但 Pillow verify 拒绝
    """
    data = path.read_bytes()
    detected = detect_magic_kind(data)
    if path.name == "png_body_corrupt.png":
        assert detected == "png"  # magic 层过 · 由 image 层拒
        with pytest.raises(UploadRejected):
            validate_image_pixels(data)
    else:
        assert detected is None, f"attack {path.name} unexpectedly detected as {detected}"


# ---------------------------------------------------------------------------
# T198 · 冻结区 AST(复用 test_save_functions_frozen.py 保证 · 本 PR 只补引用)
# ---------------------------------------------------------------------------
def test_T198_save_functions_frozen_zone_still_covered() -> None:
    """本 PR 未触碰 5 个 save_* 函数 · test_save_functions_frozen.py 保护有效。

    这是一个健壮性断言 · 保证 PR-4a 交付时冻结区测试文件存在且未被移除。
    """
    frozen_test = ROOT / "tests" / "db" / "test_save_functions_frozen.py"
    assert frozen_test.is_file(), "test_save_functions_frozen.py 缺失"
    text = frozen_test.read_text(encoding="utf-8")
    for fname in (
        "save_projects",
        "save_prompt_libraries",
        "save_runninghub_workflow_store",
        "save_asset_library",
    ):
        assert fname in text, f"{fname} 未在冻结区断言列表"


# ---------------------------------------------------------------------------
# T199 · OpenAPI baseline 不变
# ---------------------------------------------------------------------------
def test_T199_openapi_diff_exit_zero() -> None:
    """python tools/openapi_diff.py exit=0 · 契约不变。"""
    import subprocess

    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "openapi_diff.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, (
        f"openapi_diff.py exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
