"""部署 PR-07 CORS 策略骨架契约测试(T600-T619)。"""
from __future__ import annotations

import pytest

from app.security.cors import (
    CORS_MODE_AWARE_ENABLED_ENV,
    CorsPolicy,
    DEFAULT_CORS_POLICY,
    build_cors_policy,
    is_cors_mode_aware_enabled,
    parse_allowed_origins,
)


class TestCorsEnvFlag:
    def test_T600_defaults_off(self, monkeypatch):
        monkeypatch.delenv(CORS_MODE_AWARE_ENABLED_ENV, raising=False)
        assert is_cors_mode_aware_enabled() is False

    def test_T601_truthy(self, monkeypatch):
        monkeypatch.setenv(CORS_MODE_AWARE_ENABLED_ENV, "true")
        assert is_cors_mode_aware_enabled() is True


class TestCorsPolicyShape:
    def test_T602_default_equivalent_to_old_behavior(self):
        """DEFAULT_CORS_POLICY 等价于旧 allow_origins=['*'] · 与旧行为等价"""
        assert DEFAULT_CORS_POLICY.allow_origins == ("*",)
        assert DEFAULT_CORS_POLICY.allow_credentials is False

    def test_T603_frozen(self):
        with pytest.raises(Exception):
            DEFAULT_CORS_POLICY.allow_origins = ("http://x.com",)  # type: ignore


class TestBuildCorsPolicyLocalPersonal:
    def test_T604_local_personal_wildcard(self):
        policy = build_cors_policy("local_personal")
        assert policy.allow_origins == ("*",)
        assert policy.allow_credentials is False  # 与 * 互斥的浏览器规范

    def test_T605_local_personal_ignores_allowed_origins(self):
        """local_personal 无视 allowed_origins 参数"""
        policy = build_cors_policy("local_personal", ["https://ignored.com"])
        assert policy.allow_origins == ("*",)


class TestBuildCorsPolicyIntranetTeam:
    def test_T606_intranet_with_origins(self):
        policy = build_cors_policy("intranet_team", ["https://intranet.example.com"])
        assert policy.allow_origins == ("https://intranet.example.com",)
        assert policy.allow_credentials is True

    def test_T607_intranet_empty_origins_returns_empty(self):
        """intranet_team 空 origin 返回空元组 · 不 fail-fast"""
        policy = build_cors_policy("intranet_team", [])
        assert policy.allow_origins == ()

    def test_T608_intranet_none_origins_returns_empty(self):
        policy = build_cors_policy("intranet_team", None)
        assert policy.allow_origins == ()


class TestBuildCorsPolicyPublicTeam:
    def test_T609_public_team_requires_origins(self):
        """public_team 空 origin fail-fast"""
        with pytest.raises(ValueError, match="public_team"):
            build_cors_policy("public_team", [])

    def test_T610_public_team_none_origins_raises(self):
        with pytest.raises(ValueError):
            build_cors_policy("public_team", None)

    def test_T611_public_team_with_valid_origins(self):
        policy = build_cors_policy(
            "public_team", ["https://prod.example.com"]
        )
        assert policy.allow_origins == ("https://prod.example.com",)
        assert policy.allow_credentials is True
        assert policy.fail_fast is True

    def test_T612_public_team_precise_methods(self):
        policy = build_cors_policy("public_team", ["https://prod.example.com"])
        assert "GET" in policy.allow_methods
        assert "POST" in policy.allow_methods
        assert "*" not in policy.allow_methods

    def test_T613_public_team_precise_headers(self):
        policy = build_cors_policy("public_team", ["https://prod.example.com"])
        assert "Authorization" in policy.allow_headers
        assert "X-CSRF-Token" in policy.allow_headers
        assert "*" not in policy.allow_headers


class TestParseAllowedOrigins:
    def test_T614_parse_comma_separated(self):
        result = parse_allowed_origins("https://a.com,https://b.com,https://c.com")
        assert result == ["https://a.com", "https://b.com", "https://c.com"]

    def test_T615_parse_strips_whitespace(self):
        result = parse_allowed_origins(" https://a.com , https://b.com ")
        assert result == ["https://a.com", "https://b.com"]

    def test_T616_parse_empty_returns_empty(self):
        assert parse_allowed_origins("") == []
        assert parse_allowed_origins(None) == []

    def test_T617_parse_filters_empty_segments(self):
        result = parse_allowed_origins("https://a.com,,https://b.com,")
        assert result == ["https://a.com", "https://b.com"]


class TestPolicyContractExports:
    def test_T618_all_exports(self):
        from app.security import cors as m

        for sym in (
            "CorsPolicy",
            "DEFAULT_CORS_POLICY",
            "build_cors_policy",
            "parse_allowed_origins",
            "is_cors_mode_aware_enabled",
            "DeploymentMode",
        ):
            assert sym in m.__all__

    def test_T619_no_fastapi_import(self):
        """骨架层不 import fastapi(生产切换归后续 PR)"""
        import inspect
        from app.security import cors

        source = inspect.getsource(cors)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import fastapi") or stripped.startswith("from fastapi"):
                pytest.fail(f"fastapi import found: {line}")