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


# ---------------------------------------------------------------------------
# Wave 3-I 承接补丁 · P1-1 (任务 PR-5 TRA):
# 42 fixture sentinel 分布不均 —— 只有 4 fixture 含 sentinel,
# `jimeng / comfyui / generic_image / video` 4 provider **无一 fixture 携带
# sentinel** → `test_secrets_never_leak_into_view_output[jimeng/...]` 等参数
# 化用例实际只在验证 mapper 对"clean 输入不误伤",未验证 sanitization 在
# 这些 provider 上生效。
#
# 承接补丁不改现有 fixture(避免 42 expected_normalized.json 全体重算的
# 高风险);改为**运行时向 mapper 直接注入 sentinel**,7 provider × 6 状态
# × 6 sentinel = 252 检查点,断言输出 dict 全量序列化后无 sentinel。
# 这是**真正意义上的 STRONG**:与 fixture 分布无关。
# ---------------------------------------------------------------------------


# 6 类别 P0 sentinel(覆盖 TRA 指出的 `secret` / `AKIA` 空缺)
_P0_SENTINELS_INJECTED = [
    ("api_key", "api_key=SECRET_INJECT_ABC"),
    ("access_token", "access_token_INJECT_XYZ"),
    ("secret", "secret_material_INJECT_QQQ"),
    ("Bearer", "Bearer eyJhbGciOiJIUzI1NiJ9.INJECT.PPP"),
    ("sk-", "sk-INJECT-abcdef0123456789"),
    ("AKIA", "AKIAIOSFODNN7EXAMPLE_INJECT"),
]


def _load_fixture_with_sentinel_injected(
    provider: str, status: str, sentinel_tag: str, sentinel_value: str,
) -> Mapping[str, Any]:
    """(已废弃) 保留为兼容签名 —— 委托到 `_load_fixture_with_key_based_sentinel_injection`。"""
    return _load_fixture_with_key_based_sentinel_injection(provider, status, sentinel_tag, sentinel_value)


@pytest.mark.parametrize("provider,mapper", _ALL_MAPPERS)
def test_secrets_never_leak_uniform_injection_across_all_fixtures(
    provider: str, mapper,
) -> None:
    """STRONG:每 provider × 每状态 × 每 sentinel 类别都独立验证 sanitize 生效
    —— 但只针对**通过键名**塞入 sentinel 的场景(sanitize_raw_excerpt 的
    覆盖面)。

    Wave 3-I 承接补丁 P1-1:覆盖 TRA 指出的 4 项 no-op 参数化用例
    (`jimeng / comfyui / generic_image / video`)—— 即使原 fixture 干净,
    通过 `diagnostic.<sentinel_tag>` 深层注入的 sentinel 会跑一遍 mapper,
    断言 view.to_dict() 全量序列化后无 sentinel 原文。

    覆盖 TRA 指出的 `secret` / `AKIA` sentinel 类别空缺。

    注:此测试**不注入**到 `raw.message` 字段值 —— error.raw / provider_message
    从错误消息 **值**中提取,若 provider 在错误消息里返回含 secret 的字符串
    (真实生产可能场景),当前 sanitize 只查键名子串不扫值,会泄漏。这属于
    Wave 3-I 反审新发现 P1-obs(见 test_error_message_may_leak_provider_secret_values_p1_obs),
    独立小 PR 承接 sanitize 值扫描能力。
    """
    leaks = []
    for status in ("success", "fail", "timeout", "cancel", "partial", "rate_limit"):
        for sentinel_tag, sentinel_value in _P0_SENTINELS_INJECTED:
            raw = _load_fixture_with_key_based_sentinel_injection(
                provider, status, sentinel_tag, sentinel_value,
            )
            view = mapper(raw)
            blob = json.dumps(view.to_dict(), ensure_ascii=False)
            if sentinel_value in blob:
                leaks.append(f"{provider}/{status}/{sentinel_tag}: {sentinel_value}")

    assert not leaks, (
        f"[Wave 3-I 承接 P1-1] {provider} mapper 未剔除通过键名承载的 sentinel:\n"
        + "\n".join(f"  - {leak}" for leak in leaks[:10])
        + f"\n\n(共 {len(leaks)} 处泄漏,前 10 处)"
    )


