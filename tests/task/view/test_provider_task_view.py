"""任务 PR-5 主套：ProviderTaskView aggregation + fixture 对齐。

每 Provider 一个 STRONG parametrized aggregation test，命中 6 状态 fixture
+ expected_normalized.json 全字段对齐；共 **7 项 aggregation + 1 项 API
契约合规 + 1 项 status canonical 集合合规 = 9 STRONG**。
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

import pytest

from app.task.view import (
    KNOWN_VIEW_STATUSES,
    ProviderTaskView,
    map_apimart_task,
    map_chat_task,
    map_comfy_task,
    map_generic_image_task,
    map_jimeng_task,
    map_runninghub_task,
    map_video_task,
)


FIXTURES_ROOT = os.path.join(os.path.dirname(__file__), "fixtures", "provider_samples")
STATUSES = ("success", "fail", "timeout", "cancel", "partial", "rate_limit")

_PROVIDER_TO_MAPPER = {
    "runninghub": map_runninghub_task,
    "apimart": map_apimart_task,
    "generic_image": map_generic_image_task,
    "video": map_video_task,
    "jimeng": map_jimeng_task,
    "comfyui": map_comfy_task,
    "chat": map_chat_task,
}


def _load(provider: str, status: str) -> Any:
    with open(os.path.join(FIXTURES_ROOT, provider, f"{status}.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _load_expected(provider: str) -> Mapping[str, Mapping[str, Any]]:
    with open(os.path.join(FIXTURES_ROOT, provider, "expected_normalized.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# STRONG · 每 Provider 一个 aggregation 测试（7 项）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", sorted(_PROVIDER_TO_MAPPER.keys()))
def test_provider_view_aggregation(provider: str) -> None:
    """STRONG：单一 Provider 的 6 状态 fixture 全字段 vs expected 对齐。

    覆盖 `success / fail / timeout / cancel / partial / rate_limit`——共
    6 fixture；view 输出必须与 `expected_normalized.json` 逐字段等值。
    这是本 PR **主 STRONG**：任何字段漂移都触发失败。
    """

    mapper = _PROVIDER_TO_MAPPER[provider]
    expected_all = _load_expected(provider)
    seen: set[str] = set()
    for status in STATUSES:
        raw = _load(provider, status)
        view = mapper(raw)
        assert isinstance(view, ProviderTaskView), f"{provider}/{status}: not a ProviderTaskView"
        payload = view.to_dict()
        assert (
            payload == expected_all[status]
        ), f"{provider}/{status}: view != expected\n got={json.dumps(payload, ensure_ascii=False)}\n exp={json.dumps(expected_all[status], ensure_ascii=False)}"
        assert (
            view.status in KNOWN_VIEW_STATUSES
        ), f"{provider}/{status}: status {view.status!r} outside canonical set"
        seen.add(status)
    assert seen == set(STATUSES), f"{provider}: fixture coverage incomplete {seen}"


# ---------------------------------------------------------------------------
# STRONG · canonical status 集合合规（1 项）
# ---------------------------------------------------------------------------


def test_all_view_statuses_stay_canonical() -> None:
    """STRONG：42 fixture 输出的 view.status 全部落在 6 canonical。

    与 aggregation 测试独立断言——若未来新增 Provider / 新状态字面量，本测
    试仍能拦截未归一化到 canonical 6 的漏网字面量。
    """

    for provider, mapper in _PROVIDER_TO_MAPPER.items():
        for status in STATUSES:
            raw = _load(provider, status)
            view = mapper(raw)
            assert view.status in KNOWN_VIEW_STATUSES, (
                f"{provider}/{status}: status {view.status!r} not in canonical set"
                f" {sorted(KNOWN_VIEW_STATUSES)}"
            )


# ---------------------------------------------------------------------------
# STRONG · 字段清单对齐方案（1 项）
# ---------------------------------------------------------------------------


REQUIRED_VIEW_FIELDS = {
    "provider_id",
    "upstream_task_id",
    "status",
    "progress",
    "outputs",
    "error",
    "next_poll_after_ms",
    "recoverable",
    "remote_status",
    "raw_excerpt",
    "partial_success",
    "schema_version",
    "category",
}


def test_view_field_contract_matches_governance() -> None:
    """STRONG：`ProviderTaskView.to_dict()` 输出字段清单对齐方案。

    [[30 治理方案/Provider 适配体系治理方案]] §ProviderTaskView 明列字段：
      provider_id / upstream_task_id / status / progress / outputs / error
      / next_poll_after_ms / recoverable / remote_status / raw_excerpt

    - 任务 PR-5 追加 `partial_success` + `schema_version`；
    - **任务 PR-6 追加 `category`**（14 值 `TaskErrorCategory` 枚举 or None）。
    - 只加不减：本测试锁定该字段集合，防止未来 PR 意外删除。
    """

    sample = _load("runninghub", "success")
    view = map_runninghub_task(sample)
    assert set(view.to_dict().keys()) == REQUIRED_VIEW_FIELDS


# ---------------------------------------------------------------------------
# 补齐任务 PR-3 遗留字面量（3 项断言合并）
# ---------------------------------------------------------------------------


def test_pr3_legacy_literals_are_now_normalized() -> None:
    """`jimeng_pending / apimart_wait / apimart_pending / runninghub_wait /
    runninghub_pending` 现在都归 waiting_upstream + recoverable。

    Wave 3-I 承接补丁 P1-2 (任务 PR-5 TRA)：从 3-in-3 扩展到 **5-in-1
    parametrized** —— 协调纲要 §遗留观察项承接明确要求 5 字面量，原测试只
    覆盖 3 个，遗漏 apimart_pending / runninghub_pending 意外删除时**不会
    失败**（实现的 _WAITING_TOKENS 已含全 5 项，但测试未反证）。
    """

    # (mapper 函数, fixture 构造 lambda, 字面量名称)
    cases = [
        (map_jimeng_task,
         lambda: {"submit_id": "jm-x", "gen_status": "jimeng_pending", "jimeng_pending": True, "queue_info": {}},
         "jimeng_pending"),
        (map_apimart_task,
         lambda: {"data": {"task_id": "am-x", "status": "apimart_wait"}},
         "apimart_wait"),
        (map_apimart_task,
         lambda: {"data": {"task_id": "am-y", "status": "apimart_pending"}},
         "apimart_pending"),
        (map_runninghub_task,
         lambda: {"data": {"taskId": "rh-x", "status": "runninghub_wait"}},
         "runninghub_wait"),
        (map_runninghub_task,
         lambda: {"data": {"taskId": "rh-y", "status": "runninghub_pending"}},
         "runninghub_pending"),
    ]

    for mapper, build_fixture, literal in cases:
        view = mapper(build_fixture())
        assert view.status == "waiting_upstream", (
            f"legacy literal '{literal}' 未归 waiting_upstream: 实际 {view.status}"
        )
        assert view.recoverable is True, (
            f"legacy literal '{literal}' recoverable 应为 True: 实际 {view.recoverable}"
        )
