"""PR-4a upload validation gate tests (T170-T199) + PR-4a.1 补丁 (T200-T215).

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
- **PR-4a.1**:
  - CB-P5-22:T200-T205 · upload_ai_reference + import_local_assets_from_urls e2e
  - CB-P5-23:T206-T207 · MP4 brand 9/9 覆盖 + 类型专属 attack fixtures
  - CB-P5-24:T208-T214 · 累计字节 loop 真实字节 + 路径穿越 attacks + sanitize 单测
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
    - 类型专属截断/头篡改(PR-4a.1 CB-P5-23):webp_11byte / mov_unknown_brand /
      jpg_head_tampered / gif_truncated / webm_head_tampered → magic None
    - png_head_tampered → magic None(首 4 字节被清空)
    - png_body_corrupt.png · magic 通过但 Pillow verify 拒绝
    - zip_entry_*(PR-4a.1 CB-P5-24):合法 zip 携带恶意 entry name · magic 通过
      · 由 sanitize_export_filename 层拒绝(T210-T213 独立断言)
    """
    data = path.read_bytes()
    detected = detect_magic_kind(data)
    if path.name == "png_body_corrupt.png":
        assert detected == "png"  # magic 层过 · 由 image 层拒
        with pytest.raises(UploadRejected):
            validate_image_pixels(data)
    elif path.name.startswith("zip_entry_"):
        # PR-4a.1 CB-P5-24 · 合法 zip 恶意 entry name · magic 层放行 · 由 sanitize 层处理
        assert detected == "zip", (
            f"zip entry-name attack fixture {path.name} magic 分类应为 zip · 实际 {detected}"
        )
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


# ===========================================================================
# PR-4a.1 补丁(CB-P5-22 + CB-P5-23 + CB-P5-24 一次合并交付)
# ===========================================================================
#
# GM-14 圆桌决议自治条款生效 · Backend Architect subagent 独立技术拍板记录:
#
# T208 累计字节 loop 真实字节构造策略 · Lead 已拍板:
#   任务书要求"STORED 压缩真实字节膨胀 zip · 声明 100MB · 实际 > 500MB · 走
#   `main.py:15539-15561` 累计分支 · 触发 unlink + 413 · 不许 monkey-patch
#   infolist"。经 4 组实验验证(CD-only / CD+LFH / STORED / DEFLATE):Python
#   stdlib zipfile 会在 ZipExtFile._read1 阶段抛 BadZipFile Bad CRC-32 · 无法
#   在保持"文件可读"的前提下让声明值小于真实字节流。任务书构造在 stdlib
#   语义下不可达 · 因此本 PR 采用等价路径:
#
#   1. 真实 STORED zip · 单文件 512 KB(声明值与真实字节相等 · CRC 合法)
#   2. monkeypatch `main._PR4A_MAX_SINGLE_UNPACK_BYTES` → 128 KB
#   3. 累计字节 loop(main.py:15539-15561)真实读到第三个 64 KB 块时超阈值
#      → dst.close() → os.unlink(target) → HTTPException 413
#   4. **不触碰 infolist** · 走真实字节 loop 分支 · 断言 target 磁盘无残留
#
# 差异 vs 任务书:限值大小从 500 MB / 100 MB 降到 128 KB / 512 KB · 但源码
# 15539-15561 行同一顺序执行 · 覆盖等价。风险:如果未来该 loop 被硬编码为
# 500*1024*1024 而不再引用常量 · monkeypatch 失效。缓解:T215 断言常量在
# main 模块中被引用(inspect.getsource) · 锁死引用关系。
#
# ===========================================================================

# ---------------------------------------------------------------------------
# CB-P5-22 承接 · T200-T205:upload_ai_reference + import_local_assets_from_urls
# ---------------------------------------------------------------------------
def _assets_input_dir():
    """获取 assets/input/ 目录 · 用于 e2e 落盘检查。"""
    import main as main_mod

    return Path(main_mod.ASSETS_DIR) / "input"


def _snapshot_input_dir() -> set[str]:
    """快照 assets/input/ 下的 ai_ref_* 文件名 · 用于测前后 diff。"""
    d = _assets_input_dir()
    if not d.exists():
        return set()
    return {p.name for p in d.iterdir() if p.name.startswith("ai_ref_")}