def _load_fixture_with_key_based_sentinel_injection(
    provider: str, status: str, sentinel_tag: str, sentinel_value: str,
) -> Mapping[str, Any]:
    """加载原 fixture 后往 raw_json 的**键名承载**位置塞 sentinel。

    sanitize_raw_excerpt 应识别 `api_key` / `access_token` / `secret` 等键名
    子串并 mask 值 —— 无论嵌套多深。这是 P1-1 承接补丁明确覆盖的场景。
    """
    with open(os.path.join(FIXTURES_ROOT, provider, f"{status}.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        return raw
    # 键名承载:塞到通用 diagnostic + data.meta 深层位置
    raw.setdefault("diagnostic", {})[sentinel_tag] = sentinel_value
    if "data" in raw and isinstance(raw["data"], dict):
        raw["data"].setdefault("meta", {})[sentinel_tag] = sentinel_value
    return raw


# ---------------------------------------------------------------------------
# Wave 3-I 承接补丁反审新发现 P1-obs:
# error.raw / provider_message 从 Provider 错误消息值中提取,当前 sanitize
# 只扫键名子串,若 provider 在 raw["message"] 里返回 "Invalid api_key='sk-xxx'"
# 之类的字符串,会泄漏到 view.error 中。
#
# 本测试**明确记录**此已知漏洞(不 mask 视为"通过") —— 独立小 PR 承接
# sanitize_raw_excerpt 值层扫描(基于 _SECRET_VALUE_MARKERS 扩展,或引入
# SecretsBusterPlusRegex),届时把此测试改为 assert not leaks。
#
# 现状:本测试断言"至少存在这样的泄漏"(negative-existing),防止有人无意
# 中"修复"了但未同步更新契约。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider,mapper", _ALL_MAPPERS)
def test_error_message_may_leak_provider_secret_values_p1_obs(
    provider: str, mapper,
) -> None:
    """CB-P5-03 已闭合 pin(数据 PR-16 · Wave 3-L 主线 C):Provider 错误消息值
    中的 secret 字面量**必须**被 sanitize 值层正则扫描脱敏。

    历史轨迹:
    - Wave 3-I 反审首次发现此 leak(P1-obs · negative pin 锁定"当前存在")
    - CB-P5-03 登记为独立 tools/security PR 承接
    - **数据 PR-16(Wave 3-L 主线 C)承接**:`_SECRET_VALUE_REGEX_PATTERNS`
      新增 `sk-[A-Za-z0-9\\-]{8,}` 正则 · 覆盖 startswith 判据未覆盖的
      "值中间含 sk- sentinel"场景
    - 本测试**已从 negative pin 升级为 positive assert**:blob 不许含 sentinel
    """
    # 只针对 `fail` 状态,因为 provider_message 提取路径主要在 error 分支
    with open(os.path.join(FIXTURES_ROOT, provider, "fail.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict) or "message" not in raw:
        pytest.skip(f"{provider} fail fixture 无 message 字段,跳过")

    # 用一个典型的 P0 sentinel 塞进 message 值(模拟 Provider API 错误消息中含 secret)
    original_message = raw["message"]
    raw["message"] = f"Provider API error: Invalid api_key='sk-INJECT-live-abc' (from {original_message})"
    view = mapper(raw)
    blob = json.dumps(view.to_dict(), ensure_ascii=False)

    # CB-P5-03 闭合硬断言(数据 PR-16):sanitize 值层正则扫描后 · sk- sentinel
    # 必须不出现在 view 输出的任何字段(error.raw / provider_message / raw_excerpt.*)
    assert "sk-INJECT-live-abc" not in blob, (
        f"CB-P5-03 回归 · {provider} view 输出中出现 sk- sentinel:\n"
        f"blob={blob[:500]}...\n"
        "若正则被弱化或 sanitize 路径被绕过,请恢复 provider_view._SECRET_VALUE_REGEX_PATTERNS "
        "并检查 raw_excerpt / error.provider_message 是否漏了 sanitize。"
    )
