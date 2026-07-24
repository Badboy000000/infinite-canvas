"""部署 PR-10 redaction 骨架契约测试(T460-T479)。"""
from __future__ import annotations

import pytest

from app.logging.redaction import (
    LOG_REDACTION_ENABLED_ENV,
    REDACTION_MARKER,
    SENSITIVE_HEADERS,
    SENSITIVE_QUERY_KEYS,
    is_log_redaction_enabled,
    redact_headers,
    redact_query_string,
    redact_text,
    redact_url_full,
)


class TestRedactionEnvFlag:
    def test_T460_env_flag_defaults_off(self, monkeypatch):
        monkeypatch.delenv(LOG_REDACTION_ENABLED_ENV, raising=False)
        assert is_log_redaction_enabled() is False

    def test_T461_env_flag_truthy(self, monkeypatch):
        monkeypatch.setenv(LOG_REDACTION_ENABLED_ENV, "true")
        assert is_log_redaction_enabled() is True


class TestRedactHeaders:
    def test_T462_authorization_redacted(self):
        headers = {"Authorization": "Bearer sk-secret-key-12345"}
        result = redact_headers(headers)
        assert result["Authorization"] == REDACTION_MARKER

    def test_T463_x_api_key_redacted(self):
        headers = {"X-API-Key": "my-secret-key"}
        result = redact_headers(headers)
        assert result["X-API-Key"] == REDACTION_MARKER

    def test_T464_cookie_redacted(self):
        headers = {"Cookie": "session=abc123"}
        result = redact_headers(headers)
        assert result["Cookie"] == REDACTION_MARKER

    def test_T465_innocent_header_preserved(self):
        headers = {"Content-Type": "application/json"}
        result = redact_headers(headers)
        assert result["Content-Type"] == "application/json"

    def test_T466_case_insensitive(self):
        headers = {"authorization": "Bearer token"}
        result = redact_headers(headers)
        assert result["authorization"] == REDACTION_MARKER

    def test_T467_empty_headers(self):
        assert redact_headers({}) == {}

    def test_T468_set_cookie_redacted(self):
        headers = {"Set-Cookie": "session=abc; HttpOnly"}
        result = redact_headers(headers)
        assert result["Set-Cookie"] == REDACTION_MARKER


class TestRedactQueryString:
    def test_T469_signature_redacted(self):
        """敏感 key 值脱敏 · 非敏感 key 值保留"""
        qs = "X-Amz-Signature=abc123&page=1&limit=20"
        result = redact_query_string(qs)
        assert "X-Amz-Signature" in result
        assert "abc123" not in result
        assert "page=1" in result
        assert "limit=20" in result

    def test_T470_api_key_redacted(self):
        qs = "api_key=sk-secret&other=ok"
        result = redact_query_string(qs)
        assert "api_key=" in result
        assert "sk-secret" not in result
        assert "other=ok" in result

    def test_T471_token_redacted(self):
        qs = "token=mysecrettoken&keep=this"
        result = redact_query_string(qs)
        assert "token=" in result
        assert "mysecrettoken" not in result
        assert "keep=this" in result

    def test_T472_empty_qs(self):
        assert redact_query_string("") == ""

    def test_T473_no_sensitive_keys(self):
        qs = "page=1&limit=20&filter=name"
        assert redact_query_string(qs) == qs

    def test_T474_url_without_query(self):
        assert redact_url_full("https://example.com/path") == "https://example.com/path"

    def test_T475_url_with_query_redacted(self):
        url = "https://example.com/files?id=123&token=secret"
        result = redact_url_full(url)
        assert "token=" in result
        assert "secret" not in result
        assert "id=123" in result


class TestRedactText:
    def test_T476_authorization_bearer_redacted(self):
        text = 'Authorization: Bearer sk-abc123def456ghijklmnopqrstuvwxyz'
        result = redact_text(text)
        assert "sk-abc123def456ghijklmnopqrstuvwxyz" not in result
        assert REDACTION_MARKER in result

    def test_T477_api_key_value_redacted(self):
        text = 'api_key=my-secret-key-value'
        result = redact_text(text)
        assert "my-secret-key-value" not in result
        assert REDACTION_MARKER in result

    def test_T478_sk_token_redacted(self):
        """sk- 前缀 >= 20 字符的 token 被正则捕获"""
        text = 'openai_key="sk-1234567890123456789012345678901234567890"'
        result = redact_text(text)
        assert "sk-1234567890123456789012345678901234567890" not in result
        assert REDACTION_MARKER in result

    def test_T479_short_sk_token_less_than_20(self):
        """sk-< 20 字符的短 key 不被正则捕获(避免误伤短 ID)"""
        text = 'short="sk-12345"'
        result = redact_text(text)
        assert "sk-12345" in result

    def test_T479b_empty_text(self):
        assert redact_text("") == ""

    def test_T479c_clean_text(self):
        text = "normal log line without sensitive data"
        assert redact_text(text) == text


class TestContractExports:
    def test_T479d(self):
        from app.logging import redaction as m

        for sym in (
            "LOG_REDACTION_ENABLED_ENV",
            "REDACTION_MARKER",
            "SENSITIVE_HEADERS",
            "SENSITIVE_QUERY_KEYS",
            "redact_headers",
            "redact_query_string",
            "redact_text",
            "redact_url_full",
            "is_log_redaction_enabled",
        ):
            assert sym in m.__all__, f"{sym} missing from __all__"

    def test_T479e_sensitive_headers_frozen(self):
        with pytest.raises(Exception):
            SENSITIVE_HEADERS.add("new-header")  # type: ignore[misc]

    def test_T479f_sensitive_query_keys_frozen(self):
        with pytest.raises(Exception):
            SENSITIVE_QUERY_KEYS.add("new-key")  # type: ignore[misc]