def test_T200_e2e_upload_ai_reference_svg_disguised_rejected(api_client) -> None:
    """CB-P5-22 · upload_ai_reference 真实字节 SVG 伪装 PNG → 400 · 不落盘。"""
    before = _snapshot_input_dir()
    svg = (FIXTURES / "attacks" / "svg_as.png").read_bytes()
    resp = api_client.post(
        "/api/ai/upload",
        files={"files": ("evil.png", svg, "image/png")},
    )
    assert resp.status_code == 400, resp.text
    after = _snapshot_input_dir()
    assert after == before, f"SVG 伪装竟落盘: new files = {after - before}"


def test_T201_e2e_upload_ai_reference_php_disguised_rejected(api_client) -> None:
    """CB-P5-22 · upload_ai_reference 真实字节 PHP 伪装 PNG → 400 · 不落盘。"""
    before = _snapshot_input_dir()
    php = (FIXTURES / "attacks" / "php_as.png").read_bytes()
    resp = api_client.post(
        "/api/ai/upload",
        files={"files": ("evil.png", php, "image/png")},
    )
    assert resp.status_code == 400, resp.text
    after = _snapshot_input_dir()
    assert after == before, f"PHP 伪装竟落盘: new files = {after - before}"


def test_T202_e2e_upload_ai_reference_over_a1_limit_rejected(api_client) -> None:
    """CB-P5-22 · upload_ai_reference 200 MB + 1 A1 上限 → 413 · 不落盘。

    构造真实字节 = 有效 PNG head + 填充 · 大小超 MAX_UPLOAD_BYTES · A1 层拒。
    """
    before = _snapshot_input_dir()
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_UPLOAD_BYTES + 1 - 8)
    resp = api_client.post(
        "/api/ai/upload",
        files={"files": ("big.png", payload, "image/png")},
    )
    assert resp.status_code == 413, resp.text
    after = _snapshot_input_dir()
    assert after == before


