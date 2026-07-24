"""部署 PR-02 check_env_manifest 骨架契约测试(T480-T499)。"""
from __future__ import annotations

import pytest

from tools.check_env_manifest import (
    ENV_MANIFEST,
    EnvVarSpec,
    ManifestValidationResult,
    VALID_MODES,
    validate_manifest,
)


class TestManifestStructure:
    def test_T480_manifest_non_empty(self):
        assert len(ENV_MANIFEST) >= 15

    def test_T481_manifest_contains_core_key(self):
        names = [s.name for s in ENV_MANIFEST]
        assert "PUBLIC_BASE_URL" in names
        assert "IC_DEPLOYMENT_MODE" in names

    def test_T482_manifest_contains_security_keys(self):
        names = [s.name for s in ENV_MANIFEST]
        assert "IC_SESSION_SECRET" in names
        assert "IC_CORS_ALLOWED_ORIGINS" in names

    def test_T483_spec_is_frozen(self):
        spec = EnvVarSpec(name="TEST", layer="core", sensitive=False)
        with pytest.raises(Exception):
            spec.name = "OTHER"  # type: ignore[misc]

    def test_T484_result_is_frozen(self):
        r = ManifestValidationResult(
            mode="local_personal",
            missing_required=(),
            empty_optional=(),
            warnings=(),
            by_layer={},
        )
        with pytest.raises(Exception):
            r.mode = "public_team"  # type: ignore[misc]


class TestValidateLocalPersonal:
    def test_T485_local_personal_all_optional(self, monkeypatch):
        """local_personal 无必填项"""
        monkeypatch.delenv("IC_DEPLOYMENT_MODE", raising=False)
        r = validate_manifest({}, mode="local_personal")
        assert r.ok is True
        assert r.missing_required == ()

    def test_T486_local_personal_empty_optional_ok(self, monkeypatch):
        monkeypatch.setenv("IC_DEPLOYMENT_MODE", "local_personal")
        r = validate_manifest({"IC_DEPLOYMENT_MODE": "local_personal"}, mode="local_personal")
        assert r.ok is True
        # 至少有一些 empty optional
        assert len(r.empty_optional) > 0


class TestValidateIntranetTeam:
    def test_T487_intranet_team_missing_core(self, monkeypatch):
        """intranet_team 缺 PUBLIC_BASE_URL → fail"""
        r = validate_manifest({"IC_DEPLOYMENT_MODE": "intranet_team"}, mode="intranet_team")
        assert r.ok is False
        assert "PUBLIC_BASE_URL" in r.missing_required

    def test_T488_intranet_team_with_core_passes(self, monkeypatch):
        r = validate_manifest(
            {"IC_DEPLOYMENT_MODE": "intranet_team", "PUBLIC_BASE_URL": "https://team.example.com"},
            mode="intranet_team",
        )
        assert r.ok is True

    def test_T489_intranet_team_no_provider_warning(self, monkeypatch):
        r = validate_manifest(
            {"IC_DEPLOYMENT_MODE": "intranet_team", "PUBLIC_BASE_URL": "https://team.example.com"},
            mode="intranet_team",
        )
        # warning 关于 provider 密钥
        assert len(r.warnings) >= 1


class TestValidatePublicTeam:
    def test_T490_public_team_missing_security(self, monkeypatch):
        r = validate_manifest(
            {"IC_DEPLOYMENT_MODE": "public_team", "PUBLIC_BASE_URL": "https://example.com"},
            mode="public_team",
        )
        assert r.ok is False
        assert "IC_SESSION_SECRET" in r.missing_required
        assert "IC_CSRF_SECRET" in r.missing_required

    def test_T491_public_team_full_ok(self, monkeypatch):
        env = {
            "IC_DEPLOYMENT_MODE": "public_team",
            "PUBLIC_BASE_URL": "https://example.com",
            "IC_SESSION_SECRET": "s3cr3t",
            "IC_CSRF_SECRET": "csrfs3cr3t",
            "IC_CORS_ALLOWED_ORIGINS": "https://example.com",
        }
        r = validate_manifest(env, mode="public_team")
        assert r.ok is True

    def test_T492_public_team_missing_cors(self, monkeypatch):
        env = {
            "IC_DEPLOYMENT_MODE": "public_team",
            "PUBLIC_BASE_URL": "https://example.com",
            "IC_SESSION_SECRET": "s3cr3t",
            "IC_CSRF_SECRET": "csrfs3cr3t",
        }
        r = validate_manifest(env, mode="public_team")
        # IC_CORS_ALLOWED_ORIGINS 是必填
        assert "IC_CORS_ALLOWED_ORIGINS" in r.missing_required


class TestByLayer:
    def test_T493_by_layer_keys_exist(self, monkeypatch):
        r = validate_manifest({}, mode="local_personal")
        assert "core" in r.by_layer
        assert "security" in r.by_layer
        assert "storage" in r.by_layer
        assert "providers.system" in r.by_layer
        assert "logging" in r.by_layer

    def test_T494_by_layer_contains_expected_keys(self, monkeypatch):
        r = validate_manifest({}, mode="local_personal")
        assert "PUBLIC_BASE_URL" in r.by_layer["core"]
        assert "IC_SESSION_SECRET" in r.by_layer["security"]


class TestInvalidMode:
    def test_T495_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            validate_manifest({}, mode="invalid")  # type: ignore


class TestContractExports:
    def test_T496_valid_modes(self):
        assert "local_personal" in VALID_MODES
        assert "intranet_team" in VALID_MODES
        assert "public_team" in VALID_MODES

    def test_T497_manifest_has_correct_layers(self):
        layers = {s.layer for s in ENV_MANIFEST}
        assert "core" in layers
        assert "security" in layers
        assert "storage" in layers
        assert "providers.system" in layers
        assert "logging" in layers

    def test_T498_sensitive_flag_set_for_keys(self):
        sensitive_keys = {s.name for s in ENV_MANIFEST if s.sensitive}
        assert "IC_SESSION_SECRET" in sensitive_keys
        assert "COMFLY_API_KEY" in sensitive_keys
        assert "PUBLIC_BASE_URL" not in sensitive_keys

    def test_T499_cli_help(self):
        """CLI 至少可解析 --help"""
        from tools.check_env_manifest import main

        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0