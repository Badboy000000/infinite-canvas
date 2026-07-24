"""部署 PR-05 pillow_guard 骨架契约测试(T440-T459)。"""
from __future__ import annotations

import pytest

from app.security.pillow_guard import (
    DEFAULT_PILLOW_POLICY,
    PILLOW_GUARD_ENFORCE_ENV,
    PillowDecision,
    PillowGuardPolicy,
    check_image_dimensions,
    estimate_pixel_bytes,
    is_pillow_guard_enforce_enabled,
)


class TestPillowGuardEnvFlag:
    def test_T440_env_flag_defaults_off(self, monkeypatch):
        monkeypatch.delenv(PILLOW_GUARD_ENFORCE_ENV, raising=False)
        assert is_pillow_guard_enforce_enabled() is False

    def test_T441_env_flag_truthy(self, monkeypatch):
        monkeypatch.setenv(PILLOW_GUARD_ENFORCE_ENV, "true")
        assert is_pillow_guard_enforce_enabled() is True


class TestEstimatePixelBytes:
    def test_T442_estimate_rgba(self):
        assert estimate_pixel_bytes(100, 100, 4) == 40_000

    def test_T443_estimate_rgb(self):
        assert estimate_pixel_bytes(100, 100, 3) == 30_000

    def test_T444_estimate_zero_dimension(self):
        assert estimate_pixel_bytes(0, 100, 4) == 0
        assert estimate_pixel_bytes(100, 0, 4) == 0

    def test_T445_estimate_large_image(self):
        """4000x3000 RGBA ≈ 48 MB"""
        est = estimate_pixel_bytes(4000, 3000, 4)
        assert est == 48_000_000

    def test_T446_estimate_negative_channels(self):
        assert estimate_pixel_bytes(100, 100, -1) == 0


class TestCheckImageDimensions:
    def test_T447_accepts_normal_image(self):
        d = check_image_dimensions(width=1920, height=1080, channels=3)
        assert d.accepted is True
        assert d.reason == "accepted"
        assert d.total_pixels == 2_073_600

    def test_T448_invalid_dimension_rejected(self):
        d = check_image_dimensions(width=0, height=1080)
        assert d.accepted is False
        assert d.reason == "invalid_dimension"

    def test_T449_oversize_dimension_rejected(self):
        d = check_image_dimensions(
            width=DEFAULT_PILLOW_POLICY.max_dimension + 1,
            height=100,
        )
        assert d.accepted is False
        assert d.reason == "oversize_dimension"

    def test_T450_oversize_pixels_rejected(self):
        d = check_image_dimensions(
            width=10000,
            height=10000,
        )
        assert d.accepted is False
        assert d.reason == "oversize_pixels"
        assert d.total_pixels == 100_000_000

    def test_T451_oversize_estimate_bytes_rejected(self):
        """30M pixels × 4 channels × 4 bytes = 480 MB < 512 MB · 需要缩小 max_bytes_estimate"""
        policy = PillowGuardPolicy(max_bytes_estimate=10_000_000)  # 10 MB 上限
        d = check_image_dimensions(
            width=2000,
            height=2000,
            channels=4,
            policy=policy,
        )
        assert d.accepted is False
        assert d.reason == "oversize_estimate_bytes"
        assert d.estimated_bytes == 16_000_000

    def test_T452_policy_custom_max_pixels(self):
        policy = PillowGuardPolicy(max_pixels=1000)
        d = check_image_dimensions(width=30, height=30, policy=policy)
        assert d.accepted is True
        d2 = check_image_dimensions(width=30, height=30, policy=policy, channels=1)
        assert d2.accepted is True
        d3 = check_image_dimensions(width=30, height=30, policy=policy, channels=2)
        assert d3.accepted is True

    def test_T453_default_channels_rgba(self):
        d = check_image_dimensions(width=10, height=10)
        assert d.channels == 4


class TestPillowDecisionShape:
    def test_T454_decision_is_frozen(self):
        d = PillowDecision(accepted=True, reason="accepted")
        with pytest.raises(Exception):
            d.accepted = False  # type: ignore[misc]

    def test_T455_policy_is_frozen(self):
        with pytest.raises(Exception):
            DEFAULT_PILLOW_POLICY.max_pixels = 1  # type: ignore[misc]


class TestNoPilImport:
    def test_T456_no_pil_import_in_pillow_guard(self):
        """骨架层严禁 import PIL/Pillow(检查行级 import 语句)"""
        import inspect

        from app.security import pillow_guard

        source = inspect.getsource(pillow_guard)
        # 检查模块级 import 语句 · 非 docstring 子串
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import PIL") or stripped.startswith("from PIL"):
                pytest.fail(f"PIL import found: {line}")

    def test_T457_no_pil_import_in_entire_security_package(self):
        import inspect

        from app.security import upload_guard, zip_guard, pillow_guard

        for mod in (upload_guard, zip_guard, pillow_guard):
            for line in inspect.getsource(mod).splitlines():
                stripped = line.strip()
                if stripped.startswith("import PIL") or stripped.startswith("from PIL"):
                    pytest.fail(f"PIL import found in {mod.__name__}: {line}")


class TestContractExports:
    def test_T458_all_exports(self):
        from app.security import pillow_guard as m

        for sym in (
            "PillowGuardPolicy",
            "PillowDecision",
            "check_image_dimensions",
            "estimate_pixel_bytes",
            "is_pillow_guard_enforce_enabled",
            "DEFAULT_PILLOW_POLICY",
        ):
            assert sym in m.__all__, f"{sym} missing from __all__"

    def test_T459_decisions_include_metadata(self):
        d = check_image_dimensions(width=1920, height=1080, channels=4)
        assert d.width == 1920
        assert d.height == 1080
        assert d.channels == 4
        assert d.estimated_bytes == 1920 * 1080 * 4