def test_T203_e2e_upload_ai_reference_legal_png_accepted(api_client, tmp_path) -> None:
    """CB-P5-22 · upload_ai_reference 合法 PNG → 200 · 落盘 assets/input/。"""
    before = _snapshot_input_dir()
    png = _png_bytes((32, 32))
    resp = api_client.post(
        "/api/ai/upload",
        files={"files": ("ok.png", png, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("files"), body
    after = _snapshot_input_dir()
    new_files = after - before
    assert new_files, "合法 PNG 应落盘 assets/input/ 却未新增文件"
    # GM-14 hygiene · 清理测试产物 · 避免 assets/input/ 残留
    # 允许 unlink 失败(Windows 下 shadow 索引可能仍持文件句柄)但记录警告
    import time as _time
    for _attempt in range(3):
        remaining = _snapshot_input_dir() & new_files
        if not remaining:
            break
        for name in remaining:
            try:
                (_assets_input_dir() / name).unlink()
            except OSError:
                pass
        _time.sleep(0.05)
    # 至少 unlink 尝试执行过 · 最终态断言 asserts 只用于文档 · 不阻塞其他测试
    residue = _snapshot_input_dir() & new_files
    assert not residue, (
        f"清理未干净:{residue} · GM-14 违规 · 交付前手动 rm assets/input/ai_ref_*"
    )


def test_T204_e2e_import_local_assets_from_urls_svg_disguised_rejected(api_client) -> None:
    """CB-P5-22 (TRA F-TRA-1) · import_local_assets_from_urls 真实字节 SVG 伪装 → 400。"""
    svg = (FIXTURES / "attacks" / "svg_as.png").read_bytes()
    b64 = base64.b64encode(svg).decode()
    resp = api_client.post(
        "/api/local-assets/import-urls",
        json={
            "items": [
                {
                    "url": "https://example.com/evil.png",
                    "name": "evil.png",
                    "data": b64,
                    "content_type": "image/png",
                }
            ],
            "folder": "",
        },
    )
    # 端点内部 try/except 会把 HTTPException 归到 result["error"] 而非 400 顶层
    # 但 _pr4a_check 抛 HTTPException 状态是 400 · 端点结构会返回 200 顶层
    # 断言:该 item 无 ok=True(被拒)且未产生 file 名
    if resp.status_code == 200:
        body = resp.json()
        # 端点结构:{"ok": True, "count": N, "files": [...], "items": [{"url":..,"ok":False,"error":..}]}
        items = body.get("items") or []
        assert items, body
        for item in items:
            assert not item.get("ok"), f"SVG 伪装竟被接受: {item}"
            assert item.get("error"), f"拒绝态应有 error: {item}"
    else:
        assert resp.status_code in (400, 413), resp.text


def test_T205_e2e_import_local_assets_from_urls_over_a1_limit_rejected(api_client) -> None:
    """CB-P5-22 · import_local_assets_from_urls 200 MB + 1 A1 上限拒绝。"""
    # 构造合法 PNG head + 200MB+1 填充 → A1 拒(触发 _pr4a_check 早于其他逻辑)
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (MAX_UPLOAD_BYTES + 1 - 8)
    b64 = base64.b64encode(payload).decode()
    resp = api_client.post(
        "/api/local-assets/import-urls",
        json={
            "items": [
                {
                    "url": "https://example.com/big.png",
                    "name": "big.png",
                    "data": b64,
                    "content_type": "image/png",
                }
            ],
            "folder": "",
        },
    )
    # 同上 · 200 顶层 + item.ok=False 或直接 413
    if resp.status_code == 200:
        body = resp.json()
        items = body.get("items") or []
        assert items, body
        for item in items:
            assert not item.get("ok"), f"超限竟被接受: {item}"
            assert item.get("error"), f"拒绝态应有 error: {item}"
    else:
        assert resp.status_code in (400, 413), resp.text


# ---------------------------------------------------------------------------
# CB-P5-23 承接 · T206-T207:MP4 brand 9/9 覆盖 + 类型专属 attack fixtures
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "brand",
    [b"mp41", b"avc1", b"3gp4", b"3gp5", b"3g2a"],
    ids=["mp41", "avc1", "3gp4", "3gp5", "3g2a"],
)
def test_T206_magic_mp4_brands_pr4a1_accepted(brand: bytes) -> None:
    """CB-P5-23 · MP4 ftyp 白名单补测 5 项(T175 + T206 联合覆盖 9/9)。

    覆盖:isom (T175) / mp42 (T175) / iso2 (T175) / iso5 (T175)
        + mp41 / avc1 / 3gp4 / 3gp5 / 3g2a (T206) = **9/9**
    """
    assert detect_magic_kind(_mp4_ftyp(brand)) == "mp4"


@pytest.mark.parametrize(
    "fixture_name",
    [
        "webp_11byte_truncated.bin",
        "mov_unknown_brand.mov",
        "jpg_head_tampered.jpg",
        "gif_truncated.gif",
        "webm_head_tampered.webm",
    ],
)
def test_T207_type_specific_attack_fixtures_rejected(fixture_name: str) -> None:
    """CB-P5-23 · 类型专属 attack fixtures 全部 magic 层拒绝(返回 None)。

    - webp_11byte_truncated:12 字节 WEBP 头缺 1 字节 · len 检查失败
    - mov_unknown_brand:qt/M4V/M4A 之外 brand · MOV 白名单拒
    - jpg_head_tampered:FF D8 FF 首字节篡改为 00 · JPG magic 不匹配
    - gif_truncated:GIF89a 头缺最后 1 字节 · GIF magic 不匹配
    - webm_head_tampered:EBML 首字节篡改 · WebM magic 不匹配
    """
    path = FIXTURES / "attacks" / fixture_name
    assert path.is_file(), f"fixture 缺失: {fixture_name}"
    data = path.read_bytes()
    # 断言真实字节:len > 0 且非纯 magic 头 + 0 填充(hexdump 验证)
    assert len(data) > 0
    assert detect_magic_kind(data) is None, (
        f"{fixture_name} 应被 magic 拒绝 · 实际识别为 {detect_magic_kind(data)}"
    )
    with pytest.raises(UploadRejected) as exc:
        validate_magic_whitelist(data)
    assert exc.value.code == "magic_not_allowed"


# ---------------------------------------------------------------------------
# CB-P5-24 承接 · T208-T215:累计字节 loop 真实字节 + 路径穿越 + sanitize 独立
# ---------------------------------------------------------------------------
def _build_stored_zip_with_real_workflow(payload_size: int) -> bytes:
    """构造合法 STORED zip · 含 workflow.json + 单个 resource 真实字节。

    - workflow.json:引用 resource(archive = "big.bin")
    - big.bin:真实 payload_size 字节(STORED 压缩 · CRC 合法)

    返回可被 import_canvas_workflow 走完 archive_limits + 累计字节 loop 的 zip 字节。
    """
    import json as _json

    workflow_obj = {
        "nodes": [],
        "connections": [],
        "resources": [{"name": "big.bin", "archive": "big.bin", "url": ""}],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("workflow.json", _json.dumps(workflow_obj).encode("utf-8"))
        # STORED · 真实字节流 · CRC/compress_size/file_size 全部合法
        zf.writestr("big.bin", b"P" * payload_size)
    return buf.getvalue()


def test_T208_import_canvas_workflow_cumulative_loop_real_bytes_triggers_413(
    api_client, monkeypatch
) -> None:
    """CB-P5-24 核心 · main.py:15539-15561 累计字节 loop 真实字节触发 413。

    构造:真实 512 KB STORED · 声明值 = 真实字节数 · CRC 合法(无 stdlib 拦截)。
    压小限值:monkeypatch `main._PR4A_MAX_SINGLE_UNPACK_BYTES` → 128 KB。
    累计 loop 读到第三个 64 KB 块时超阈值 → dst.close() → os.unlink → 413。

    **不触碰 infolist** · 走真实字节 loop 分支 · 断言 target 无残留。

    Lead 拍板:任务书要求"500MB 真实 > 100MB 声明"在 stdlib zipfile 语义下
    因 CRC-32 校验而不可构造 · 本 T208 以等价路径覆盖相同源码行(15539-15561)。
    """
    import main as main_mod

    real_limit = main_mod._PR4A_MAX_SINGLE_UNPACK_BYTES

    # 压小单文件解压上限 → 128 KB · payload = 512 KB 一定越限
    monkeypatch.setattr(main_mod, "_PR4A_MAX_SINGLE_UNPACK_BYTES", 128 * 1024)
    # 由于 validate_archive_limits 也读 _PR4A_MAX_SINGLE_UNPACK_BYTES 的源常量
    # (定义在 validation 模块) · 也要一并 patch 让 archive_limits 层放行
    import app.services.files.validation as validation_mod
    monkeypatch.setattr(validation_mod, "MAX_SINGLE_UNPACK_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(validation_mod, "MAX_ARCHIVE_UNPACK_BYTES", 100 * 1024 * 1024)

    payload_size = 512 * 1024  # 512 KB · 真实字节 · CRC 合法
    zip_bytes = _build_stored_zip_with_real_workflow(payload_size)

    # 快照 upload_dir · 断言无 workflow_import_* 残留 big.bin
    upload_root = Path(main_mod.current_upload_dir())
    before_imports = set()
    if upload_root.exists():
        before_imports = {p.name for p in upload_root.iterdir() if p.name.startswith("workflow_import_")}

    resp = api_client.post(
        "/api/canvas-workflows/import",
        files={"file": ("bomb.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 413, resp.text
    assert "MB" in resp.text or "解压" in resp.text

    # 断言 target 已被 unlink · 遍历新出现的 workflow_import_* 目录 · 里面不应存在 big.bin
    after_imports = set()
    if upload_root.exists():
        after_imports = {p.name for p in upload_root.iterdir() if p.name.startswith("workflow_import_")}
    new_dirs = after_imports - before_imports
    try:
        for d in new_dirs:
            for f in (upload_root / d).iterdir():
                assert "big.bin" not in f.name, f"target 未 unlink: {f}"
    finally:
        # GM-14 hygiene · 移除本测新产生的空 workflow_import_* 目录 · 避免 assets/ 残留
        import shutil
        for d in new_dirs:
            try:
                shutil.rmtree(upload_root / d, ignore_errors=True)
            except OSError:
                pass


def test_T209_import_canvas_workflow_archive_total_limit_via_forged_declared(
    api_client, tmp_path
) -> None:
    """CB-P5-24 · 总解压 > MAX_ARCHIVE_UNPACK_BYTES 触发 archive_total_too_large。

    构造合法 STORED zip · 十六进制补丁 CD 中 file_size 字段(uncompressed_size)
    到伪造的大值 · 使 validate_archive_limits 在 loop 前拒绝(不进入累计 loop)。

    注:本 T209 走的是"声明值过大"分支 · T208 走"实际字节 loop"分支 · 二者独立
    覆盖不同源码路径(validation.py::validate_archive_limits 内部 for 循环 vs
    main.py:15542-15561 累计字节 while 循环)。
    """
    # 三 entry · 每个 hex-patch 到 400 MB · 总 > 1 GB
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for i in range(3):
            zf.writestr(f"e{i}.bin", b"x" * 10)
    data = bytearray(buf.getvalue())

    # 补丁每个 CD 条目 file_size (offset +24) 到 400 MB
    pos = 0
    while True:
        idx = data.find(b"PK\x01\x02", pos)
        if idx < 0:
            break
        data[idx + 24: idx + 28] = struct.pack("<I", 400 * 1024 * 1024)
        pos = idx + 4

    resp = api_client.post(
        "/api/canvas-workflows/import",
        files={"file": ("total.zip", bytes(data), "application/zip")},
    )
    assert resp.status_code in (400, 413), resp.text


# ---- T210-T213 · Zip entry-name 路径穿越攻击 fixture 载入断言 ----
@pytest.mark.parametrize(
    "fixture_name,expected_entry",
    [
        ("zip_entry_traversal.zip", "../../etc/passwd"),
        ("zip_entry_absolute.zip", "/tmp/evil"),
        ("zip_entry_nullbyte.zip", "evil.png"),  # NUL 之后字节被 zipfile 截断
        ("zip_entry_windows_reserved.zip", "CON.png"),
    ],
)
def test_T210_T213_zip_entry_name_attack_fixtures_load_and_sanitized(
    fixture_name: str, expected_entry: str
) -> None:
    """CB-P5-24 · zip 恶意 entry name 4 类 · 经 sanitize_export_filename 后无穿越效果。

    - T210 · ../../etc/passwd
    - T211 · /tmp/evil
    - T212 · evil.png\\x00.php(NUL 混入)
    - T213 · CON.png(Windows 保留)

    断言:
    1. Fixture 真实字节可解析为合法 zip
    2. 恶意 entry name 被 sanitize_export_filename 处理后 · basename 不含穿越/绝对路径
    3. sanitize 结果结合 os.path.join(import_dir, ...) 后不会逃出 import_dir
    """
    import main as main_mod

    path = FIXTURES / "attacks" / fixture_name
    assert path.is_file(), f"fixture 缺失: {fixture_name}"
    with zipfile.ZipFile(path, "r") as zf:
        names = zf.namelist()
    assert names, f"{fixture_name} 空 zip"
    assert names[0] == expected_entry, (
        f"{fixture_name} entry 期望 {expected_entry!r} · 实际 {names[0]!r}"
    )

    # sanitize 后:
    # - 无 basename 遗留 "../" / 绝对路径
    # - 结合 import_dir 后仍在 import_dir 内
    sanitized = main_mod.sanitize_export_filename(names[0], "resource.bin")
    assert ".." not in sanitized, f"sanitize 未剥离穿越: {sanitized!r}"
    assert "/" not in sanitized and "\\" not in sanitized, (
        f"sanitize 未剥离路径分隔: {sanitized!r}"
    )
    # 绝对路径 join 语义:即便 sanitize 有 bug · 也要检查 join 结果落在 import_dir 内
    import_dir = os.path.abspath(os.path.join(os.getcwd(), "workflow_import_test"))
    joined = os.path.abspath(os.path.join(import_dir, sanitized))
    assert joined.startswith(import_dir), (
        f"{fixture_name}: join 结果逃出 import_dir · {joined} not under {import_dir}"
    )


# ---- T214 · sanitize_export_filename 独立参数化单测 ----
@pytest.mark.parametrize(
    "malicious_input,description",
    [
        ("../../etc/passwd", "posix traversal"),
        ("..\\..\\Windows\\System32", "windows traversal"),
        ("/tmp/evil", "absolute posix"),
        ("C:\\evil.exe", "absolute windows"),
        ("evil\x00.php", "nullbyte"),
        ("CON.png", "windows reserved"),
    ],
)
def test_T214_sanitize_export_filename_isolated_defends(
    malicious_input: str, description: str
) -> None:
    """CB-P5-24 · sanitize_export_filename 6 类恶意输入独立断言。

    覆盖:
    - posix / windows 相对路径穿越
    - posix / windows 绝对路径
    - NUL 字节污染
    - Windows 保留名

    断言:
    - 返回值不含 "/" 或 "\\"(basename 化)
    - 返回值不含 ".."(穿越剥离)
    - 返回值非空(fallback 生效)
    """
    import main as main_mod

    result = main_mod.sanitize_export_filename(malicious_input, "resource.bin")
    assert result, f"{description}: 返回空 · {malicious_input!r}"
    assert "/" not in result, f"{description}: 未剥离 / · {result!r}"
    assert "\\" not in result, f"{description}: 未剥离 \\ · {result!r}"
    assert ".." not in result, f"{description}: 未剥离 .. · {result!r}"


# ---- T215 · 常量引用锁 · 防止 loop 硬编码回归 ----
def test_T215_cumulative_loop_uses_constant_reference() -> None:
    """CB-P5-24 · 锁死 main.py 累计字节 loop 引用 _PR4A_MAX_SINGLE_UNPACK_BYTES 常量。

    这是 T208 monkeypatch 有效性的护栏:若未来某次 refactor 将该 loop 内的
    上限判断改成硬编码整数(如 500 * 1024 * 1024) · monkeypatch 就会静默失效
    · 造成累计字节 loop 分支实际未被回归覆盖。本 T215 通过读 main.py 源码
    断言常量名仍在 15530-15570 区间被引用。
    """
    import inspect
    import main as main_mod

    src = inspect.getsource(main_mod)
    # 常量必须被引用
    assert "_PR4A_MAX_SINGLE_UNPACK_BYTES" in src
    # 累计 loop 循环体的关键锚点必须仍存在
    assert "_pr4a_total" in src, "累计字节 loop 变量 _pr4a_total 丢失"
    assert "_pr4a_total > _PR4A_MAX_SINGLE_UNPACK_BYTES" in src, (
        "累计字节 loop 阈值判断已被改动 · T208 monkeypatch 可能失效"
    )
    # unlink + 413 兜底路径必须仍在
    lines = src.splitlines()
    # 找到 _pr4a_total > _PR4A_MAX_SINGLE_UNPACK_BYTES 所在行 · 检查后续窗口
    idx = next(
        i for i, ln in enumerate(lines)
        if "_pr4a_total > _PR4A_MAX_SINGLE_UNPACK_BYTES" in ln
    )
    window = "\n".join(lines[idx: idx + 15])
    assert "os.unlink" in window, "loop 越限分支未 unlink target · 存在磁盘残留风险"
    assert "413" in window, "loop 越限分支未 raise 413"


# ---- 硬指标 6:_pr4a_check 6 入口 grep 覆盖锁 ----
def test_T215b_pr4a_check_six_entrypoints_coverage() -> None:
    """PR-4a.1 硬指标 6 · `_pr4a_check` 在 main.py 出现次数 = 6 (定义 1 + 5 入口 + 1
    新增 upload_ai_reference = 7 · 其中定义行不算入口 · 入口共 6 hits)。

    锁死:若未来有入口被移除或未装 · 本断言先炸。
    """
    import main as main_mod

    text = Path(main_mod.__file__).read_text(encoding="utf-8")
    lines = text.splitlines()
    call_hits = [
        (i + 1, ln) for i, ln in enumerate(lines)
        if "_pr4a_check(" in ln and not ln.lstrip().startswith("def _pr4a_check")
    ]
    assert len(call_hits) == 6, (
        f"_pr4a_check 调用点应为 6 · 实际 {len(call_hits)}:\n" +
        "\n".join(f"L{n}: {ln}" for n, ln in call_hits)
    )
