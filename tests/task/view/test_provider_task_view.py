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
}


def test_view_field_contract_matches_governance() -> None:
    """STRONG：`ProviderTaskView.to_dict()` 输出字段清单对齐方案。

    [[30 治理方案/Provider 适配体系治理方案]] §ProviderTaskView 明列字段：
      provider_id / upstream_task_id / status / progress / outputs / error
      / next_poll_after_ms / recoverable / remote_status / raw_excerpt

    本 PR 追加 `partial_success` + `schema_version` 两字段（不减不改，
    仅追加）；本测试锁定该字段集合，防止未来 PR 意外删除。
    """

    sample = _load("runninghub", "success")
    view = map_runninghub_task(sample)
    assert set(view.to_dict().keys()) == REQUIRED_VIEW_FIELDS


# ---------------------------------------------------------------------------
# 补齐任务 PR-3 遗留字面量（3 项断言合并）
# ---------------------------------------------------------------------------


def test_pr3_legacy_literals_are_now_normalized() -> None:
    """`jimeng_pending / apimart_wait / runninghub_wait` 现在都归 waiting_upstream。

    PR-3 遗留：`_CANVAS_TO_TASK_STATUS` 只覆盖 8 稳定字面量；view 层现在补
    齐——本测试直接构造这三个字面量喂给对应 mapper，断言归一化正确。
    """

    # jimeng_pending
    view = map_jimeng_task({"submit_id": "jm-x", "gen_status": "jimeng_pending", "jimeng_pending": True, "queue_info": {}})
    assert view.status == "waiting_upstream" and view.recoverable is True

    # apimart_wait
    view = map_apimart_task({"data": {"task_id": "am-x", "status": "apimart_wait"}})
    assert view.status == "waiting_upstream" and view.recoverable is True

    # runninghub_wait
    view = map_runninghub_task({"data": {"taskId": "rh-x", "status": "runninghub_wait"}})
    assert view.status == "waiting_upstream" and view.recoverable is True
