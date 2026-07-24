"""`app.adapters.provider.classifiers` — 错误分类抽取(Provider PR-03 骨架层)。

**定位**:纯函数 · 输入上游错误响应/异常/CLI 输出 · 返回 `TaskError` frozen value object。
本模块**不 wrap** main.py 中的 `friendly_*` 函数 · 生产切换归后续 PR。

**五个分类器**(治理方案阶段 6.0 / 6.1):
- ``classify_generic_image_error(payload_or_exc, request_id) -> TaskError``
- ``classify_chat_error(payload_or_exc, request_id) -> TaskError``
- ``classify_runninghub_error(payload, http_status, request_id) -> TaskError``
- ``classify_jimeng_error(stdout, stderr, rc, request_id) -> TaskError``
- ``classify_video_error(payload_or_exc, request_id) -> TaskError``

**契约要求**:
- `TaskError.code` 稳定机器码 · 每个 code 在 `error_messages_zh` 有唯一文案
- `provider_message / provider_code` 保留上游原文
- `retryable` 由 category 决定:`RATE_LIMIT / TIMEOUT / UPSTREAM_5XX / UPSTREAM_UNAVAILABLE / RECOVERABLE_UNKNOWN → true`
- `raw_excerpt` P0 密钥零泄漏防线:剔除任何潜在敏感字段

**不做**:
- 不改 main.py 内 `friendly_*` 实现
- 不改错误响应结构
- 不改前端错误 UI

见 [[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-03。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from app.adapters.provider.base import TaskError, TaskErrorCategory


# ---------------------------------------------------------------------------
# retryable 判定:一次性列出可重试的 category
# ---------------------------------------------------------------------------

_RETRYABLE_CATEGORIES = frozenset({
    TaskErrorCategory.RATE_LIMIT,
    TaskErrorCategory.TIMEOUT,
    TaskErrorCategory.UPSTREAM_5XX,
    TaskErrorCategory.UPSTREAM_UNAVAILABLE,
    TaskErrorCategory.RECOVERABLE_UNKNOWN,
})


def is_retryable(category: TaskErrorCategory) -> bool:
    """按 category 判断是否可重试。"""
    return category in _RETRYABLE_CATEGORIES


# ---------------------------------------------------------------------------
# raw_excerpt 严禁字段白名单
# ---------------------------------------------------------------------------

_ALLOWED_ERROR_EXCERPT_FIELDS = frozenset({
    "code",
    "error_code",
    "status",
    "http_status",
    "reason",
    "message",
    "detail",
    "elapsed_ms",
})


def _sanitize_error_excerpt(payload: Mapping[str, Any]) -> dict:
    """从 payload 抽取白名单字段 · 严禁密钥泄漏(与部署 PR-10 redaction 双层)。"""
    return {
        k: v for k, v in payload.items()
        if k in _ALLOWED_ERROR_EXCERPT_FIELDS
    }


# ---------------------------------------------------------------------------
# 通用错误关键词表
# ---------------------------------------------------------------------------


_AUTH_KEYWORDS = ("unauthorized", "invalid_api_key", "invalid_token", "expired", "forbidden", "auth")
_QUOTA_KEYWORDS = ("quota", "insufficient", "balance", "credit")
_RATE_LIMIT_KEYWORDS = ("rate", "throttle", "too many", "429")
_VALIDATION_KEYWORDS = ("invalid_request", "invalid parameter", "bad request", "400")
_CONTENT_POLICY_KEYWORDS = ("content_policy", "safety", "moderation", "policy_violation")
_MODEL_NOT_FOUND_KEYWORDS = ("model not found", "model_not_found", "unknown model")
_TIMEOUT_KEYWORDS = ("timeout", "timed out", "deadline")
_DOWNLOAD_KEYWORDS = ("download failed", "download_failed", "fetch failed")


def _category_from_text(text: str) -> TaskErrorCategory:
    """从错误文本关键词推断 category · 骨架层粗粒度。

    优先级:auth > content_policy > quota > rate_limit > validation > model_not_found > timeout > download > unknown
    """
    low = text.lower()

    if any(k in low for k in _AUTH_KEYWORDS):
        return TaskErrorCategory.AUTH
    if any(k in low for k in _CONTENT_POLICY_KEYWORDS):
        return TaskErrorCategory.CONTENT_POLICY
    if any(k in low for k in _QUOTA_KEYWORDS):
        return TaskErrorCategory.QUOTA
    if any(k in low for k in _RATE_LIMIT_KEYWORDS):
        return TaskErrorCategory.RATE_LIMIT
    if any(k in low for k in _VALIDATION_KEYWORDS):
        return TaskErrorCategory.VALIDATION
    if any(k in low for k in _MODEL_NOT_FOUND_KEYWORDS):
        return TaskErrorCategory.MODEL_NOT_FOUND
    if any(k in low for k in _TIMEOUT_KEYWORDS):
        return TaskErrorCategory.TIMEOUT
    if any(k in low for k in _DOWNLOAD_KEYWORDS):
        return TaskErrorCategory.DOWNLOAD_FAILED

    return TaskErrorCategory.RECOVERABLE_UNKNOWN


# ---------------------------------------------------------------------------
# 五个分类器主入口
# ---------------------------------------------------------------------------


def classify_generic_image_error(
    payload_or_exc: Any,
    request_id: str,
) -> TaskError:
    """通用图像 provider 错误 → TaskError。

    Args:
        payload_or_exc: 上游错误响应 dict 或 Exception 对象。
        request_id: 用于 TaskError.request_id。

    Returns:
        TaskError。
    """
    if isinstance(payload_or_exc, dict):
        message = str(
            payload_or_exc.get("message")
            or payload_or_exc.get("error")
            or payload_or_exc.get("detail")
            or ""
        )
        provider_code = payload_or_exc.get("code") or payload_or_exc.get("error_code")
        raw_excerpt = _sanitize_error_excerpt(payload_or_exc)
    else:
        message = str(payload_or_exc)
        provider_code = None
        raw_excerpt = {}

    # HTTP 状态推断
    http_status = payload_or_exc.get("http_status") if isinstance(payload_or_exc, dict) else None
    if isinstance(http_status, int):
        if http_status == 401 or http_status == 403:
            category = TaskErrorCategory.AUTH
        elif http_status == 429:
            category = TaskErrorCategory.RATE_LIMIT
        elif 500 <= http_status < 600:
            category = TaskErrorCategory.UPSTREAM_5XX
        elif http_status == 408:
            category = TaskErrorCategory.TIMEOUT
        else:
            category = _category_from_text(message)
    else:
        category = _category_from_text(message)

    return TaskError(
        code=f"generic_image.{category.value.lower()}",
        category=category,
        provider_code=str(provider_code) if provider_code else None,
        provider_message=message[:500] if message else None,
        retryable=is_retryable(category),
        raw_excerpt=raw_excerpt,
        request_id=request_id,
    )


def classify_chat_error(
    payload_or_exc: Any,
    request_id: str,
) -> TaskError:
    """Chat provider 错误 → TaskError。"""
    if isinstance(payload_or_exc, dict):
        message = str(
            payload_or_exc.get("message")
            or payload_or_exc.get("error")
            or ""
        )
        provider_code = payload_or_exc.get("code")
        raw_excerpt = _sanitize_error_excerpt(payload_or_exc)
    else:
        message = str(payload_or_exc)
        provider_code = None
        raw_excerpt = {}

    category = _category_from_text(message)

    return TaskError(
        code=f"chat.{category.value.lower()}",
        category=category,
        provider_code=str(provider_code) if provider_code else None,
        provider_message=message[:500] if message else None,
        retryable=is_retryable(category),
        raw_excerpt=raw_excerpt,
        request_id=request_id,
    )


def classify_runninghub_error(
    payload: Mapping[str, Any],
    http_status: Optional[int],
    request_id: str,
) -> TaskError:
    """RunningHub 错误 → TaskError。

    RunningHub 特殊性:
    - `code` 是主要错误标识(如 903 = wallet 余额不足)
    - `msg` 是文案
    - HTTP 200 但 code != 0 也算错误
    """
    rh_code = payload.get("code")
    message = str(payload.get("msg") or payload.get("message") or "")

    # 已知 RunningHub 错误码映射
    if rh_code == 903 or "insufficient" in message.lower() or "余额" in message:
        category = TaskErrorCategory.QUOTA
    elif rh_code == 421 or "rate" in message.lower():
        category = TaskErrorCategory.RATE_LIMIT
    elif rh_code in (401, 403):
        category = TaskErrorCategory.AUTH
    elif http_status is not None and 500 <= http_status < 600:
        category = TaskErrorCategory.UPSTREAM_5XX
    elif http_status is not None and http_status == 429:
        category = TaskErrorCategory.RATE_LIMIT
    else:
        category = _category_from_text(message)

    return TaskError(
        code=f"runninghub.{category.value.lower()}",
        category=category,
        provider_code=str(rh_code) if rh_code is not None else None,
        provider_message=message[:500] if message else None,
        retryable=is_retryable(category),
        raw_excerpt=_sanitize_error_excerpt(dict(payload)),
        request_id=request_id,
    )


def classify_jimeng_error(
    stdout: str,
    stderr: str,
    rc: int,
    request_id: str,
) -> TaskError:
    """即梦 CLI 错误 → TaskError(基于 stdout / stderr / return code)。"""
    combined = (stderr or "") + "\n" + (stdout or "")

    # rate_limit 特殊模式
    if "rate_limit" in combined.lower() or "rate limit" in combined.lower():
        category = TaskErrorCategory.RATE_LIMIT
    elif "content" in combined.lower() and ("policy" in combined.lower() or "safe" in combined.lower()):
        category = TaskErrorCategory.CONTENT_POLICY
    elif rc == 124 or "timeout" in combined.lower():
        category = TaskErrorCategory.TIMEOUT
    elif "auth" in combined.lower() or "login" in combined.lower():
        category = TaskErrorCategory.AUTH
    elif rc != 0:
        category = _category_from_text(combined)
    else:
        category = TaskErrorCategory.RECOVERABLE_UNKNOWN

    return TaskError(
        code=f"jimeng.{category.value.lower()}",
        category=category,
        provider_code=str(rc),
        provider_message=(stderr or stdout or "")[:500] or None,
        retryable=is_retryable(category),
        raw_excerpt={"rc": rc},
        request_id=request_id,
    )


def classify_video_error(
    payload_or_exc: Any,
    request_id: str,
) -> TaskError:
    """视频 provider 错误 → TaskError。"""
    if isinstance(payload_or_exc, dict):
        message = str(
            payload_or_exc.get("message")
            or payload_or_exc.get("error")
            or ""
        )
        provider_code = payload_or_exc.get("code")
        raw_excerpt = _sanitize_error_excerpt(payload_or_exc)
    else:
        message = str(payload_or_exc)
        provider_code = None
        raw_excerpt = {}

    # 视频特有:download_failed 更常见
    if "download" in message.lower():
        category = TaskErrorCategory.DOWNLOAD_FAILED
    elif "policy" in message.lower() or "safety" in message.lower():
        category = TaskErrorCategory.CONTENT_POLICY
    else:
        category = _category_from_text(message)

    return TaskError(
        code=f"video.{category.value.lower()}",
        category=category,
        provider_code=str(provider_code) if provider_code else None,
        provider_message=message[:500] if message else None,
        retryable=is_retryable(category),
        raw_excerpt=raw_excerpt,
        request_id=request_id,
    )


__all__ = [
    "classify_generic_image_error",
    "classify_chat_error",
    "classify_runninghub_error",
    "classify_jimeng_error",
    "classify_video_error",
    "is_retryable",
]
