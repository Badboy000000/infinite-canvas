"""部署 PR-03 upload_guard 骨架契约测试(T400-T419)。"""
from __future__ import annotations

import pytest

from app.security.upload_guard import (
    DEFAULT_UPLOAD_POLICY,
    UPLOAD_GUARD_ENFORCE_ENV,
    UploadDecision,
    UploadGuardPolicy,
    check_upload,
    guess_mime_from_magic,
    is_upload_guard_enforce_enabled,
)


class TestUploadGuardEnvFlag:
    def test_T400_env_flag_defaults_off(self, monkeypatch):
        """UPLOAD_GUARD_ENFORCE 默认 false"""
        monkeypatch.delenv(UPLOAD_GUARD_ENFORCE_ENV, raising=False)
        assert is_upload_guard_enforce_enabled() is False

    def test_T401_env_flag_truthy_values(self, monkeypatch):
        """1 / true / yes / on / TRUE 均视为 on"""
        for v in ("1", "true", "yes", "on", "TRUE"):
            monkeypatch.setenv(UPLOAD_GUARD_ENFORCE_ENV, v)
            assert is_upload_guard_enforce_enabled() is True


class TestMagicSignatures:
    @pytest.mark.parametrize(
        "head,expected_mime,expected_cat",
        [
            (b"\xff\xd8\xff\xe0somemore", "image/jpeg", "image"),
            (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "image/png", "image"),
            (b"GIF89a" + b"\x00" * 10, "image/gif", "image"),
            (b"PK\x03\x04" + b"\x00" * 12, "application/zip", "zip"),
            (b"BM" + b"\x00" * 14, "image/bmp", "image"),
        ],
        ids=["jpeg", "png", "gif", "zip", "bmp"],
    )
    def test_T402_magic_detects_common_formats(self, head, expected_mime, expected_cat):
        result = guess_mime_from_magic(head)
        assert result == (expected_mime, expected_cat)

    def test_T403_magic_unknown_returns_none(self):
        assert guess_mime_from_magic(b"not-a-known-format") is None

    def test_T404_magic_empty_returns_none(self):
        assert guess_mime_from_magic(b"") is None

    def test_T405_magic_detects_svg(self):
        """SVG 侦测(用于返回 svg_disabled reason)"""
        assert guess_mime_from_magic(b"<?xml version='1.0'?>\n<svg xmlns=") == (
            "image/svg+xml",
            "svg",
        )
        assert guess_mime_from_magic(b"<svg width='10'>") == (
            "image/svg+xml",
            "svg",
        )


class TestUploadCheck:
    def _mk_head(self, kind: str) -> bytes:
        return {
            "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 12,
            "png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 8,
            "zip": b"PK\x03\x04" + b"\x00" * 12,
            "svg": b"<svg width='10'>",
        }[kind]

    def test_T406_accepts_valid_image(self):
        d = check_upload(
            filename="hello.jpg",
            size=1024,
            head_bytes=self._mk_head("jpeg"),
            declared_mime="image/jpeg",
        )
        assert d.accepted is True
        assert d.reason == "accepted"
        assert d.matched_mime == "image/jpeg"

    def test_T407_double_extension_rejected(self):
        d = check_upload(
            filename="innocent.jpg.exe",
            size=1024,
            head_bytes=self._mk_head("jpeg"),
        )
        assert d.accepted is False
        assert d.reason == "ext_double"

    def test_T408_magic_unknown_rejected(self):
        d = check_upload(
            filename="mystery.bin",
            size=100,
            head_bytes=b"\x00" * 20,
        )
        assert d.accepted is False
        assert d.reason == "magic_unknown"

    def test_T409_svg_default_rejected(self):
        d = check_upload(
            filename="logo.svg",
            size=100,
            head_bytes=self._mk_head("svg"),
        )
        assert d.accepted is False
        assert d.reason == "svg_disabled"

    def test_T410_svg_allowed_when_policy_says_so(self):
        policy = UploadGuardPolicy(allow_svg=True)
        d = check_upload(
            filename="logo.svg",
            size=100,
            head_bytes=self._mk_head("svg"),
            policy=policy,
        )
        # allow_svg=True 且 magic 命中 svg · category='svg' 无对应 size 上限走 generic
        assert d.accepted is True or d.reason == "accepted"

    def test_T411_mime_mismatch_rejected(self):
        """png magic + 声明 video/mp4 → mime_mismatch"""
        d = check_upload(
            filename="fake.mp4",
            size=100,
            head_bytes=self._mk_head("png"),
            declared_mime="video/mp4",
        )
        assert d.accepted is False
        assert d.reason == "mime_mismatch"

    def test_T412_oversize_image_rejected(self):
        d = check_upload(
            filename="huge.jpg",
            size=DEFAULT_UPLOAD_POLICY.image_max_bytes + 1,
            head_bytes=self._mk_head("jpeg"),
        )
        assert d.accepted is False
        assert d.reason == "oversize"
        assert d.limit_bytes == DEFAULT_UPLOAD_POLICY.image_max_bytes

    def test_T413_zip_size_uses_zip_limit(self):
        d = check_upload(
            filename="pack.zip",
            size=100,
            head_bytes=self._mk_head("zip"),
        )
        assert d.accepted is True
        assert d.matched_mime == "application/zip"

    def test_T414_declared_mime_missing_still_ok(self):
        d = check_upload(
            filename="a.png",
            size=100,
            head_bytes=self._mk_head("png"),
            declared_mime=None,
        )
        assert d.accepted is True


class TestUploadDecisionShape:
    def test_T415_decision_is_frozen(self):
        d = UploadDecision(accepted=True, reason="accepted")
        with pytest.raises(Exception):
            d.accepted = False  # type: ignore[misc]

    def test_T416_policy_is_frozen(self):
        with pytest.raises(Exception):
            DEFAULT_UPLOAD_POLICY.image_max_bytes = 1  # type: ignore[misc]


class TestUploadDoubleExtensions:
    @pytest.mark.parametrize(
        "fname",
        [
            "photo.jpg.exe",
            "PHOTO.JPG.EXE",
            "archive.zip.exe",
            "malware.png.svg",
            "shell.php.jpg",
            "backdoor.jsp.jpg",
        ],
        ids=["jpg.exe", "JPG.EXE", "zip.exe", "png.svg", "php.jpg", "jsp.jpg"],
    )
    def test_T417_common_double_extensions_rejected(self, fname):
        d = check_upload(
            filename=fname,
            size=100,
            head_bytes=b"\xff\xd8\xff\xe0" + b"\x00" * 12,
        )
        assert d.accepted is False
        assert d.reason == "ext_double"


class TestContractExports:
    def test_T418_all_exports(self):
        from app.security import upload_guard as m

        for sym in (
            "UploadGuardPolicy",
            "UploadDecision",
            "check_upload",
            "guess_mime_from_magic",
            "is_upload_guard_enforce_enabled",
            "DEFAULT_UPLOAD_POLICY",
        ):
            assert sym in m.__all__, f"{sym} missing from __all__"

    def test_T419_no_pil_import_in_upload_guard(self):
        """骨架层严禁 import PIL"""
        import inspect

        from app.security import upload_guard

        source = inspect.getsource(upload_guard)
        assert "from PIL" not in source
        assert "import PIL" not in source
