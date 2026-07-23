"""Provider PR-A · CB-P5-01 承接 · jimeng/comfyui rate_limit 通道契约测试。

Wave 3-N.5 Batch 4 主线 B。测试编号 T310-T319(10 项)。

覆盖面
======

- jimeng CLI 退避 payload → `rate_limited + recoverable=True`
- jimeng "retry after" / "rate_limit_hit" 字段真值 → `rate_limited`
- jimeng 无退避提示时保持原 `waiting_upstream`(向后兼容负向断言)
- comfyui `/queue` shape queue 长度 > 阈值(严格 `>` 10)→ `rate_limited`
- comfyui queue 长度 = 10(阈值边界)→ **不**归 `rate_limited`
- 旧 fixture(`rate_limit.json` 原承载 waiting 语义)不被误归 rate_limited
- 2 个新 fixture 独立 grep 9 处 sentinel · 全 0 命中(**P0 密钥零泄漏**)

硬约束
======

- 骨架层:只做识别 · 不做限流(不改动 provider 通信通道)
- fixture 内不含任何 sentinel(`api_key` / `access_token` / `secret` /
  `Bearer` / `refresh_token` / `authorization` / `x-api-key` /
  `client_secret`;共 9 处 case-insensitive 关键词)
"""

from __future__ import annotations

import json
import os
import re

import pytest

from app.task.view import (
    KNOWN_VIEW_STATUSES,
    map_comfy_task,
    map_jimeng_task,
)
from app.task.view.provider_view import (
    COMFYUI_QUEUE_RATE_LIMIT_THRESHOLD,
    _infer_rate_limit_from_queue,
)


FIXTURES_ROOT = os.path.join(
    os.path.dirname(__file__), "fixtures", "provider_samples"
)


# ---------------------------------------------------------------------------
# 硬约束前置:canonical 集合含 rate_limited(骨架层新增第 7 值)
# ---------------------------------------------------------------------------


def test_rate_limited_is_in_known_view_statuses() -> None:
    """`rate_limited` 必须落进 canonical 集合,否则 `_view` 会 raise ValueError。"""

    assert "rate_limited" in KNOWN_VIEW_STATUSES


# ---------------------------------------------------------------------------
# T310 jimeng CLI 退避 payload → rate_limited
# ---------------------------------------------------------------------------


