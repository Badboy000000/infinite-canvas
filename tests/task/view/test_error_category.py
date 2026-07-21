"""任务 PR-6 · T30-T39:`TaskErrorCategory` + `ErrorCategoryMapper` 契约。

编号池:T30-T39(共 10 个;Wave 3-J 协调纲要 §共享编号池预分配)。

覆盖矩阵
========

- **T30**:14 枚举值定义完整性(不许漂移)
- **T31**:7 provider x 常见 error fixture 分类正确性(28 fixture 参数化)
- **T32**:PR-3 遗留 5 字面量在无 error 场景下 category=None
- **T33**:partial_success fixture 的 category == `partial_success`
         (与 `ProviderTaskView.partial_success=True` 联动)
- **T34**:未识别 error 归 unknown_recoverable if retryable else unknown_terminal
- **T35**:network_error sentinel 分类(`conn_reset` / `dns_error` / `tls_error`)
- **T36**:invalid_credential sentinel 分类(401 / 403 / auth_failed / api_key_invalid)
- **T37**:rate_limit sentinel 分类(429 / queue_depth / too_many_requests)
- **T38**:content_moderation sentinel 分类(policy_violation / nsfw_detected)
- **T39**:`ProviderTaskView.to_dict()` category 字段 JSON 序列化契约
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

import pytest

from app.task.view import (
    ErrorCategoryMapper,
    KNOWN_VIEW_STATUSES,
    ProviderTaskView,
    TaskErrorCategory,
    ViewError,
    map_apimart_task,
    map_chat_task,
    map_comfy_task,
    map_generic_image_task,
    map_jimeng_task,
    map_runninghub_task,
    map_video_task,
)


PROVIDER_SAMPLES = os.path.join(
    os.path.dirname(__file__), "fixtures", "provider_samples"
)
ERROR_CAT_FIXTURES = os.path.join(
    os.path.dirname(__file__), "fixtures", "error_categories"
)


_MAPPER_BY_NAME = {
    "map_runninghub_task": map_runninghub_task,
    "map_apimart_task": map_apimart_task,
    "map_generic_image_task": map_generic_image_task,
    "map_video_task": map_video_task,
    "map_jimeng_task": map_jimeng_task,
    "map_comfy_task": map_comfy_task,
    "map_chat_task": map_chat_task,
}


# ---------------------------------------------------------------------------
# T30 · 14 枚举值定义完整性(STRONG)
# ---------------------------------------------------------------------------


_EXPECTED_CATEGORY_VALUES = frozenset({
    "rate_limit",
    "timeout",
    "upstream_5xx",
    "invalid_credential",
    "invalid_input",
    "quota_exceeded",
    "content_moderation",
    "resource_not_found",
    "cancelled_by_user",
    "cancelled_by_upstream",
    "partial_success",
    "network_error",
    "unknown_recoverable",
    "unknown_terminal",
})


def test_T30_task_error_category_enum_has_exactly_14_values() -> None:
    """STRONG:枚举值集合必须**精确等于** 14 值(既不许多,也不许少)。

    协调纲要 §主线 A · 目标枚举明列 14 值;新增 / 删除 / 重命名 → 本测试
    立即 FAIL,阻止未同步治理方案的枚举漂移。
    """

    actual = {member.value for member in TaskErrorCategory}
    assert actual == _EXPECTED_CATEGORY_VALUES, (
        f"TaskErrorCategory drift: expected {sorted(_EXPECTED_CATEGORY_VALUES)}, "
        f"got {sorted(actual)}"
    )
    # 二重防线:枚举名 == 枚举值(str Enum 便利契约)
    for member in TaskErrorCategory:
        assert member.name == member.value, (
            f"TaskErrorCategory.{member.name} name/value mismatch: {member.value}"
        )


# ---------------------------------------------------------------------------
# T31 · 28 fixture 参数化分类正确性(STRONG)
# ---------------------------------------------------------------------------


def _load_error_category_fixtures() -> list[tuple[str, Mapping[str, Any]]]:
    entries: list[tuple[str, Mapping[str, Any]]] = []
    for name in sorted(os.listdir(ERROR_CAT_FIXTURES)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(ERROR_CAT_FIXTURES, name), encoding="utf-8") as fh:
            entries.append((name, json.load(fh)))
    return entries


@pytest.mark.parametrize(
    "fixture_name,payload",
    _load_error_category_fixtures(),
    ids=[e[0] for e in _load_error_category_fixtures()],
)
def test_T31_mapper_classifies_fixture_correctly(
    fixture_name: str, payload: Mapping[str, Any],
) -> None:
    """STRONG:每 fixture 都必须归到 declared `expected_category`。

    fixture schema:``{expected_category, mapper, provider_id, raw}``。
    我们跑 `map_*(raw)` → 检查 `view.category.value == expected_category`。
    """

    mapper = _MAPPER_BY_NAME[payload["mapper"]]
    view = mapper(payload["raw"])
    expected = payload["expected_category"]
    assert view.category is not None, (
        f"{fixture_name}: view.category should not be None (expected {expected})"
    )
    assert view.category.value == expected, (
        f"{fixture_name}: expected category={expected!r}, got {view.category.value!r}\n"
        f"  view.error.raw={view.error.raw if view.error else None!r}\n"
        f"  view.error.provider_code={view.error.provider_code if view.error else None!r}\n"
        f"  view.remote_status={view.remote_status!r}"
    )


# ---------------------------------------------------------------------------
# T32 · PR-3 遗留 5 字面量 category=None(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mapper,raw,literal",
    [
        (
            map_jimeng_task,
            {"submit_id": "jm-x", "gen_status": "jimeng_pending", "jimeng_pending": True, "queue_info": {}},
            "jimeng_pending",
        ),
        (
            map_apimart_task,
            {"data": {"task_id": "am-x", "status": "apimart_wait"}},
            "apimart_wait",
        ),
        (
            map_apimart_task,
            {"data": {"task_id": "am-y", "status": "apimart_pending"}},
            "apimart_pending",
        ),
        (
            map_runninghub_task,
            {"data": {"taskId": "rh-x", "status": "runninghub_wait"}},
            "runninghub_wait",
        ),
        (
            map_runninghub_task,
            {"data": {"taskId": "rh-y", "status": "runninghub_pending"}},
            "runninghub_pending",
        ),
    ],
    ids=[
        "jimeng_pending",
        "apimart_wait",
        "apimart_pending",
        "runninghub_wait",
        "runninghub_pending",
    ],
)
def test_T32_pr3_legacy_literals_have_none_category(
    mapper, raw: Mapping[str, Any], literal: str,
) -> None:
    """STRONG:PR-3 遗留 5 字面量 → view.status=waiting_upstream,error=None,
    category=None(pending 不是 error;不许把 waiting 误分类为任何 category)。
    """

    view = mapper(raw)
    assert view.status == "waiting_upstream", (
        f"{literal}: expected waiting_upstream, got {view.status}"
    )
    assert view.error is None, (
        f"{literal}: pending is not an error; view.error should be None but got {view.error}"
    )
    assert view.category is None, (
        f"{literal}: pending literal must not carry a category; got {view.category}"
    )


# ---------------------------------------------------------------------------
# T33 · partial_success fixture category 与 partial_success 字段联动(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider,mapper",
    [
        ("runninghub", map_runninghub_task),
        ("apimart", map_apimart_task),
        ("generic_image", map_generic_image_task),
        ("video", map_video_task),
        ("jimeng", map_jimeng_task),
        ("comfyui", map_comfy_task),
    ],
)
def test_T33_partial_fixture_yields_partial_success_category(
    provider: str, mapper,
) -> None:
    """STRONG:partial fixture 满足 `partial_success=True` 且
    `category == partial_success`;error 依然为 None(partial 不是 error)。

    chat/partial.json 不满足 partial_success=True(chat mapper 用不同语义),
    故排除该 provider(见 test_provider_task_view aggregation 现状快照)。
    """

    with open(os.path.join(PROVIDER_SAMPLES, provider, "partial.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    view = mapper(raw)
    assert view.partial_success is True, (
        f"{provider}/partial: partial_success expected True, got {view.partial_success}"
    )
    assert view.error is None, (
        f"{provider}/partial: partial 场景 error 应为 None,got {view.error}"
    )
    assert view.category == TaskErrorCategory.partial_success, (
        f"{provider}/partial: category expected partial_success, got {view.category}"
    )


# ---------------------------------------------------------------------------
# T34 · 未识别 error 兜底(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "retryable,expected",
    [
        (True, TaskErrorCategory.unknown_recoverable),
        (False, TaskErrorCategory.unknown_terminal),
    ],
    ids=["retryable_true->unknown_recoverable", "retryable_false->unknown_terminal"],
)
def test_T34_unmatched_error_falls_back_by_retryable(
    retryable: bool, expected: TaskErrorCategory,
) -> None:
    """STRONG:构造完全无匹配子串的 `ViewError`,断言 mapper 按 retryable 分岔。

    使用 `zzz_unmapped_marker_xyz` 作 raw / provider_code / provider_message ——
    绝不与任何字面量白名单碰撞。remote_status 也用无匹配字面量。
    """

    err = ViewError(
        raw="zzz_unmapped_marker_xyz",
        friendly_zh="未知错误",
        retryable=retryable,
        provider_code="zzz_unmapped_marker_xyz",
        provider_message="zzz_unmapped_marker_xyz",
    )
    category = ErrorCategoryMapper.categorize(
        err, remote_status="zzz_unmapped_status", provider_id="test-provider"
    )
    assert category == expected, (
        f"retryable={retryable}: expected {expected}, got {category}"
    )


# ---------------------------------------------------------------------------
# T35 · network_error sentinel(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signal",
    [
        "conn_reset by peer",
        "connection_reset detected",
        "dns_error unresolved host",
        "tls_error handshake",
        "connection_refused by remote",
        "connect_timeout after 3s",  # network 优先于 timeout
        "network_unreachable",
        "econnreset",
    ],
)
def test_T35_network_error_sentinels_classify(signal: str) -> None:
    """STRONG:network_error marker 独立命中;connect_timeout 应先归 network
    (而非 timeout),这是本表优先级 1 的直接效果。"""

    err = ViewError(raw=signal, friendly_zh="网络失败", retryable=True)
    got = ErrorCategoryMapper.categorize(err, remote_status="", provider_id="test")
    assert got == TaskErrorCategory.network_error, (
        f"signal={signal!r} 应归 network_error,got {got}"
    )


# ---------------------------------------------------------------------------
# T36 · invalid_credential sentinel(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_code,message",
    [
        ("401", "authentication_error"),
        ("403", "forbidden by policy"),
        ("auth_failed", "credential rejected"),
        ("api_key_invalid", "please check api key"),
        ("invalid_api_key", "authentication failed"),
        ("unauthorized", "not authorized to call endpoint"),
        ("authentication_error", "invalid API key"),
    ],
)
def test_T36_invalid_credential_sentinels_classify(
    provider_code: str, message: str,
) -> None:
    """STRONG:401 / 403 / auth_failed / api_key_invalid / unauthorized 全部
    归 invalid_credential(优先级 4)。"""

    err = ViewError(
        raw=message,
        friendly_zh="认证失败",
        retryable=False,
        provider_code=provider_code,
        provider_message=message,
    )
    got = ErrorCategoryMapper.categorize(err, remote_status="failed", provider_id="test")
    assert got == TaskErrorCategory.invalid_credential, (
        f"code={provider_code!r} msg={message!r}: expected invalid_credential, got {got}"
    )


# ---------------------------------------------------------------------------
# T37 · rate_limit sentinel(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signal",
    [
        "rate_limit exceeded",
        "rate limit reached (with space)",
        "too_many_requests",
        "too many requests (with space)",
        "429",
        "throttled by upstream",
        "queue_depth over threshold",
    ],
)
def test_T37_rate_limit_sentinels_classify(signal: str) -> None:
    """STRONG:429 / rate_limit / queue_depth / too_many_requests / throttl 全部
    归 rate_limit(优先级 2)。"""

    err = ViewError(raw=signal, friendly_zh="限流", retryable=True)
    got = ErrorCategoryMapper.categorize(err, remote_status="failed", provider_id="test")
    assert got == TaskErrorCategory.rate_limit, (
        f"signal={signal!r} 应归 rate_limit,got {got}"
    )


# ---------------------------------------------------------------------------
# T38 · content_moderation sentinel(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "signal",
    [
        "policy_violation triggered",
        "nsfw_detected in prompt",
        "content_moderation flagged",
        "content_rejected by review",
        "moderation blocked",
        "unsafe_content detected",
    ],
)
def test_T38_content_moderation_sentinels_classify(signal: str) -> None:
    """STRONG:policy_violation / nsfw_detected / content_moderation 等全部
    归 content_moderation(优先级 5)。"""

    err = ViewError(raw=signal, friendly_zh="内容审核", retryable=False)
    got = ErrorCategoryMapper.categorize(err, remote_status="failed", provider_id="test")
    assert got == TaskErrorCategory.content_moderation, (
        f"signal={signal!r} 应归 content_moderation,got {got}"
    )


# ---------------------------------------------------------------------------
# T39 · to_dict() category 字段 JSON 序列化契约(STRONG)
# ---------------------------------------------------------------------------


def test_T39_to_dict_serializes_category_as_string_or_none() -> None:
    """STRONG:`ProviderTaskView.to_dict()` 输出:
    - category=None 时 payload["category"] is None(不能是缺 key,不能是 "None")
    - category != None 时 payload["category"] is str 且属于 14 值之一
    - json.dumps 后可 round-trip
    """

    # 1) 无 error 且非 partial → category None
    with open(os.path.join(PROVIDER_SAMPLES, "runninghub", "success.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    view = map_runninghub_task(raw)
    payload = view.to_dict()
    assert "category" in payload, "payload must contain 'category' key"
    assert payload["category"] is None, (
        f"success fixture should yield category=None, got {payload['category']}"
    )
    # JSON round-trip
    revived = json.loads(json.dumps(payload, ensure_ascii=False))
    assert revived["category"] is None

    # 2) 有 error → category 是 str 且属于 14 值
    with open(os.path.join(PROVIDER_SAMPLES, "runninghub", "fail.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    view = map_runninghub_task(raw)
    payload = view.to_dict()
    assert isinstance(payload["category"], str), (
        f"fail fixture category should be str, got {type(payload['category']).__name__}"
    )
    assert payload["category"] in _EXPECTED_CATEGORY_VALUES, (
        f"fail fixture category {payload['category']!r} outside 14 known values"
    )
    revived = json.loads(json.dumps(payload, ensure_ascii=False))
    assert revived["category"] == payload["category"]

    # 3) partial fixture → category="partial_success"
    with open(os.path.join(PROVIDER_SAMPLES, "runninghub", "partial.json"), encoding="utf-8") as fh:
        raw = json.load(fh)
    view = map_runninghub_task(raw)
    payload = view.to_dict()
    assert payload["category"] == "partial_success", (
        f"partial fixture should serialize category='partial_success', got {payload['category']}"
    )
