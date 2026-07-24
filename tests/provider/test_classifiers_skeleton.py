"""Provider PR-03 classifiers 骨架契约测试(T540-T569)。"""
from __future__ import annotations

import pytest

from app.adapters.provider.base import TaskErrorCategory
from app.adapters.provider.classifiers import (
    classify_chat_error,
    classify_generic_image_error,
    classify_jimeng_error,
    classify_runninghub_error,
    classify_video_error,
    is_retryable,
)
from app.adapters.provider.error_messages_zh import ERROR_MESSAGES_ZH, get_error_message


class TestGenericImageClassifier:
    def test_T540_401_maps_to_auth(self):
        payload = {"message": "Unauthorized", "http_status": 401}
        err = classify_generic_image_error(payload, request_id="rid")
        assert err.category == TaskErrorCategory.AUTH
        assert err.retryable is False

    def test_T541_429_maps_to_rate_limit(self):
        payload = {"message": "Rate limit exceeded", "http_status": 429}
        err = classify_generic_image_error(payload, request_id="rid")
        assert err.category == TaskErrorCategory.RATE_LIMIT
        assert err.retryable is True

    def test_T542_500_maps_to_upstream_5xx(self):
        payload = {"message": "Server error", "http_status": 500}
        err = classify_generic_image_error(payload, request_id="rid")
        assert err.category == TaskErrorCategory.UPSTREAM_5XX
        assert err.retryable is True

    def test_T543_content_policy_maps(self):
        payload = {"message": "content_policy violation"}
        err = classify_generic_image_error(payload, request_id="rid")
        assert err.category == TaskErrorCategory.CONTENT_POLICY

    def test_T544_quota_maps(self):
        payload = {"message": "insufficient credit balance"}
        err = classify_generic_image_error(payload, request_id="rid")
        assert err.category == TaskErrorCategory.QUOTA

    def test_T545_provider_code_preserved(self):
        payload = {"message": "err", "code": "custom_code_123"}
        err = classify_generic_image_error(payload, request_id="rid")
        assert err.provider_code == "custom_code_123"

    def test_T546_provider_message_truncated_at_500(self):
        long = "x" * 1000
        payload = {"message": long}
        err = classify_generic_image_error(payload, request_id="rid")
        assert len(err.provider_message) == 500


class TestChatClassifier:
    def test_T547_chat_content_policy(self):
        err = classify_chat_error({"message": "content_policy violation"}, request_id="rid")
        assert err.category == TaskErrorCategory.CONTENT_POLICY

    def test_T548_chat_timeout(self):
        err = classify_chat_error({"message": "Request timed out"}, request_id="rid")
        assert err.category == TaskErrorCategory.TIMEOUT
        assert err.retryable is True


class TestRunninghubClassifier:
    def test_T549_rh_code_903_maps_to_quota(self):
        err = classify_runninghub_error({"code": 903, "msg": "wallet insufficient"}, None, "rid")
        assert err.category == TaskErrorCategory.QUOTA

    def test_T550_rh_code_421_maps_to_rate_limit(self):
        err = classify_runninghub_error({"code": 421, "msg": "rate limited"}, None, "rid")
        assert err.category == TaskErrorCategory.RATE_LIMIT

    def test_T551_rh_http_500_maps_to_upstream_5xx(self):
        err = classify_runninghub_error({"code": 0, "msg": "server error"}, 500, "rid")
        assert err.category == TaskErrorCategory.UPSTREAM_5XX

    def test_T552_rh_provider_code_stringified(self):
        err = classify_runninghub_error({"code": 903, "msg": "x"}, None, "rid")
        assert err.provider_code == "903"


class TestJimengClassifier:
    def test_T553_jimeng_rate_limit_via_stderr(self):
        err = classify_jimeng_error("", "rate_limit hit", 1, "rid")
        assert err.category == TaskErrorCategory.RATE_LIMIT

    def test_T554_jimeng_content_policy(self):
        err = classify_jimeng_error("", "content policy violation", 1, "rid")
        assert err.category == TaskErrorCategory.CONTENT_POLICY

    def test_T555_jimeng_timeout_rc_124(self):
        err = classify_jimeng_error("", "", 124, "rid")
        assert err.category == TaskErrorCategory.TIMEOUT

    def test_T556_jimeng_auth_via_stderr(self):
        err = classify_jimeng_error("", "auth failed", 1, "rid")
        assert err.category == TaskErrorCategory.AUTH


class TestVideoClassifier:
    def test_T557_video_download_failed(self):
        err = classify_video_error({"message": "download failed"}, request_id="rid")
        assert err.category == TaskErrorCategory.DOWNLOAD_FAILED

    def test_T558_video_content_policy(self):
        err = classify_video_error({"message": "safety violation"}, request_id="rid")
        assert err.category == TaskErrorCategory.CONTENT_POLICY


class TestRetryableJudgment:
    @pytest.mark.parametrize(
        "cat,expected",
        [
            (TaskErrorCategory.AUTH, False),
            (TaskErrorCategory.QUOTA, False),
            (TaskErrorCategory.RATE_LIMIT, True),
            (TaskErrorCategory.VALIDATION, False),
            (TaskErrorCategory.CONTENT_POLICY, False),
            (TaskErrorCategory.TIMEOUT, True),
            (TaskErrorCategory.UPSTREAM_5XX, True),
            (TaskErrorCategory.UPSTREAM_UNAVAILABLE, True),
            (TaskErrorCategory.RECOVERABLE_UNKNOWN, True),
            (TaskErrorCategory.INTERNAL, False),
            (TaskErrorCategory.CANCELLED, False),
        ],
    )
    def test_T559_retryable_by_category(self, cat, expected):
        assert is_retryable(cat) == expected


class TestErrorMessagesZh:
    def test_T560_all_categories_have_message(self):
        """每个已知 code 都有中文文案"""
        for code in (
            "generic_image.auth",
            "generic_image.rate_limit",
            "runninghub.quota",
            "jimeng.content_policy",
            "video.download_failed",
        ):
            msg = get_error_message(code)
            assert msg
            assert msg != ERROR_MESSAGES_ZH["unknown.error"]

    def test_T561_unknown_code_falls_back(self):
        msg = get_error_message("nonexistent.code.abc")
        assert msg == ERROR_MESSAGES_ZH["unknown.error"]


class TestSecretsSanitization:
    """raw_excerpt 严禁密钥字段(P0)"""

    def test_T562_generic_error_excerpt_excludes_secrets(self):
        payload = {"message": "err", "api_key": "sk-x", "code": "e1"}
        err = classify_generic_image_error(payload, request_id="rid")
        assert "api_key" not in err.raw_excerpt

    def test_T563_runninghub_error_excerpt_excludes_secrets(self):
        payload = {"code": 100, "msg": "err", "secret": "x"}
        err = classify_runninghub_error(payload, None, "rid")
        assert "secret" not in err.raw_excerpt


class TestContractExports:
    def test_T564_all_classifier_exports(self):
        from app.adapters.provider import classifiers as m

        for sym in (
            "classify_generic_image_error",
            "classify_chat_error",
            "classify_runninghub_error",
            "classify_jimeng_error",
            "classify_video_error",
            "is_retryable",
        ):
            assert sym in m.__all__

    def test_T565_error_zh_exports(self):
        from app.adapters.provider import error_messages_zh as m

        assert "ERROR_MESSAGES_ZH" in m.__all__
        assert "get_error_message" in m.__all__