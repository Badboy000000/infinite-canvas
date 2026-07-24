"""部署 PR-04 zip_guard 骨架契约测试(T420-T439)。"""
from __future__ import annotations

import pytest

from app.security.zip_guard import (
    DEFAULT_ZIP_POLICY,
    ZIP_GUARD_ENFORCE_ENV,
    ZipDecision,
    ZipEntryMeta,
    ZipGuardPolicy,
    inspect_zip_entries,
    is_zip_guard_enforce_enabled,
    normalize_zip_entry_path,
)


class TestZipGuardEnvFlag:
    def test_T420_env_flag_defaults_off(self, monkeypatch):
        monkeypatch.delenv(ZIP_GUARD_ENFORCE_ENV, raising=False)
        assert is_zip_guard_enforce_enabled() is False

    def test_T421_env_flag_truthy(self, monkeypatch):
        monkeypatch.setenv(ZIP_GUARD_ENFORCE_ENV, "true")
        assert is_zip_guard_enforce_enabled() is True


class TestZipDecisionShape:
    def test_T422_decision_is_frozen(self):
        d = ZipDecision(accepted=True, reason="accepted")
        with pytest.raises(Exception):
            d.accepted = False  # type: ignore[misc]

    def test_T423_policy_is_frozen(self):
        with pytest.raises(Exception):
            DEFAULT_ZIP_POLICY.max_entries = 1  # type: ignore[misc]


class TestInspectZipEntries:
    def _entry(self, name, uncompressed=100, compressed=50, is_symlink=False):
        return ZipEntryMeta(
            filename=name,
            compressed_size=compressed,
            uncompressed_size=uncompressed,
            is_symlink=is_symlink,
        )

    def test_T424_accepts_small_zip(self):
        ents = [self._entry("file.txt", 100, 50)]
        d = inspect_zip_entries(ents)
        assert d.accepted is True
        assert d.reason == "accepted"
        assert d.total_uncompressed == 100
        assert d.entry_count == 1

    def test_T425_too_many_entries_rejected(self):
        ents = [
            self._entry(f"f{i}.txt", 10, 9) for i in range(DEFAULT_ZIP_POLICY.max_entries + 1)
        ]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "too_many_entries"

    def test_T426_single_entry_oversize_rejected(self):
        ents = [self._entry("big.bin", DEFAULT_ZIP_POLICY.max_single_entry_bytes + 1, 100)]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "oversize_single_entry"
        assert d.offending_entry == "big.bin"

    def test_T427_bomb_ratio_rejected(self):
        """80MB 解压 / 100KB 压缩 = ratio 800 > 200(且单条 < 100MB)"""
        ents = [self._entry("bomb.dat", 80 * 1024 * 1024, 100 * 1024)]  # 80MB uncompressed, 100KB compressed
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "bomb_ratio"
        assert d.offending_entry == "bomb.dat"

    def test_T428_zero_compressed_uncompressed_positive(self):
        """compressed=0 · uncompressed>0 → bomb(file infinite)"""
        ents = [self._entry("bomb.dat", 1000, 0)]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "bomb_ratio"
        assert d.detected_ratio == float("inf")

    def test_T429_total_uncompressed_oversize(self):
        """3 个 70MB 条 = 210MB > 200MB · 单条 70MB < 100MB · ratio 70 < 200"""
        ents = [
            self._entry("seg1.bin", 70 * 1024 * 1024, 1024 * 1024),  # 70MB uncompressed, 1MB compressed
            self._entry("seg2.bin", 70 * 1024 * 1024, 1024 * 1024),
            self._entry("seg3.bin", 70 * 1024 * 1024, 1024 * 1024),
        ]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "oversize_total_uncompressed"

    def test_T430_symlink_rejected_by_default(self):
        ents = [self._entry("link.txt", 10, 10, is_symlink=True)]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "symlink"
        assert d.offending_entry == "link.txt"

    def test_T431_symlink_allowed_when_policy_says(self):
        policy = ZipGuardPolicy(allow_symlinks=True)
        ents = [self._entry("link.txt", 10, 10, is_symlink=True)]
        d = inspect_zip_entries(ents, policy=policy)
        assert d.accepted is True

    def test_T432_path_escape_rejected(self):
        ents = [self._entry("../../etc/passwd", 100, 50)]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "path_escape"
        assert d.offending_entry == "../../etc/passwd"

    def test_T433_absolute_path_rejected(self):
        ents = [self._entry("/etc/passwd", 100, 50)]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "absolute_path"

    def test_T434_windows_absolute_path_rejected(self):
        ents = [self._entry("C:/Windows/system32/evil.dll", 100, 50)]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "absolute_path"

    def test_T435_backslash_normalized(self):
        """反斜杠路径统一判断"""
        ents = [self._entry("..\\..\\etc\\passwd", 100, 50)]
        d = inspect_zip_entries(ents)
        assert d.accepted is False
        assert d.reason == "path_escape"


class TestNormalizePath:
    def test_T436_safe_path_normalizes(self):
        safe, norm = normalize_zip_entry_path("safe/dir/file.txt", "/tmp/dest")
        assert safe is True
        assert norm == "safe/dir/file.txt"

    def test_T437_escape_returns_false(self):
        safe, _ = normalize_zip_entry_path("../../etc/passwd", "/tmp/dest")
        assert safe is False

    def test_T438_absolute_returns_false(self):
        safe, _ = normalize_zip_entry_path("/etc/passwd", "/tmp/dest")
        assert safe is False

    def test_T439_empty_name_is_safe(self):
        safe, norm = normalize_zip_entry_path("", "/tmp/dest")
        assert safe is True
        assert norm == ""


class TestContractExports:
    def test_T439b_all_exports(self):
        from app.security import zip_guard as m

        for sym in (
            "ZipGuardPolicy",
            "ZipDecision",
            "ZipEntryMeta",
            "inspect_zip_entries",
            "normalize_zip_entry_path",
            "is_zip_guard_enforce_enabled",
            "DEFAULT_ZIP_POLICY",
        ):
            assert sym in m.__all__, f"{sym} missing from __all__"