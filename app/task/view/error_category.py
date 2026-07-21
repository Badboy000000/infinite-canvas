"""`app.task.view.error_category` — TaskErrorCategory 枚举 + Mapper（任务 PR-6）。

设计约束
========

1. **14 值枚举**（严格对齐 Wave 3-J 协调纲要 §主线 A · 任务 PR-6）：
   `rate_limit / timeout / upstream_5xx / invalid_credential / invalid_input
   / quota_exceeded / content_moderation / resource_not_found /
   cancelled_by_user / cancelled_by_upstream / partial_success /
   network_error / unknown_recoverable / unknown_terminal`

2. **零改现有 `ViewError`**：本 PR 只**增量**在 `ProviderTaskView` 追加
   `category: Optional[TaskErrorCategory] = None`（PR-6 增量演进契约）；
   `ViewError` 6 字段保留字节等价。

3. **Mapper 是无副作用纯函数**：`ErrorCategoryMapper.categorize(view_error,
   remote_status, provider_id) -> TaskErrorCategory`；不读 fixture，不
   写日志，不接入路由；只做字面量匹配。

4. **`partial_success` 由 mapper 调用点承接**：本枚举值**不**由
   `categorize()` 产出（error 存在时的 14 类别），而由 `map_*` 函数在
   `partial=True 且 error is None` 时直接赋值。见 `map_runninghub_task`
   等注释。

5. **未识别 error** → `unknown_recoverable` 若 `view_error.retryable=True`
   否则 `unknown_terminal`（14 类别底线兜底）。

**KNOWN LIMITATION**(Wave 3-J TRA-A + RC-A 独立发现,承接补丁记录 · 未修复)
==========================================================================

数字子串 `"500" / "502" / "503" / "401" / "403" / "429" / "400" / "404" /
"402" / "504"` 走**纯子串匹配**,前后**无词边界断言**(`\\b...\\b`)。
非 HTTP status 数字上下文会**误命中**:

- `"generated 5000 tokens"` → 命中 `"500"` → `upstream_5xx`(应为 unknown)
- `"port 4010 declined"` → 命中 `"401"` → `invalid_credential`(应为 unknown)
- `"id 12429 aborted"` → 命中 `"429"` → `rate_limit`(应为 unknown)
- `"user 401k balance"` → 命中 `"401"` → `invalid_credential`(应为 unknown)

**当前实现选择维持子串语义**,原因:
1. 修复需引入 `re` 正则匹配(替代 `in` 子串),性能与语义改动都超出 PR-6 范围
2. 42 fixture 无一命中此 latent 面(HTTP status 码在实际 provider raw 里总是
   位于短字段或标准位置,不会被无关数字上下文淹没)
3. 修复方案候选:tools/security 独立 PR 承接词边界匹配 + fixture 抗回归扩展

**已被 pin 到测试**:`tests/task/view/test_error_category.py::test_T50_digit_
substring_collision_documented` 显式记录 6 个 latent case;若未来实现改词边界,
该测试**全部 FAIL**,提示 KNOWN LIMITATION 已消除。

字面量白名单
============

字面量集合按下述**优先级顺序**匹配（前置命中先赢，避免相互覆盖）：

| 优先级 | 类别 | 命中 marker（子串匹配 / 大小写不敏感） |
|-------|------|------------------------------------|
| 1 | network_error | `conn_reset / connection_reset / dns_error / tls_error / connection_refused / connect_timeout / econnreset` |
| 2 | rate_limit | `rate_limit / rate limit / too_many_requests / throttl / queue_depth / 429` |
| 3 | quota_exceeded | `quota_exceeded / balance_insufficient / insufficient_balance / insufficient_quota / 402` |
| 4 | invalid_credential | `auth_failed / api_key_invalid / unauthorized / forbidden / invalid_api_key / authentication_error / 401 / 403` |
| 5 | content_moderation | `policy_violation / nsfw_detected / content_moderation / content_rejected / moderation / unsafe_content / content_reject / content_review` |
| 6 | resource_not_found | `task_id_not_found / resource_not_found / not_found / does_not_exist / 404` |
| 7 | invalid_input | `validation_failed / invalid_param / invalid_request / bad_request / validation_error / invalid_input / invalid_argument / 400` |
| 8 | timeout | `timeout / timed_out / timedout / expired / 504` |
| 9 | upstream_5xx | `upstream_5xx / upstream_error / internal_server_error / bad_gateway / service_unavailable / workflow_error / 500 / 502 / 503` |
| 10 | cancelled_by_upstream | `remote_status ∈ {cancelled, canceled}` **且** `text` 含 `upstream / system_cancel` |
| 11 | cancelled_by_user | `remote_status ∈ {cancelled, canceled}` |
| 12 | unknown_recoverable / unknown_terminal | 兜底（依 `retryable` 分岔） |

**注**：
- `partial_success` **不**在优先级表中——`categorize()` 前置条件是"存在
  `ViewError`"；partial 场景 error 为 None，由 mapper 调用点直接赋值。
- `network_error` 优先于 `timeout` 匹配（`connect_timeout` 应归 network 而非
  超时）；`connect_timeout` 命中 `connect_timeout` 子串先于 `timeout`。
- PR-3 遗留字面量（`jimeng_pending / apimart_wait / apimart_pending /
  runninghub_wait / runninghub_pending`）**不**在此表——它们的 view.status
  是 `waiting_upstream`，无 error，故 category=None（见 T32）。

Provider 特定 error 字面量分布（来自 42 fixture）
=================================================

- **runninghub**：`RH_WORKFLOW_ERROR` → `upstream_5xx`（workflow_error 命中）;
  `TIMEOUT` → `timeout`；`rate_limit` → `rate_limit`。
- **apimart**：`APIMART_CONTENT_REJECTED` → `content_moderation`（content_reject
  命中）；`timeout` → `timeout`；`rate_limit_exceeded` → `rate_limit`。
- **generic_image**：`invalid_param` → `invalid_input`；`timeout` → `timeout`；
  `rate_limited` → `rate_limit`；`generation_error` → `unknown_terminal`。
- **video**：`timeout` → `timeout`；`rate_limit` → `rate_limit`；`generation_error`
  → `unknown_terminal`。
- **jimeng**：`cli timeout after 300s` → `timeout`；`prompt invalid` →
  `unknown_terminal`（无匹配子串；jimeng 需自定义 `invalid` marker 才能命中
  invalid_input，本 PR 保守兜底）。
- **comfyui**：`workflow timeout` → `timeout`；`KSampler failed: OOM` →
  `unknown_terminal`；`user cancel` → 无 error → category=None。
- **chat**：`rate_limit_exceeded` → `rate_limit`；`timeout` → `timeout`；
  `invalid_request_error` → `invalid_input`（`invalid_request` 命中）。
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.task.view.provider_view import ViewError


class TaskErrorCategory(str, Enum):
    """14 值错误分类枚举。

    值一律使用小写 snake_case 字面量（对齐协调纲要 §主线 A · 目标枚举）。
    继承 ``str`` 使 ``json.dumps`` 直接输出字符串值，便于跨语言消费。
    """

    rate_limit = "rate_limit"
    timeout = "timeout"
    upstream_5xx = "upstream_5xx"
    invalid_credential = "invalid_credential"
    invalid_input = "invalid_input"
    quota_exceeded = "quota_exceeded"
    content_moderation = "content_moderation"
    resource_not_found = "resource_not_found"
    cancelled_by_user = "cancelled_by_user"
    cancelled_by_upstream = "cancelled_by_upstream"
    partial_success = "partial_success"
    network_error = "network_error"
    unknown_recoverable = "unknown_recoverable"
    unknown_terminal = "unknown_terminal"


# ---------------------------------------------------------------------------
# 字面量白名单（子串匹配，大小写不敏感）
# ---------------------------------------------------------------------------


_NETWORK_ERROR_MARKERS: tuple = (
    "conn_reset",
    "connection_reset",
    "dns_error",
    "tls_error",
    "ssl_error",
    "connection_refused",
    "connect_timeout",
    "network_error",
    "econnreset",
    "econnrefused",
    "network_unreachable",
)


_RATE_LIMIT_MARKERS: tuple = (
    "rate_limit",
    "rate limit",
    "too_many_requests",
    "too many requests",
    "throttl",
    "queue_depth",
    "429",
)


_QUOTA_EXCEEDED_MARKERS: tuple = (
    "quota_exceeded",
    "balance_insufficient",
    "insufficient_balance",
    "insufficient_quota",
    "insufficient_funds",
    "402",
)


_INVALID_CREDENTIAL_MARKERS: tuple = (
    "auth_failed",
    "api_key_invalid",
    "invalid_api_key",
    "unauthorized",
    "forbidden",
    "authentication_error",
    "authentication_failed",
    "401",
    "403",
)


_CONTENT_MODERATION_MARKERS: tuple = (
    "policy_violation",
    "nsfw_detected",
    "content_moderation",
    "content_rejected",
    "content_reject",
    "content_review",
    "moderation",
    "unsafe_content",
    "safety_block",
)


_RESOURCE_NOT_FOUND_MARKERS: tuple = (
    "task_id_not_found",
    "resource_not_found",
    "not_found",
    "does_not_exist",
    "404",
)


_INVALID_INPUT_MARKERS: tuple = (
    "validation_failed",
    "validation_error",
    "invalid_param",
    "invalid_parameter",
    "invalid_request",
    "invalid_input",
    "invalid_argument",
    "bad_request",
    "400",
)


_TIMEOUT_MARKERS: tuple = (
    "timeout",
    "timed_out",
    "timedout",
    "expired",
    "504",
)


_UPSTREAM_5XX_MARKERS: tuple = (
    "upstream_5xx",
    "upstream_error",
    "internal_server_error",
    "bad_gateway",
    "service_unavailable",
    "workflow_error",
    "500",
    "502",
    "503",
)


_UPSTREAM_CANCEL_HINTS: tuple = (
    "upstream",
    "system_cancel",
    "server_cancel",
)


_CANCEL_STATUS_TOKENS: frozenset = frozenset({"cancelled", "canceled"})


class ErrorCategoryMapper:
    """`ViewError` → `TaskErrorCategory` 静态分类器。

    - 无实例状态；仅接受 view_error + remote_status + provider_id。
    - **不**产出 `TaskErrorCategory.partial_success`；partial 场景由 mapper
      调用点承接。
    - 未匹配到具体类别时按 `view_error.retryable` 分岔到
      `unknown_recoverable / unknown_terminal`。
    - **不修改**入参；不抛异常（除非 view_error 完全非法）。
    """

    @staticmethod
    def categorize(
        view_error: "ViewError",
        remote_status: str,
        provider_id: str,
    ) -> TaskErrorCategory:
        """把 `ViewError` 映射到 14 类别之一。

        输入：
        - ``view_error``：mapper 已构造好的 `ViewError`（含 raw /
          provider_code / provider_message / retryable）。
        - ``remote_status``：Provider 上游原文 status 字面量（用于分辨
          cancelled_by_user / cancelled_by_upstream；非取消场景不参与匹配）。
        - ``provider_id``：Provider 识别码，供未来 provider-specific 分歧
          扩展（目前不参与决策，仅记录）。

        输出：`TaskErrorCategory` 枚举值。

        未识别 error → `unknown_recoverable` if `retryable` else
        `unknown_terminal`。
        """

        if view_error is None:
            # Defensive: caller 应保证 error 非空；兜底返回可恢复未知。
            return TaskErrorCategory.unknown_recoverable

        # 汇总所有 signal 文本（raw + provider_code + provider_message +
        # remote_status），转小写作 haystack。
        parts: list = []
        for part in (
            view_error.raw,
            view_error.provider_code,
            view_error.provider_message,
            remote_status,
        ):
            if part:
                parts.append(str(part).lower())
        text = " ".join(parts)

        # 优先级顺序匹配（see module docstring）
        if any(m in text for m in _NETWORK_ERROR_MARKERS):
            return TaskErrorCategory.network_error
        if any(m in text for m in _RATE_LIMIT_MARKERS):
            return TaskErrorCategory.rate_limit
        if any(m in text for m in _QUOTA_EXCEEDED_MARKERS):
            return TaskErrorCategory.quota_exceeded
        if any(m in text for m in _INVALID_CREDENTIAL_MARKERS):
            return TaskErrorCategory.invalid_credential
        if any(m in text for m in _CONTENT_MODERATION_MARKERS):
            return TaskErrorCategory.content_moderation
        if any(m in text for m in _RESOURCE_NOT_FOUND_MARKERS):
            return TaskErrorCategory.resource_not_found
        if any(m in text for m in _INVALID_INPUT_MARKERS):
            return TaskErrorCategory.invalid_input
        if any(m in text for m in _TIMEOUT_MARKERS):
            return TaskErrorCategory.timeout
        if any(m in text for m in _UPSTREAM_5XX_MARKERS):
            return TaskErrorCategory.upstream_5xx

        # Cancellation 判定：remote_status 落在 cancel token 集合内，同时
        # 结合上下文分辨 by_upstream vs by_user。
        remote_lower = (remote_status or "").strip().lower()
        if remote_lower in _CANCEL_STATUS_TOKENS:
            if any(hint in text for hint in _UPSTREAM_CANCEL_HINTS):
                return TaskErrorCategory.cancelled_by_upstream
            return TaskErrorCategory.cancelled_by_user

        # 兜底：依 retryable 分岔
        if view_error.retryable:
            return TaskErrorCategory.unknown_recoverable
        return TaskErrorCategory.unknown_terminal


__all__ = ["TaskErrorCategory", "ErrorCategoryMapper"]
