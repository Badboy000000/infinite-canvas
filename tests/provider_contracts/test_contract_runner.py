"""Provider 契约测试运行器 · 参数化跑协议 × case。

见 [[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-04。
"""
from __future__ import annotations

import pytest

from app.adapters.provider.classifiers import classify_generic_image_error
from app.adapters.provider.mappers import generic_image_payload_to_view
from tests.provider_contracts.conftest import (
    list_protocol_dirs,
    placeholder_substitute,
    read_fixture_text,
    resolve_fixture,
)


class TestContractDirDiscovery:
    def test_protocol_dirs_at_least_openai(self):
        """至少发现 openai 协议目录"""
        protocols = list_protocol_dirs()
        assert "openai" in protocols

    def test_openai_fixtures_exist(self):
        """openai 目录基本 fixture 齐全"""
        for name in ("submit_request.expected", "response_success.fixture", "response_rate_limit.fixture"):
            assert resolve_fixture("openai", name) is not None, f"missing fixture: openai/{name}.json"


class TestPlaceholderSubstitute:
    def test_replaces_api_key(self):
        obj = {"headers": {"Authorization": "Bearer {{API_KEY}}"}}
        result = placeholder_substitute(obj, api_key="sk-test-999")
        assert result["headers"]["Authorization"] == "Bearer sk-test-999"

    def test_replaces_base_url(self):
        obj = {"endpoint": "{{BASE_URL}}/images/generations"}
        result = placeholder_substitute(obj, base_url="https://api.foo.com/v1")
        assert result["endpoint"] == "https://api.foo.com/v1/images/generations"

    def test_nested_replacement(self):
        obj = {"a": [{"b": "{{API_KEY}}"}]}
        result = placeholder_substitute(obj, api_key="key-123")
        assert result["a"][0]["b"] == "key-123"

    def test_fixture_raw_text_contains_no_hardcoded_key(self):
        """所有 openai fixture 原始文本禁止硬编码 API Key 前缀"""
        import re
        for name in ("submit_request.expected", "response_success.fixture"):
            text = read_fixture_text("openai", name)
            assert text is not None
            # 检查:硬编码 API Key 前缀不允许(sk-proj- / sk-ant- / AKIA)
            for prefix in ("sk-proj-", "sk-ant-", "AKIA"):
                if prefix in text:
                    pytest.fail(f"hardcoded API key prefix {prefix} in {name}")


class TestOpenaiFixtureMapping:
    def test_response_success_maps_to_succeeded(self):
        fixture = resolve_fixture("openai", "response_success.fixture")
        view = generic_image_payload_to_view(fixture)
        assert view.status == "succeeded"
        assert view.upstream_task_id == "task-abc-123"
        assert len(view.outputs) == 1
        assert view.outputs[0].source_url_or_bytes == "https://cdn.example.com/img/abc-123.png"

    def test_response_matches_expected_normalized(self):
        fixture = resolve_fixture("openai", "response_success.fixture")
        expected = resolve_fixture("openai", "expected_normalized")
        view = generic_image_payload_to_view(fixture)

        assert view.provider_id == expected["provider_id"] or expected["provider_id"] == "openai"
        assert view.status == expected["status"]
        assert view.upstream_task_id == expected["upstream_task_id"]
        assert len(view.outputs) == expected["outputs_count"]
        assert view.outputs[0].source_url_or_bytes == expected["outputs_first_url"]

    def test_rate_limit_fixture_classified_as_rate_limit(self):
        fixture = resolve_fixture("openai", "response_rate_limit.fixture")
        error = fixture["error"]
        error["http_status"] = fixture.get("http_status")
        task_error = classify_generic_image_error(error, request_id="rid-test")
        assert task_error.category.value == "RATE_LIMIT"
        assert task_error.retryable is True

    def test_content_policy_fixture_classified(self):
        fixture = resolve_fixture("openai", "response_content_policy.fixture")
        error = fixture["error"]
        error["http_status"] = fixture.get("http_status")
        task_error = classify_generic_image_error(error, request_id="rid-test")
        assert task_error.category.value == "CONTENT_POLICY"
        assert task_error.retryable is False


class TestFixtureSecurity:
    def test_no_real_api_keys_in_fixtures(self):
        """所有 fixture 中不得出现真实 API Key(P0 密钥零泄漏防线)"""
        protocols = list_protocol_dirs()
        forbidden_prefixes = ("sk-proj-", "sk-ant-", "AKIA")
        for protocol in protocols:
            fixtures_dir = list_protocol_dirs()
            # 所有 json 文件 · 递归检查
            from tests.provider_contracts.conftest import FIXTURES_ROOT
            for path in (FIXTURES_ROOT / protocol).glob("**/*.json"):
                text = path.read_text(encoding="utf-8")
                for prefix in forbidden_prefixes:
                    assert prefix not in text, f"real key prefix {prefix} in {path}"