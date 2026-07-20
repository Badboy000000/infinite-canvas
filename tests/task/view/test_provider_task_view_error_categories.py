"""任务 PR-5 error 分支 + P0 密钥零泄漏防线。

- `TaskErrorCategory` 允许缺失（PR-6 承接）：断言 `ViewError` 字段集合
  **不**含 `category`。
- raw string + friendly_zh 兜底：所有 `status == "failed"` 分支必须给出这
  两个字段。
- P0 sentinel：`api_key / access_token / secret / Bearer / authorization`
  等 sentinel 出现在 fixture 中时，view 输出 dict 的任何字段（含
  raw_excerpt / error）都不许再出现原文；断言等值 `[REDACTED]`。
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from typing import Any, Mapping

import pytest

from app.task.view import (
    ProviderTaskView,
    ViewError,
    map_apimart_task,
    map_chat_task,
    map_comfy_task,
    map_generic_image_task,
    map_jimeng_task,
    map_runninghub_task,
    map_video_task,
    sanitize_raw_excerpt,
)


FIXTURES_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "provider_samples")


# ---------------------------------------------------------------------------
# STRONG · TaskErrorCategory 允许缺失
# ---------------------------------------------------------------------------


def test_view_error_has_no_category_field_yet() -> None:
    """STRONG：`ViewError` 字段集合**必须**不含 `category`（PR-6 承接）。

    但**必须**保留 raw + friendly_zh + retryable 三字段（本 PR 兜底契约）。
    未来 PR-6 会新增 `category: TaskErrorCategory` 字段而**不删**已有字段。
    """

    field_names = {f.name for f in dataclasses.fields(ViewError)}
    assert "category" not in field_names, (
        "ViewError.category should NOT exist yet (task PR-6 introduces TaskErrorCategory)"
    )
    assert {"raw", "friendly_zh", "retryable"} <= field_names, (
        "ViewError must retain raw + friendly_zh + retryable as fallback"
    )


# ---------------------------------------------------------------------------
# STRONG · 所有 failed 视图必须给出 raw + friendly_zh 兜底
# ---------------------------------------------------------------------------


_ALL_MAPPERS = [
    ("runninghub", map_runninghub_task),
    ("apimart", map_apimart_task),
    ("generic_image", map_generic_image_task),
    ("video", map_video_task),
    ("jimeng", map_jimeng_task),
    ("comfyui", map_comfy_task),
    ("chat", map_chat_task),
]


@pytest.mark.parametrize("provider,mapper", _ALL_MAPPERS)
def test_failed_view_has_raw_and_friendly_zh(provider: str, mapper) -> None:
    """STRONG：`failed` fixture 生成的视图 error 必须含 raw + friendly_zh 非空。"""

    with open(os.path.join(FIXTURES_ROOT, provider, "fail.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    view = mapper(raw)
    assert view.status == "failed", f"{provider} fail fixture should map to failed"
    assert view.error is not None, f"{provider} failed view must carry error"
    assert view.error.raw and view.error.raw.strip(), f"{provider} error.raw must be non-empty"
    assert (
        view.error.friendly_zh and view.error.friendly_zh.strip()
    ), f"{provider} error.friendly_zh must be non-empty"


# ---------------------------------------------------------------------------
# STRONG · P0 密钥零泄漏 sentinel
# ---------------------------------------------------------------------------


_SENTINELS = [
    "sk-should-be-redacted",
    "should-be-redacted-token",
    "LEAK-BE-REDACTED",
    "LEAKED_TOKEN",
    "Bearer LEAK",
    "Bearer LEAKED_TOKEN",
]


def _serialize_view(view: ProviderTaskView) -> str:
    return json.dumps(view.to_dict(), ensure_ascii=False)


@pytest.mark.parametrize("provider,mapper", _ALL_MAPPERS)
def test_secrets_never_leak_into_view_output(provider: str, mapper) -> None:
    """STRONG：任何 fixture（含 fail / rate_limit / cancel）经 view 后都不留 sentinel。

    - fixture 中人为注入了 `api_key / access_token / authorization` 键
      承载 sentinel；
    - view 输出必须把这些字段替换为 `[REDACTED]`；
    - 序列化后**不许**出现任何 sentinel 原文子串。
    """

    for status in ("success", "fail", "timeout", "cancel", "partial", "rate_limit"):
        with open(os.path.join(FIXTURES_ROOT, provider, f"{status}.json"), encoding="utf-8") as fh:
            raw = json.load(fh)
        view = mapper(raw)
        blob = _serialize_view(view)
        for sentinel in _SENTINELS:
            assert (
                sentinel not in blob
            ), f"sentinel {sentinel!r} leaked in {provider}/{status} view: {blob}"


def test_sanitize_raw_excerpt_scrubs_sentinels_directly() -> None:
    """`sanitize_raw_excerpt` 是零泄漏的最后一道防线；单独断言其行为。"""

    payload = {
        "api_key": "sk-live-secret-123",
        "nested": {
            "access_token": "should-vanish",
            "Authorization": "Bearer LEAKED",
            "public": "keep-me",
            "list": ["Bearer ANOTHER-LEAK", "public-item", {"secret": "gone"}],
        },
        "note": "normal string",
        "AKIA_EXAMPLE": "AKIAIOSFODNN7EXAMPLE",
    }
    cleaned = sanitize_raw_excerpt(payload)
    blob = json.dumps(cleaned)
    for token in ("sk-live-secret-123", "should-vanish", "LEAKED", "gone", "AKIAIOSFODNN7EXAMPLE", "ANOTHER-LEAK"):
        assert token not in blob, f"sentinel {token!r} leaked in sanitized output"
    assert cleaned["nested"]["public"] == "keep-me"
    assert cleaned["note"] == "normal string"


def test_status_outside_canonical_raises() -> None:
    """内部 `_view` 拒绝非 canonical 状态（防止 mapper 意外产出漏网字面量）。"""

    from app.task.view.provider_view import _view

    with pytest.raises(ValueError, match="ProviderTaskView.status"):
        _view(
            provider_id="test",
            upstream_task_id=None,
            status="in_flight",  # 非 canonical
            progress=None,
            outputs=(),
            error=None,
            next_poll_after_ms=None,
            recoverable=True,
            remote_status="in_flight",
            raw_excerpt={},
        )
