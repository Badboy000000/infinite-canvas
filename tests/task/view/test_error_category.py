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
        ("chat", map_chat_task),  # Wave 3-J 承接补丁 P1-D:RC-A + TRA-A 独立复核
                                   # chat/partial.json 与其他 6 provider 一致
                                   # (partial_success=True + category=partial_success),
                                   # 原 docstring 排除理由已过期,拉入 7/7 参数化。
    ],
)
def test_T33_partial_fixture_yields_partial_success_category(
    provider: str, mapper,
) -> None:
    """STRONG:partial fixture 满足 `partial_success=True` 且
    `category == partial_success`;error 依然为 None(partial 不是 error)。

    覆盖 7/7 provider(runninghub / apimart / generic_image / video / jimeng /
    comfyui / chat)—— Wave 3-J 承接补丁 P1-D 修正:此前 chat 被错误排除,
    实际 map_chat_task(chat/partial.json) 也返回 partial_success=True。
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


# ---------------------------------------------------------------------------
# Wave 3-J 承接补丁编号:T50-T57(RC-A + TRA-A + RC-B 反审必处理)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T50 · P1-A · 数字子串误命中 latent bug 覆盖(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_text,provider_code,expected_category,scenario",
    [
        # 5000 tokens 无关文案 —— 会命中 upstream_5xx `500` 子串(latent)
        (
            "generated 5000 tokens successfully but downstream parse failed",
            "downstream_parse_error",
            TaskErrorCategory.upstream_5xx,
            "5000_hits_500_KNOWN_LATENT",
        ),
        # port 4010 —— 会命中 invalid_credential `401` 子串(latent,
        # 优先级 4 > invalid_input 优先级 7,所以 credential 先胜)
        (
            "connection to port 4010 declined by user process",
            "port_declined",
            TaskErrorCategory.invalid_credential,
            "port_4010_hits_401_KNOWN_LATENT",
        ),
        # id 5020 —— 会命中 upstream_5xx `502` 子串(latent)
        (
            "generation id 5020 aborted",
            "id_aborted",
            TaskErrorCategory.upstream_5xx,
            "id_5020_hits_502_KNOWN_LATENT",
        ),
        # id 12429 —— 会命中 rate_limit `429` 子串(latent)
        (
            "id 12429 aborted upstream",
            "id_aborted",
            TaskErrorCategory.rate_limit,
            "id_12429_hits_429_KNOWN_LATENT",
        ),
        # user 5030 —— 会命中 upstream_5xx `503` 子串(latent)
        (
            "user 5030 hit quota barrier",
            "quota_barrier",
            TaskErrorCategory.upstream_5xx,
            "id_5030_hits_503_KNOWN_LATENT",
        ),
        # user 401k —— 会命中 invalid_credential `401` 子串(latent)
        (
            "user 401k balance exceeded",
            "balance_exceeded",
            TaskErrorCategory.invalid_credential,
            "id_401k_hits_401_KNOWN_LATENT",
        ),
    ],
    ids=[
        "5000_hits_500_KNOWN_LATENT",
        "port_4010_hits_401_KNOWN_LATENT",
        "id_5020_hits_502_KNOWN_LATENT",
        "id_12429_hits_429_KNOWN_LATENT",
        "id_5030_hits_503_KNOWN_LATENT",
        "id_401k_hits_401_KNOWN_LATENT",
    ],
)
def test_T50_digit_substring_collision_documented(
    raw_text: str, provider_code: str,
    expected_category: TaskErrorCategory, scenario: str,
) -> None:
    """STRONG (documenting KNOWN LIMITATION):数字子串误命中 latent bug.

    Wave 3-J TRA-A 反审 P1-A 发现:mapper 用**纯子串匹配** `"500" / "401" /
    "429" / ...`,数字前后**无词边界断言**。如 "HTTP 5000" / "port 4010" /
    "id 12429" 等文本会**误命中** upstream_5xx / rate_limit / invalid_credential /
    invalid_input。

    Wave 3-J 承接补丁决策:
    - **不改**当前实现(避免连锁效应打破 42 fixture)
    - 用本测试**显式记录 6 个 KNOWN LATENT case**,把 latent bug 从"未记录"
      翻到"已记录且被断言锁定"
    - 若未来 mapper 改为词边界匹配(如 `r'\\b(429|500|502|503|401|400)\\b'`),
      本测试将全部 FAIL,提示"latent 已修复,现在期望应翻转到 unknown_terminal"

    这符合 Wave 3-I "documented negative pin" 承接模式(参考 CB-P5-03)。
    Wave 3-K 若有 tools/security 独立 PR,可把本测试翻正。
    """

    err = ViewError(
        raw=raw_text,
        friendly_zh="documented latent bug scenario",
        retryable=False,
        provider_code=provider_code,
        provider_message=raw_text,
    )
    got = ErrorCategoryMapper.categorize(
        err, remote_status="failed", provider_id="test-latent"
    )
    assert got == expected_category, (
        f"[{scenario}] latent bug case:期望 {expected_category.value},实际 {got.value};"
        f"若本测试 FAIL,说明数字子串误命中行为发生变化,需评估是否修复 mapper 加词边界。"
    )


# ---------------------------------------------------------------------------
# T51 · P1-B · cancelled_by_user / cancelled_by_upstream 硬锁(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "remote_status,raw_text,expected_category,scenario",
    [
        # cancelled_by_user:remote_status 命中 cancel token,text 无 upstream hint
        ("cancelled", "user_requested_cancel", TaskErrorCategory.cancelled_by_user, "cancelled_user"),
        ("canceled", "user_stop", TaskErrorCategory.cancelled_by_user, "canceled_user_variant"),
        ("cancelled", "", TaskErrorCategory.cancelled_by_user, "cancelled_empty_text"),
        # cancelled_by_upstream:remote_status cancel token + text 命中 upstream hint
        ("cancelled", "upstream forced cancel", TaskErrorCategory.cancelled_by_upstream, "upstream_cancel"),
        ("cancelled", "system_cancel by scheduler", TaskErrorCategory.cancelled_by_upstream, "system_cancel_hint"),
        ("canceled", "server_cancel due to scheduler policy", TaskErrorCategory.cancelled_by_upstream, "server_cancel_variant"),
    ],
    ids=[
        "cancelled_user",
        "canceled_user_variant",
        "cancelled_empty_text",
        "upstream_cancel",
        "system_cancel_hint",
        "server_cancel_variant",
    ],
)
def test_T51_cancelled_variants_classify(
    remote_status: str, raw_text: str,
    expected_category: TaskErrorCategory, scenario: str,
) -> None:
    """STRONG:remote_status ∈ {cancelled, canceled} 触发取消分支;
    text 含 upstream/system_cancel/server_cancel → cancelled_by_upstream,
    否则 → cancelled_by_user。
    """

    err = ViewError(
        raw=raw_text,
        friendly_zh="任务取消",
        retryable=False,
        provider_code=None,
        provider_message=raw_text,
    )
    got = ErrorCategoryMapper.categorize(
        err, remote_status=remote_status, provider_id="test-cancel"
    )
    assert got == expected_category, (
        f"[{scenario}] remote_status={remote_status!r} text={raw_text!r} → "
        f"expected {expected_category.value},got {got.value}"
    )


# ---------------------------------------------------------------------------
# T52 · P1-C · 优先级顺序抗回归(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_category,winning_marker,losing_markers",
    [
        # network_error > timeout:connect_timeout 应归 network(优先级 1)
        (
            "connect_timeout after 3s expired",
            TaskErrorCategory.network_error,
            "connect_timeout",
            ["timeout", "expired"],
        ),
        # rate_limit > quota_exceeded:同时命中时优先 rate_limit(优先级 2)
        (
            "rate_limit exceeded due to quota_exceeded on tier",
            TaskErrorCategory.rate_limit,
            "rate_limit",
            ["quota_exceeded"],
        ),
        # invalid_credential > content_moderation:同时命中时优先 credential(优先级 4)
        (
            "authentication_error and policy_violation blocked",
            TaskErrorCategory.invalid_credential,
            "authentication_error",
            ["policy_violation"],
        ),
        # content_moderation > resource_not_found:同时命中时优先 moderation(优先级 5)
        (
            "content_moderation blocked but resource_not_found downstream",
            TaskErrorCategory.content_moderation,
            "content_moderation",
            ["resource_not_found"],
        ),
        # invalid_input > timeout:400 vs timeout 同时命中,优先 invalid_input(优先级 7)
        (
            "bad_request and request timeout",
            TaskErrorCategory.invalid_input,
            "bad_request",
            ["timeout"],
        ),
    ],
    ids=[
        "network_over_timeout",
        "rate_limit_over_quota",
        "credential_over_moderation",
        "moderation_over_res_not_found",
        "invalid_input_over_timeout",
    ],
)
def test_T52_priority_order_antiregression(
    text: str,
    expected_category: TaskErrorCategory,
    winning_marker: str,
    losing_markers: list,
) -> None:
    """STRONG:模块 docstring 明列 9 层优先级顺序,同一 text 同时命中多类 marker
    时,**只允许前面优先级胜出**;若某天有人错改了 `if any(...)` 顺序,本测试立即
    FAIL,拉回优先级约束。"""

    err = ViewError(
        raw=text,
        friendly_zh="priority test",
        retryable=False,
        provider_code=None,
        provider_message=text,
    )
    got = ErrorCategoryMapper.categorize(
        err, remote_status="failed", provider_id="test-priority"
    )
    assert got == expected_category, (
        f"priority regression: text={text!r} "
        f"应归 {expected_category.value}({winning_marker} 胜出),"
        f"实际 {got.value};losing markers = {losing_markers}"
    )


# ---------------------------------------------------------------------------
# T53 · P2-D · 大小写不敏感硬锁(STRONG)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_text,expected_category",
    [
        # 全大写变体
        ("RATE_LIMIT EXCEEDED", TaskErrorCategory.rate_limit),
        ("TOO_MANY_REQUESTS", TaskErrorCategory.rate_limit),
        ("Unauthorized Access", TaskErrorCategory.invalid_credential),
        ("AUTHENTICATION_ERROR", TaskErrorCategory.invalid_credential),
        ("POLICY_VIOLATION FLAGGED", TaskErrorCategory.content_moderation),
        ("NSFW_DETECTED", TaskErrorCategory.content_moderation),
        # 混合大小写
        ("Rate_Limit reached", TaskErrorCategory.rate_limit),
        ("Content_Rejected By Review", TaskErrorCategory.content_moderation),
    ],
    ids=[
        "upper_rate_limit",
        "upper_too_many_requests",
        "mixed_unauthorized",
        "upper_authentication_error",
        "upper_policy_violation",
        "upper_nsfw_detected",
        "mixed_rate_limit",
        "mixed_content_rejected",
    ],
)
def test_T53_case_insensitive_matching(
    raw_text: str, expected_category: TaskErrorCategory,
) -> None:
    """STRONG:mapper docstring 承诺"子串匹配 / 大小写不敏感"(module docstring
    §字面量白名单)。实现方式是 `text = " ".join(str(p).lower() for p in parts)`,
    marker 已经全小写。本测试锁定该行为,防止未来把 `.lower()` 移除。"""

    err = ViewError(
        raw=raw_text,
        friendly_zh="case sensitivity test",
        retryable=False,
        provider_code=None,
        provider_message=raw_text,
    )
    got = ErrorCategoryMapper.categorize(
        err, remote_status="failed", provider_id="test-case"
    )
    assert got == expected_category, (
        f"case sensitivity regression: text={raw_text!r} "
        f"应归 {expected_category.value}(大小写不敏感),实际 {got.value}"
    )

