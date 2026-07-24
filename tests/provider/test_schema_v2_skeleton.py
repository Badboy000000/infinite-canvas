"""Provider PR-07 schema_v2 骨架契约测试(T570-T599)。"""
from __future__ import annotations

import pytest

from app.adapters.provider.schema_v2 import (
    ApiProviderPayloadV2,
    CapabilitiesGroup,
    ConnectionGroup,
    CredentialsGroup,
    IdentityGroup,
    ModelsGroup,
    PROVIDER_SCHEMA_V2_ENABLED_ENV,
    PlatformSpecificGroup,
    RuntimeHintsGroup,
    is_schema_v2_enabled,
    v1_to_v2,
    v2_to_v1,
)


class TestEnvFlag:
    def test_T570_defaults_off(self, monkeypatch):
        monkeypatch.delenv(PROVIDER_SCHEMA_V2_ENABLED_ENV, raising=False)
        assert is_schema_v2_enabled() is False

    def test_T571_env_flag_truthy(self, monkeypatch):
        monkeypatch.setenv(PROVIDER_SCHEMA_V2_ENABLED_ENV, "true")
        assert is_schema_v2_enabled() is True


class TestGroupModels:
    def test_T572_identity_required_fields(self):
        with pytest.raises(Exception):
            IdentityGroup()  # type: ignore

    def test_T573_identity_full(self):
        g = IdentityGroup(id="p1", name="Provider 1", protocol="openai", description="desc")
        assert g.id == "p1"

    def test_T574_credentials_never_stores_api_key_by_default(self):
        g = CredentialsGroup()
        assert g.has_key is False
        assert g.key_fingerprint is None

    def test_T575_capabilities_defaults(self):
        g = CapabilitiesGroup()
        assert g.image_generate is False
        assert g.chat is False

    def test_T576_models_defaults_empty_tuple(self):
        g = ModelsGroup()
        assert g.chat_models == ()
        assert g.image_models == ()

    def test_T577_platform_specific_all_optional(self):
        g = PlatformSpecificGroup()
        assert g.volcengine is None
        assert g.runninghub is None

    def test_T578_runtime_hints_defaults(self):
        g = RuntimeHintsGroup()
        assert g.cost_class == "medium"
        assert g.recommended_poll_ms == 1000


class TestV1toV2:
    def test_T579_basic_identity_mapping(self):
        v1 = {"id": "p1", "name": "P1", "protocol": "openai"}
        v2 = v1_to_v2(v1)
        assert v2["identity"]["id"] == "p1"
        assert v2["identity"]["protocol"] == "openai"

    def test_T580_connection_grouping(self):
        v1 = {
            "id": "p1", "name": "P1", "protocol": "openai",
            "base_url": "https://api.example.com",
            "timeout": 30,
        }
        v2 = v1_to_v2(v1)
        assert v2["connection"]["base_url"] == "https://api.example.com"
        assert v2["connection"]["timeout"] == 30

    def test_T581_capabilities_grouping(self):
        v1 = {
            "id": "p1", "name": "P1", "protocol": "openai",
            "image_generate": True, "chat": True,
        }
        v2 = v1_to_v2(v1)
        assert v2["capabilities"]["image_generate"] is True
        assert v2["capabilities"]["chat"] is True

    def test_T582_platform_specific_grouping(self):
        v1 = {
            "id": "p1", "name": "P1", "protocol": "runninghub",
            "runninghub": {"workflow_id": "wf-1"},
        }
        v2 = v1_to_v2(v1)
        assert v2["platform_specific"]["runninghub"] == {"workflow_id": "wf-1"}

    @pytest.mark.parametrize(
        "secret_field",
        ["api_key", "wallet_api_key", "access_key_id", "secret_access_key"],
    )
    def test_T583_secret_fields_stripped(self, secret_field):
        """P0 密钥零泄漏:严禁字段在 v2 输出中不出现"""
        v1 = {"id": "p1", "name": "P1", "protocol": "openai", secret_field: "SECRET_VALUE"}
        v2 = v1_to_v2(v1)

        def _contains_recursive(obj, needle):
            if isinstance(obj, dict):
                return any(_contains_recursive(v, needle) for v in obj.values()) or needle in obj
            if isinstance(obj, list):
                return any(_contains_recursive(v, needle) for v in obj)
            return False

        assert not _contains_recursive(v2, secret_field), f"{secret_field} leaked into v2 output"
        # 且不出现值
        text = str(v2)
        assert "SECRET_VALUE" not in text

    def test_T584_platform_specific_strips_nested_secrets(self):
        v1 = {
            "id": "p1", "name": "P1", "protocol": "volcengine",
            "volcengine": {"access_key_id": "AKIA_SECRET", "region": "cn-north-1"},
        }
        v2 = v1_to_v2(v1)
        assert v2["platform_specific"]["volcengine"]["region"] == "cn-north-1"
        assert "access_key_id" not in v2["platform_specific"]["volcengine"]


class TestV2toV1:
    def test_T585_identity_reverse_mapping(self):
        v2 = {"identity": {"id": "p1", "name": "P1", "protocol": "openai"}}
        v1 = v2_to_v1(v2)
        assert v1["id"] == "p1"
        assert v1["name"] == "P1"

    def test_T586_full_roundtrip_idempotent(self):
        v1_original = {
            "id": "p1", "name": "P1", "protocol": "openai",
            "base_url": "https://api.example.com",
            "image_generate": True,
            "runninghub": {"workflow_id": "wf-1"},
        }
        v2 = v1_to_v2(v1_original)
        v1_back = v2_to_v1(v2)
        assert v1_back["id"] == v1_original["id"]
        assert v1_back["protocol"] == v1_original["protocol"]
        assert v1_back["base_url"] == v1_original["base_url"]
        assert v1_back["image_generate"] is True
        assert v1_back["runninghub"]["workflow_id"] == "wf-1"


class TestApiProviderPayloadV2Model:
    def test_T587_construct_from_v2_payload(self):
        v1 = {"id": "p1", "name": "P1", "protocol": "openai"}
        v2 = v1_to_v2(v1)
        model = ApiProviderPayloadV2.model_validate(v2)
        assert model.identity.id == "p1"

    def test_T588_credentials_defaults(self):
        v1 = {"id": "p1", "name": "P1", "protocol": "openai"}
        v2 = v1_to_v2(v1)
        model = ApiProviderPayloadV2.model_validate(v2)
        assert model.credentials.has_key is False


class TestContractExports:
    def test_T589_all_exports(self):
        from app.adapters.provider import schema_v2 as m

        for sym in (
            "IdentityGroup",
            "ConnectionGroup",
            "CredentialsGroup",
            "CapabilitiesGroup",
            "ModelsGroup",
            "PlatformSpecificGroup",
            "RuntimeHintsGroup",
            "ApiProviderPayloadV2",
            "v1_to_v2",
            "v2_to_v1",
            "is_schema_v2_enabled",
        ):
            assert sym in m.__all__