def test_T310_jimeng_cli_backoff_payload_maps_to_rate_limited() -> None:
    """新 fixture `jimeng_rate_limited.json`(fixtures/provider_samples/jimeng/rate_limited.json)
    含 `rate_limit_hit` + `retry_after` + `error_message='rate limit hit,...'`,
    view 层归 `rate_limited + recoverable=True`。"""

    path = os.path.join(FIXTURES_ROOT, "jimeng", "rate_limited.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    view = map_jimeng_task(raw)
    assert view.status == "rate_limited", (
        f"jimeng rate_limit 通道 → 期望 rate_limited,实际 {view.status!r}"
    )
    assert view.recoverable is True
    assert view.provider_id == "jimeng"
    assert view.error is None, "rate_limited 骨架层:只识别不产生 error"


# ---------------------------------------------------------------------------
# T311 jimeng "retry after" 提示 → rate_limited + recoverable=True
# ---------------------------------------------------------------------------


def test_T311_jimeng_retry_after_hint_maps_to_rate_limited() -> None:
    """CLI 层退避原文含 `retry after 60s` 提示,view 归 rate_limited。"""

    raw = {
        "submit_id": "jm-t311",
        "gen_status": "jimeng_pending",
        "jimeng_pending": True,
        "retry_after": 60,
        "error_message": "please retry after 60 seconds",
    }
    view = map_jimeng_task(raw)
    assert view.status == "rate_limited"
    assert view.recoverable is True


# ---------------------------------------------------------------------------
# T312 jimeng 无退避提示 → 保持原 waiting_upstream(向后兼容负向断言)
# ---------------------------------------------------------------------------


def test_T312_jimeng_without_rate_limit_signal_stays_waiting_upstream() -> None:
    """普通排队 payload(仅 queue_info,无 rate_limit_hit / retry_after)
    → 仍归 `waiting_upstream`,与 PR-3 遗留字面量约定一致。"""

    raw = {
        "submit_id": "jm-t312",
        "gen_status": "jimeng_pending",
        "jimeng_pending": True,
        "queue_info": {"queue_idx": 3, "queue_length": 8},
    }
    view = map_jimeng_task(raw)
    assert view.status == "waiting_upstream", (
        f"无 rate_limit 信号不能被误归 rate_limited,实际 {view.status!r}"
    )
    assert view.status != "rate_limited"


# ---------------------------------------------------------------------------
# T313 jimeng `rate_limit_hit` 字段真值 → rate_limited
# ---------------------------------------------------------------------------


def test_T313_jimeng_rate_limit_hit_flag_maps_to_rate_limited() -> None:
    """仅凭 `rate_limit_hit: True` 布尔字段即触发识别(与 retry_after / 消息独立)。"""

    raw = {
        "submit_id": "jm-t313",
        "gen_status": "jimeng_pending",
        "jimeng_pending": True,
        "rate_limit_hit": True,
    }
    view = map_jimeng_task(raw)
    assert view.status == "rate_limited"
    assert view.recoverable is True


# ---------------------------------------------------------------------------
# T314 comfyui queue 长度 = 11 → rate_limited
# ---------------------------------------------------------------------------


def test_T314_comfyui_queue_length_11_maps_to_rate_limited() -> None:
    """queue_running + queue_pending 累计 = 11 严格 > 10 → rate_limited。"""

    raw = {
        "queue_running": [{"prompt_id": f"run-{i}"} for i in range(3)],
        "queue_pending": [{"prompt_id": f"pend-{i}"} for i in range(8)],
    }
    view = map_comfy_task(raw)
    assert view.status == "rate_limited", (
        f"queue_len=11 应归 rate_limited,实际 {view.status!r}"
    )
    assert view.recoverable is True


# ---------------------------------------------------------------------------
# T315 comfyui queue 长度 = 15 → rate_limited
# ---------------------------------------------------------------------------


def test_T315_comfyui_queue_length_15_maps_to_rate_limited() -> None:
    """新 fixture `comfyui_rate_limited.json` queue_running=3 + queue_pending=9
    = 12 严格 > 10 → rate_limited。同时命中 fixture 落盘契约。"""

    path = os.path.join(FIXTURES_ROOT, "comfyui", "rate_limited.json")
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    view = map_comfy_task(raw)
    assert view.status == "rate_limited"
    assert view.recoverable is True

    # 独立 15 长度断言 · 直接构造 payload
    raw15 = {
        "queue_running": [{"prompt_id": f"run-{i}"} for i in range(5)],
        "queue_pending": [{"prompt_id": f"pend-{i}"} for i in range(10)],
    }
    view15 = map_comfy_task(raw15)
    assert view15.status == "rate_limited"


# ---------------------------------------------------------------------------
# T316 comfyui queue 长度 = 10 → 不归 rate_limited(阈值边界 · 严格 >)
# ---------------------------------------------------------------------------


def test_T316_comfyui_queue_length_10_is_boundary_not_rate_limited() -> None:
    """阈值边界:queue_len 严格 = 10 时**不**归 rate_limited(判据 `>`)。"""

    assert COMFYUI_QUEUE_RATE_LIMIT_THRESHOLD == 10
    assert _infer_rate_limit_from_queue(10) is False
    assert _infer_rate_limit_from_queue(11) is True

    raw = {
        "queue_running": [{"prompt_id": f"run-{i}"} for i in range(4)],
        "queue_pending": [{"prompt_id": f"pend-{i}"} for i in range(6)],
    }
    view = map_comfy_task(raw)
    assert view.status != "rate_limited", (
        f"阈值边界 queue_len=10 严格不归 rate_limited,实际 {view.status!r}"
    )


# ---------------------------------------------------------------------------
# T317 comfyui queue 长度 = 5 → 保持原类别(向后兼容负向断言)
# ---------------------------------------------------------------------------


def test_T317_comfyui_queue_length_5_stays_original_category() -> None:
    """queue_len=5 远低于阈值 → **不**归 rate_limited。"""

    raw = {
        "queue_running": [{"prompt_id": "run-1"}],
        "queue_pending": [{"prompt_id": f"pend-{i}"} for i in range(4)],
    }
    view = map_comfy_task(raw)
    assert view.status != "rate_limited"


# ---------------------------------------------------------------------------
# T318 向后兼容:旧 rate_limit.json 仍归 waiting_upstream(未被新逻辑误归)
# ---------------------------------------------------------------------------


def test_T318_legacy_rate_limit_fixtures_still_waiting_upstream() -> None:
    """既有 `jimeng/rate_limit.json` 承载"排队中"语义(jimeng_pending +
    queue_info) · 既有 `comfyui/rate_limit.json` 空对象 · 两者都必须继续
    归 `waiting_upstream`,不因本 PR 新逻辑漂移。"""

    with open(
        os.path.join(FIXTURES_ROOT, "jimeng", "rate_limit.json"),
        encoding="utf-8",
    ) as fh:
        jimeng_legacy = json.load(fh)
    view_jimeng = map_jimeng_task(jimeng_legacy)
    assert view_jimeng.status == "waiting_upstream", (
        f"jimeng legacy rate_limit.json 不能被误归 rate_limited,实际 {view_jimeng.status!r}"
    )

    with open(
        os.path.join(FIXTURES_ROOT, "comfyui", "rate_limit.json"),
        encoding="utf-8",
    ) as fh:
        comfy_legacy = json.load(fh)
    view_comfy = map_comfy_task(comfy_legacy)
    assert view_comfy.status == "waiting_upstream", (
        f"comfyui legacy rate_limit.json 不能被误归 rate_limited,实际 {view_comfy.status!r}"
    )


# ---------------------------------------------------------------------------
# T319 P0 密钥零泄漏防线:2 个新 fixture 独立 grep 9 处 sentinel
# ---------------------------------------------------------------------------


#: **CB-P5-01 承接** · 9 处密钥 sentinel 关键词(case-insensitive 匹配)。
_P0_SENTINEL_KEYWORDS: tuple = (
    "api_key",
    "access_token",
    "secret",
    "bearer",
    "refresh_token",
    "authorization",
    "x-api-key",
    "client_secret",
    "sk-",
)


@pytest.mark.parametrize(
    "fixture_path",
    [
        os.path.join(FIXTURES_ROOT, "jimeng", "rate_limited.json"),
        os.path.join(FIXTURES_ROOT, "comfyui", "rate_limited.json"),
    ],
)
def test_T319_p0_secret_sentinels_zero_hit_in_new_fixtures(
    fixture_path: str,
) -> None:
    """P0 密钥零泄漏防线:2 个新 fixture × 9 sentinel = 18 项断言全 0 命中。

    - 直接读原始 bytes(不走 json.load,避开可能的 unicode 转义漂移)
    - case-insensitive · 子串匹配 · 与 CB-P5-25 深度防御归后续 PR 无关
    """

    with open(fixture_path, encoding="utf-8") as fh:
        blob = fh.read()
    for sentinel in _P0_SENTINEL_KEYWORDS:
        pattern = re.compile(re.escape(sentinel), re.IGNORECASE)
        matches = pattern.findall(blob)
        assert not matches, (
            f"P0 sentinel {sentinel!r} 命中 fixture {fixture_path}:"
            f" {matches}"
        )
