"""CB-P5-02 + CB-P5-03 · sanitize_raw_excerpt 值层扫描升级(数据 PR-16 · Wave 3-L 主线 C)。

覆盖点(T110-T115 共 6 项):

- T110 CB-P5-02:`akira` / `akihabara` 等 `aki` 起头的合法业务字符串不再误脱敏
- T111 CB-P5-02:AWS access key `AKIA[0-9A-Z]{16}` 前缀仍正确脱敏
- T112 CB-P5-02:AWS temporary access key `ASIA[0-9A-Z]{16}` 前缀正确脱敏
- T113 CB-P5-03:字符串中间的 `sk-{16,}` 命中正确脱敏(原 startswith 不覆盖)
- T114 CB-P5-03:Provider error message payload 中的 secret 字面量整值脱敏
- T115 CB-P5-03:regression · 原 sk- prefix / Bearer prefix 判定保留
"""

from __future__ import annotations

import pytest

from app.task.view.provider_view import (
    _looks_like_secret_value,
    sanitize_raw_excerpt,
    _SECRET_VALUE_MARKERS,
    _SECRET_VALUE_REGEX_PATTERNS,
)


# ---------------------------------------------------------------------------
# T110 · CB-P5-02 · aki 前缀过宽误伤修复
# ---------------------------------------------------------------------------


def test_t110_cbp502_akira_akihabara_not_false_positive() -> None:
    """`akira` / `akihabara` 等以 `aki` 起头的合法业务字符串不应被误脱敏。"""
    assert _looks_like_secret_value("akira") is False
    assert _looks_like_secret_value("akihabara") is False
    assert _looks_like_secret_value("Akira Model 3") is False
    assert _looks_like_secret_value("AKIHABARA-district") is False
    # 通过 sanitize_raw_excerpt 也不应命中
    sanitized = sanitize_raw_excerpt({"brand_name": "akira", "location": "akihabara"})
    assert sanitized == {"brand_name": "akira", "location": "akihabara"}


# ---------------------------------------------------------------------------
# T111 · CB-P5-02 · AKIA 4 字符官方前缀仍命中
# ---------------------------------------------------------------------------


def test_t111_cbp502_akia_prefix_still_matches() -> None:
    """AWS long-term access key `AKIA{16}` 前缀应正确脱敏。"""
    assert _looks_like_secret_value("AKIA0123456789ABCDEF") is True
    assert _looks_like_secret_value("akia0123456789ABCDEF") is True  # lowered
    # marker 表已经改为 4 字符
    assert "akia" in _SECRET_VALUE_MARKERS
    assert "aki" not in _SECRET_VALUE_MARKERS


# ---------------------------------------------------------------------------
# T112 · CB-P5-02 · ASIA temporary access key 前缀命中
# ---------------------------------------------------------------------------


def test_t112_cbp502_asia_prefix_matches() -> None:
    """AWS temporary session access key `ASIA{16}` 前缀应正确脱敏。"""
    assert _looks_like_secret_value("ASIA0123456789ABCDEF") is True
    assert _looks_like_secret_value("asia0123456789ABCDEF") is True
    assert "asia" in _SECRET_VALUE_MARKERS


# ---------------------------------------------------------------------------
# T113 · CB-P5-03 · 字符串中间的 sk- 命中(值内容正则扫描)
# ---------------------------------------------------------------------------


def test_t113_cbp503_sk_secret_in_middle_of_string() -> None:
    """字符串中间含 `sk-{16,}` 应通过正则扫描命中脱敏。"""
    # 原 startswith 判据不命中(不以 sk- 开头)
    value = "Error: Invalid api_key='sk-abcdefghij0123456789'"
    assert _looks_like_secret_value(value) is True

    # 短 sk- 前缀不误伤(fixture / sample)
    assert _looks_like_secret_value("sk-test") is True  # startswith 命中(保留原行为)
    # 但 sk- 后面短于 16 字符时正则不命中(仅 startswith 覆盖)
    # sk- 后随机短字符
    assert _looks_like_secret_value("value contains sk-abc") is False  # 中间 · 短 · 不命中


# ---------------------------------------------------------------------------
# T114 · CB-P5-03 · Provider error message payload sanitize
# ---------------------------------------------------------------------------


def test_t114_cbp503_provider_error_message_payload_sanitized() -> None:
    """Provider 错误消息 payload 中的 secret 字面量应整值脱敏。"""
    payload = {
        "message": "Invalid api_key='sk-abcdefghij0123456789'",
        "code": "E1002",
        "safe_field": "some ordinary text",
    }
    sanitized = sanitize_raw_excerpt(payload)
    assert sanitized["message"] == "[REDACTED]"
    assert sanitized["code"] == "E1002"  # 未误伤
    assert sanitized["safe_field"] == "some ordinary text"  # 未误伤

    # AKIA in middle
    payload2 = {"log_line": "AWS request failed with key AKIA0123456789ABCDEF"}
    sanitized2 = sanitize_raw_excerpt(payload2)
    assert sanitized2["log_line"] == "[REDACTED]"

    # Bearer in middle
    payload3 = {"trace": "Authorization: Bearer abc.def.ghi received"}
    sanitized3 = sanitize_raw_excerpt(payload3)
    assert sanitized3["trace"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# T115 · regression · 保留原有 startswith 判据
# ---------------------------------------------------------------------------


def test_t115_regression_original_prefix_judgments_preserved() -> None:
    """CB-P5-02/03 不得破坏原有 sk- / Bearer 前缀判定行为。"""
    # 原 sk- 起头(治理期 sample fixture)
    assert _looks_like_secret_value("sk-test-key") is True
    assert _looks_like_secret_value("sk-SMOKE-TEST-DO-NOT-LOG") is True

    # 原 Bearer 起头
    assert _looks_like_secret_value("Bearer abc.def.ghi") is True
    assert _looks_like_secret_value("bearer XYZ.abc.123") is True  # lowered

    # 空字符串 / None
    assert _looks_like_secret_value("") is False
    assert _looks_like_secret_value(None) is False
    assert _looks_like_secret_value(123) is False  # 非字符串

    # 正则表存在且非空
    assert len(_SECRET_VALUE_REGEX_PATTERNS) == 4
