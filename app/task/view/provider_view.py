"""`app.task.view.provider_view` — ProviderTaskView + 7 map 函数（任务 PR-5）。

设计约束
========

1. **字段严格对齐两方案**：
   - 主契约：[[30 治理方案/Provider 适配体系治理方案]] §"ProviderTaskView"（6 canonical
     status；`outputs / error / raw_excerpt / next_poll_after_ms / recoverable / remote_status`）。
   - 落地契约：[[30 治理方案/任务模型与后台任务治理方案]] §"ProviderTask · remote_view"。
2. **允许缺 TaskErrorCategory**：本 PR 不引入枚举；`ViewError` 只保留 raw
   string + friendly_zh + retryable 三字段（任务 PR-6 承接 category 抽取）。
3. **P0 密钥零入库**：`sanitize_raw_excerpt` 剔除任何 key 或 value 含
   sentinel（`api_key / access_token / secret / bearer / authorization / password`）
   的字段，替换成 `"[REDACTED]"`。所有 map 函数输出 dict 均经过该 sanitize。
4. **只映射，不接入**：本模块不改任何路由，不改任何前端读端点 shape；只提
   供内部诊断视图。

补齐任务 PR-3 遗留字面量
========================

任务 PR-3 `_CANVAS_TO_TASK_STATUS` 仅覆盖 8 个稳定字面量；PR-5 在 view 层
把以下业务字面量正式收入 remote_status → view.status 的映射：

- `jimeng_pending` → `waiting_upstream`（jimeng CLI 排队中）
- `apimart_wait` / `apimart_pending` → `waiting_upstream`
- `runninghub_wait` / `runninghub_pending` → `waiting_upstream`

这些字面量**只**在 view 层做归一化；`_CANVAS_TO_TASK_STATUS` 保持不动
（那是 Task 状态机边界，view 层是诊断视图边界）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Pattern, Sequence, Tuple

from app.task.view.error_category import ErrorCategoryMapper, TaskErrorCategory


# ---------------------------------------------------------------------------
# 常量：canonical 状态集
# ---------------------------------------------------------------------------

#: [[Provider 适配体系治理方案]] §ProviderTaskView 明列的 6 canonical status。
#:
#: **CB-P5-01 承接(Provider PR-A · Wave 3-N.5 Batch 4 主线 B)**:新增 7-th
#: canonical `rate_limited` — Provider 上游 rate_limit 通道显式识别值域。
#: 骨架层:只做识别 · 不做限流;下游 `_VIEW_TO_TASK` boundary 与
#: `ProviderTaskViewStatus` Literal 类型的扩展留待后续 provider 通信通道
#: 专题 PR 承接,本 PR 不改动 provider 通信通道以对齐硬约束。
KNOWN_VIEW_STATUSES: frozenset = frozenset(
    {"queued", "running", "succeeded", "failed", "cancelled", "waiting_upstream", "rate_limited"}
)


#: **CB-P5-01 承接** · comfyui 通道 queue 长度阈值。严格 `>` 阈值时视为
#: rate limit 触发 · 阈值 `= 10` 时保持原类别。
COMFYUI_QUEUE_RATE_LIMIT_THRESHOLD: int = 10


#: 需要脱敏的字段名子串。命中任一即整字段值替换为 `"[REDACTED]"`。
_SECRET_KEY_TOKENS: tuple = (
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "secret",
    "bearer",
    "authorization",
    "password",
    "credential",
    "session_token",
    "refresh_token",
)


#: 需要脱敏的**值前缀 / 关键词**。命中即整字段替换为 `"[REDACTED]"`。
#:
#: **CB-P5-02 承接(数据 PR-16 · Wave 3-L 主线 C)**:原 `"aki"` 前缀过宽,会命中
#: `akira` / `akihabara` 等合法业务字符串。收紧为 AWS 官方 access key 4 字符
#: 前缀 `AKIA` / `ASIA`(long-term + temporary)。
_SECRET_VALUE_MARKERS: tuple = (
    "bearer ",
    "sk-",
    "akia",
    "asia",
)


#: **CB-P5-03 承接(数据 PR-16 · Wave 3-L 主线 C)**:sanitize 值层扫描 gap。
#: 原 `startswith` 判据只覆盖字符串开头,不覆盖 Provider 错误消息值中间的
#: secret 字面量(如 `{"message": "Invalid api_key='sk-xxxxxxxxxxxxxxxx'"}`)。
#: 新增正则模式对字符串值做**内容级**扫描,命中即整值替换为 `"[REDACTED]"`。
#:
#: 正则设计原则:
#: - `sk-[A-Za-z0-9\-]{8,}` — OpenAI / Anthropic / test sentinel style key(8+ 字符
#:   防误伤裸 `sk-` 前缀但允许连字符 · 覆盖 `sk-INJECT-live-abc` sentinel 模式);
#: - `AKIA[0-9A-Z]{16}` — AWS long-term access key(严格 20 字符固定长度);
#: - `ASIA[0-9A-Z]{16}` — AWS temporary session access key;
#: - `Bearer\s+[A-Za-z0-9._~+/=\-]+` — OAuth / JWT bearer token。
_SECRET_VALUE_REGEX_PATTERNS: Tuple[Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9\-]{8,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=\-]+"),
)


# ---------------------------------------------------------------------------
# 值对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ViewError:
    """View 层 error 视图（任务 PR-5 起）。

    **任务 PR-5 不引入 `TaskErrorCategory` 枚举**（任务 PR-6 承接）；
    本 dataclass 只保留 raw string + friendly_zh 兜底 + retryable。
    未来 PR-6 会在此新增 `category: TaskErrorCategory` 字段而**不**删改
    已有字段（PR-6 增量演进）。
    """

    #: **必填** —— 上游原始错误文本（供审计）。
    raw: str
    #: **必填** —— 中文用户友好文案兜底。
    friendly_zh: str
    #: 是否可重试；rate_limit / timeout / upstream_5xx → True。
    retryable: bool = False
    #: 上游 Provider 机器码（如 `apimart:E1002`）。
    provider_code: Optional[str] = None
    #: 上游 Provider 原始消息。
    provider_message: Optional[str] = None
    #: 请求追踪 ID。
    request_id: Optional[str] = None


@dataclass(frozen=True)
class ProviderTaskView:
    """异构 Provider 任务状态的统一视图。

    字段清单严格对齐 [[Provider 适配体系治理方案]] §"ProviderTaskView"；
    本 PR 追加 `partial_success: bool`（用于 partial fixture 场景 —— outputs
    非空但存在失败子任务），以及 `schema_version` 契约字段。

    - `status` 值域严格限定于 :data:`KNOWN_VIEW_STATUSES`（6 canonical）；
      未识别字面量归一化为 `"unknown_recoverable"` 之前须先落 `waiting_upstream`
      + `recoverable=True` 或 `failed` + `recoverable=True`。**map 函数不产出
      canonical 以外的字面量**。
    - `outputs` 是 AssetRef list（每项含 `kind` / `source_url` / `mime` /
      `size_hint`）；本 PR 不落盘、不下载，只做引用。
    - `raw_excerpt` 已过 sanitize，绝无密钥类字面量。
    """

    provider_id: str
    upstream_task_id: Optional[str]
    status: str
    progress: Optional[float]
    outputs: Sequence[Mapping[str, Any]]
    error: Optional[ViewError]
    next_poll_after_ms: Optional[int]
    recoverable: bool
    remote_status: str
    raw_excerpt: Mapping[str, Any]
    partial_success: bool = False
    schema_version: str = "v1"
    #: **任务 PR-6 增量新增** —— 错误分类枚举。
    #: - error 为 None 且非 partial_success → category=None（兼容 PR-5 语义）
    #: - error 非空 → 由 :class:`ErrorCategoryMapper.categorize` 决定 14 值之一
    #: - error 为 None 但 partial_success=True → mapper 调用点填
    #:   :attr:`TaskErrorCategory.partial_success`
    category: Optional[TaskErrorCategory] = None

    def to_dict(self) -> dict:
        """把 view 展平成 dict（供 audit / debug 序列化）。"""

        payload: dict = {
            "provider_id": self.provider_id,
            "upstream_task_id": self.upstream_task_id,
            "status": self.status,
            "progress": self.progress,
            "outputs": [dict(item) for item in self.outputs],
            "next_poll_after_ms": self.next_poll_after_ms,
            "recoverable": self.recoverable,
            "remote_status": self.remote_status,
            "raw_excerpt": dict(self.raw_excerpt),
            "partial_success": self.partial_success,
            "schema_version": self.schema_version,
            "category": self.category.value if self.category is not None else None,
        }
        if self.error is None:
            payload["error"] = None
        else:
            payload["error"] = {
                "raw": self.error.raw,
                "friendly_zh": self.error.friendly_zh,
                "retryable": self.error.retryable,
                "provider_code": self.error.provider_code,
                "provider_message": self.error.provider_message,
                "request_id": self.error.request_id,
            }
        return payload


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _looks_like_secret_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(tok in lowered for tok in _SECRET_KEY_TOKENS)


def _looks_like_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower().strip()
    if any(lowered.startswith(mark) for mark in _SECRET_VALUE_MARKERS):
        return True
    # CB-P5-03(数据 PR-16 · Wave 3-L 主线 C):值内容级正则扫描 · 覆盖字符串
    # 中间的 secret 字面量(原 startswith 判据无法命中的 Provider error
    # message payload 场景)。
    if any(pattern.search(value) for pattern in _SECRET_VALUE_REGEX_PATTERNS):
        return True
    return False


def sanitize_raw_excerpt(raw: Any, *, max_depth: int = 6) -> Any:
    """递归剔除任何形似密钥的字段。

    命中判据:
    - key 名字含 `api_key / access_token / secret / bearer / authorization`
      等子串 → 值替换为 `"[REDACTED]"`。
    - value 是字符串且以 `Bearer ` / `sk-` / `AKIA` / `ASIA` 起头 → 值替换为
      `"[REDACTED]"`(**CB-P5-02** 数据 PR-16 收紧 · 原 `aki` 前缀过宽误伤
      `akira` / `akihabara` 等合法业务字符串)。
    - value 是字符串且**内部含** `sk-{16,}` / `AKIA{16}` / `ASIA{16}` /
      `Bearer <token>` 正则命中 → 值替换为 `"[REDACTED]"`(**CB-P5-03** 数据
      PR-16 承接 · 覆盖 Provider 错误消息中间的 secret 字面量场景)。
    - **容器**递归深度超 `max_depth` 时截断为 `"[TRUNCATED]"`(防病态大响
      应嵌套;只有 dict/list 计入深度,标量叶子不计)。

    返回值本身是新对象,不修改入参。
    """

    if isinstance(raw, Mapping):
        if max_depth <= 0:
            return "[TRUNCATED]"
        cleaned: dict = {}
        for key, value in raw.items():
            if _looks_like_secret_key(key):
                cleaned[str(key)] = "[REDACTED]"
                continue
            if _looks_like_secret_value(value):
                cleaned[str(key)] = "[REDACTED]"
                continue
            cleaned[str(key)] = sanitize_raw_excerpt(value, max_depth=max_depth - 1)
        return cleaned
    if isinstance(raw, (list, tuple)):
        if max_depth <= 0:
            return "[TRUNCATED]"
        return [sanitize_raw_excerpt(item, max_depth=max_depth - 1) for item in raw]
    if _looks_like_secret_value(raw):
        return "[REDACTED]"
    return raw


def _pick_str(mapping: Mapping[str, Any], *keys: str) -> Optional[str]:
    """在 mapping 里按顺序取第一个非空 str。"""

    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _pick_int(mapping: Mapping[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _pick_float(mapping: Mapping[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _flatten_data(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    """许多 Provider 把状态藏在 `data` 子对象里；返回合并后的浅拷贝。"""

    data = raw.get("data") if isinstance(raw, Mapping) else None
    if isinstance(data, Mapping):
        merged = dict(data)
        for key, value in raw.items():
            if key == "data":
                continue
            merged.setdefault(key, value)
        return merged
    return raw


def _outputs_from_urls(urls: Sequence[str], *, mime_hint: str = "image/png") -> list:
    """把 URL 列表折成 AssetRef list（kind=url）。"""

    refs: list = []
    for url in urls:
        text = str(url or "").strip()
        if not text:
            continue
        refs.append({"kind": "url", "source_url": text, "mime": mime_hint, "size_hint": None})
    return refs


def _make_error(
    *,
    raw: Optional[str],
    friendly_zh: str,
    retryable: bool = False,
    provider_code: Optional[str] = None,
    provider_message: Optional[str] = None,
    request_id: Optional[str] = None,
) -> ViewError:
    return ViewError(
        raw=str(raw or friendly_zh),
        friendly_zh=friendly_zh,
        retryable=retryable,
        provider_code=provider_code,
        provider_message=provider_message,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# 通用状态归一化（image / apimart / video 复用）
# ---------------------------------------------------------------------------


#: `main.image_task_status()` 上游返回的成功字面量集合（放大写不敏感）。
_IMAGE_SUCCESS_TOKENS: frozenset = frozenset(
    {"success", "successful", "succeed", "succeeded", "completed", "complete", "done", "finished", "ok", "ready"}
)


#: `main.image_task_status()` 上游返回的失败字面量集合（放大写不敏感）。
_IMAGE_FAILED_TOKENS: frozenset = frozenset(
    {"failure", "failed", "fail", "error", "errored", "rejected"}
)


#: 显式的取消字面量。
_CANCELLED_TOKENS: frozenset = frozenset({"canceled", "cancelled"})


#: 显式的超时字面量。
_TIMEOUT_TOKENS: frozenset = frozenset({"timeout", "timedout", "timed_out", "expired"})


#: 显式的限流字面量（部分 Provider 会把 429 转成 `rate_limit` 字符串放
#: 到 status 字段；否则从 error.code 抓）。
_RATE_LIMIT_TOKENS: frozenset = frozenset({"rate_limit", "rate_limited", "throttled", "too_many_requests"})


#: 显式的等待/排队字面量（含 PR-3 未映射的 `jimeng_pending / apimart_wait /
#: runninghub_wait` 等业务字面量）。
_WAITING_TOKENS: frozenset = frozenset(
    {
        "queued",
        "pending",
        "waiting",
        "wait",
        "in_queue",
        "created",
        "submitted",
        "jimeng_pending",
        "apimart_wait",
        "apimart_pending",
        "runninghub_wait",
        "runninghub_pending",
        "not_started",
        "processing_wait",
    }
)


#: 显式的运行中字面量。
_RUNNING_TOKENS: frozenset = frozenset(
    {"running", "processing", "in_progress", "generating", "in_generation", "started"}
)


def _classify_common_status(remote_status: str) -> Optional[str]:
    """把上游任意 status 字面量归一化到 canonical 6 之一。找不到返回 None。"""

    token = (remote_status or "").strip().lower()
    if not token:
        return None
    if token in _IMAGE_SUCCESS_TOKENS:
        return "succeeded"
    if token in _CANCELLED_TOKENS:
        return "cancelled"
    if token in _TIMEOUT_TOKENS:
        # 超时归 failed；由 error.retryable 表征可重试；view.status 保持 canonical。
        return "failed"
    if token in _RATE_LIMIT_TOKENS:
        return "failed"
    if token in _IMAGE_FAILED_TOKENS:
        return "failed"
    if token in _WAITING_TOKENS:
        return "waiting_upstream"
    if token in _RUNNING_TOKENS:
        return "running"
    return None


def _classify_status_with_error_signal(
    remote_status: str,
    *,
    error_signal: Optional[str] = None,
) -> tuple[str, bool]:
    """归一化状态并回传 `recoverable` 提示（`True` 表示可继续轮询/重试）。

    error_signal 的匹配是**子串**匹配（`rate_limit_exceeded` 命中
    `rate_limit`；`request_timeout` 命中 `timeout`），因此比 remote_status
    的严格集合匹配更宽松，用于覆盖各 Provider 的自定义 code 命名。
    """

    token = (remote_status or "").strip().lower()
    error_token = (error_signal or "").strip().lower()
    if token in _TIMEOUT_TOKENS or any(mark in error_token for mark in _TIMEOUT_TOKENS):
        return ("failed", True)
    if token in _RATE_LIMIT_TOKENS or "rate_limit" in error_token or "rate limit" in error_token or "throttl" in error_token:
        return ("failed", True)
    mapped = _classify_common_status(token)
    if mapped is None:
        # 未知字面量：先落 failed + recoverable=True，供 worker 进入 unknown_recoverable
        # 恢复扫描；view.status 严格 canonical。
        return ("failed", True)
    recoverable = mapped in {"waiting_upstream", "running"}
    return (mapped, recoverable)


# ---------------------------------------------------------------------------
# 7 Map 函数
# ---------------------------------------------------------------------------


def _extract_generic_urls(raw: Mapping[str, Any]) -> list[str]:
    """从常见 Provider 响应形状里挖 URL/b64 素材（尽力而为）。"""

    urls: list[str] = []
    if not isinstance(raw, Mapping):
        return urls
    containers: list[Any] = [raw]
    data = raw.get("data")
    if isinstance(data, Mapping):
        containers.append(data)
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        for key in ("results", "result", "outputs", "output", "images", "videos", "artifacts"):
            block = container.get(key)
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, str) and item.startswith(("http://", "https://")):
                        urls.append(item)
                    elif isinstance(item, Mapping):
                        for uk in ("url", "fileUrl", "file_url", "download_url", "downloadUrl", "imageUrl", "image_url"):
                            value = item.get(uk)
                            if isinstance(value, list) and value:
                                value = value[0]
                            if isinstance(value, str) and value:
                                urls.append(value)
                                break
            elif isinstance(block, Mapping):
                for uk in ("url", "fileUrl", "file_url", "download_url"):
                    value = block.get(uk)
                    if isinstance(value, str) and value:
                        urls.append(value)
                        break
    # 去重保序
    seen: set = set()
    ordered: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


def _extract_error_signal(raw: Mapping[str, Any]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """返回 `(raw_error_text, provider_code, provider_message)`。"""

    if not isinstance(raw, Mapping):
        return (None, None, None)
    error = raw.get("error")
    provider_code: Optional[str] = None
    provider_message: Optional[str] = None
    raw_text: Optional[str] = None
    if isinstance(error, Mapping):
        provider_code = _pick_str(error, "code", "type", "kind")
        provider_message = _pick_str(error, "message", "msg", "detail", "reason", "friendly")
        raw_text = provider_message or provider_code
    elif isinstance(error, str) and error.strip():
        raw_text = error.strip()
    if raw_text is None:
        raw_text = _pick_str(raw, "message", "msg", "detail", "reason", "fail_reason", "failReason")
    return (raw_text, provider_code, provider_message)


def _view(
    *,
    provider_id: str,
    upstream_task_id: Optional[str],
    status: str,
    progress: Optional[float],
    outputs: Sequence[Mapping[str, Any]],
    error: Optional[ViewError],
    next_poll_after_ms: Optional[int],
    recoverable: bool,
    remote_status: str,
    raw_excerpt: Mapping[str, Any],
    partial_success: bool = False,
) -> ProviderTaskView:
    """构造 view，同时做 canonical status 断言与 raw_excerpt sanitize。

    **任务 PR-6 增量**：`category` 字段在此处集中派生（零改 7 map 函数体）：
    - `error` 非 None → 走 :class:`ErrorCategoryMapper.categorize`（14 值之一）
    - `error` 为 None 但 `partial_success=True` → :attr:`TaskErrorCategory.partial_success`
    - `error` 为 None 且 `partial_success=False` → ``None``（兼容 PR-5 语义）
    """

    if status not in KNOWN_VIEW_STATUSES:
        raise ValueError(
            f"ProviderTaskView.status must be one of {sorted(KNOWN_VIEW_STATUSES)}, got {status!r}"
        )
    category: Optional[TaskErrorCategory]
    if error is not None:
        category = ErrorCategoryMapper.categorize(
            error, remote_status=remote_status, provider_id=provider_id
        )
    elif partial_success:
        category = TaskErrorCategory.partial_success
    else:
        category = None
    return ProviderTaskView(
        provider_id=provider_id,
        upstream_task_id=upstream_task_id,
        status=status,
        progress=progress,
        outputs=tuple(dict(item) for item in outputs),
        error=error,
        next_poll_after_ms=next_poll_after_ms,
        recoverable=recoverable,
        remote_status=remote_status,
        raw_excerpt=sanitize_raw_excerpt(raw_excerpt),
        partial_success=partial_success,
        category=category,
    )


def map_runninghub_task(raw: Mapping[str, Any]) -> ProviderTaskView:
    """映射 RunningHub `/task/openapi/status` 响应。

    RunningHub 常见形状：`{"code": 0, "data": {"taskId": ..., "status": ...,
    "results": [...]}}`；顶层 `status` / `taskStatus` 也可能出现。
    """

    if not isinstance(raw, Mapping):
        return _view(
            provider_id="runninghub",
            upstream_task_id=None,
            status="failed",
            progress=None,
            outputs=(),
            error=_make_error(raw="raw payload is not an object", friendly_zh="RunningHub 响应格式非法", retryable=False),
            next_poll_after_ms=None,
            recoverable=False,
            remote_status="",
            raw_excerpt={},
        )
    merged = _flatten_data(raw)
    upstream_id = _pick_str(merged, "taskId", "task_id", "id")
    remote_status = _pick_str(merged, "status", "state", "taskStatus", "task_status") or ""
    error_raw, provider_code, provider_message = _extract_error_signal(raw)
    canonical, recoverable_hint = _classify_status_with_error_signal(remote_status, error_signal=provider_code)

    outputs = _outputs_from_urls(_extract_generic_urls(raw))
    progress = _pick_float(merged, "progress", "percent", "percentage")
    next_poll = _pick_int(merged, "nextPollMs", "poll_after_ms", "retry_after_ms")

    partial = False
    error: Optional[ViewError] = None
    if canonical == "succeeded":
        if not outputs:
            # 声称成功但零素材 —— 触发 partial_success 场景；worker 应二次查询
            partial = True
            canonical = "waiting_upstream"
            recoverable_hint = True
    if canonical == "failed":
        error = _make_error(
            raw=error_raw or remote_status or "RunningHub task failed",
            friendly_zh=provider_message or "RunningHub 任务失败",
            retryable=recoverable_hint,
            provider_code=provider_code,
            provider_message=provider_message,
            request_id=_pick_str(merged, "requestId", "request_id", "traceId"),
        )

    return _view(
        provider_id="runninghub",
        upstream_task_id=upstream_id,
        status=canonical,
        progress=progress,
        outputs=outputs,
        error=error,
        next_poll_after_ms=next_poll,
        recoverable=recoverable_hint,
        remote_status=remote_status,
        raw_excerpt=raw,
        partial_success=partial,
    )


def _map_openai_style_image(raw: Mapping[str, Any], provider_id: str) -> ProviderTaskView:
    """openai-image / apimart / 通用图像任务的公共映射逻辑。"""

    if not isinstance(raw, Mapping):
        return _view(
            provider_id=provider_id,
            upstream_task_id=None,
            status="failed",
            progress=None,
            outputs=(),
            error=_make_error(raw="raw payload is not an object", friendly_zh=f"{provider_id} 响应格式非法"),
            next_poll_after_ms=None,
            recoverable=False,
            remote_status="",
            raw_excerpt={},
        )
    # 参照 main.py image_task_data / image_task_status 的字段优先级。
    task_block: Mapping[str, Any] = raw
    data = raw.get("data")
    if isinstance(data, Mapping):
        task_block = {**data, **{k: v for k, v in raw.items() if k != "data"}}
    upstream_id = _pick_str(task_block, "task_id", "taskId", "id", "job_id", "jobId")
    remote_status = _pick_str(task_block, "status", "task_status", "state") or ""
    error_raw, provider_code, provider_message = _extract_error_signal(raw)
    canonical, recoverable_hint = _classify_status_with_error_signal(remote_status, error_signal=provider_code)
    outputs = _outputs_from_urls(_extract_generic_urls(raw))
    progress = _pick_float(task_block, "progress", "percent")
    next_poll = _pick_int(task_block, "poll_after_ms", "retry_after_ms", "next_poll_ms")

    partial = False
    error: Optional[ViewError] = None
    if canonical == "succeeded" and not outputs:
        partial = True
        canonical = "waiting_upstream"
        recoverable_hint = True
    if canonical == "failed":
        fail_msg = provider_message or _pick_str(task_block, "fail_reason", "failReason", "message") or "生图任务失败"
        error = _make_error(
            raw=error_raw or remote_status or fail_msg,
            friendly_zh=fail_msg,
            retryable=recoverable_hint,
            provider_code=provider_code,
            provider_message=provider_message,
            request_id=_pick_str(task_block, "request_id", "requestId", "trace_id"),
        )
    return _view(
        provider_id=provider_id,
        upstream_task_id=upstream_id,
        status=canonical,
        progress=progress,
        outputs=outputs,
        error=error,
        next_poll_after_ms=next_poll,
        recoverable=recoverable_hint,
        remote_status=remote_status,
        raw_excerpt=raw,
        partial_success=partial,
    )


def map_apimart_task(raw: Mapping[str, Any]) -> ProviderTaskView:
    """映射 APIMart（OpenAI 兼容）异步图任务响应。"""

    return _map_openai_style_image(raw, provider_id="apimart")


def map_generic_image_task(raw: Mapping[str, Any]) -> ProviderTaskView:
    """映射通用 OpenAI 兼容图像任务（对齐 `main.wait_for_image_task`）。"""

    return _map_openai_style_image(raw, provider_id="openai-image")


def map_video_task(raw: Mapping[str, Any]) -> ProviderTaskView:
    """映射视频任务（volcengine / OpenAI Sora / apimart-video 通用形状）。

    与 image 的差别：mime_hint 用 `video/mp4`；进度字段常出现在
    `progress_percent`；rate_limit 命中位常在顶层 `error.type`。
    """

    if not isinstance(raw, Mapping):
        return _view(
            provider_id="openai-video",
            upstream_task_id=None,
            status="failed",
            progress=None,
            outputs=(),
            error=_make_error(raw="raw payload is not an object", friendly_zh="视频任务响应格式非法"),
            next_poll_after_ms=None,
            recoverable=False,
            remote_status="",
            raw_excerpt={},
        )
    merged = _flatten_data(raw)
    upstream_id = _pick_str(merged, "task_id", "taskId", "id", "job_id", "jobId", "video_id", "videoId")
    remote_status = _pick_str(merged, "status", "state", "phase") or ""
    error_raw, provider_code, provider_message = _extract_error_signal(raw)
    canonical, recoverable_hint = _classify_status_with_error_signal(remote_status, error_signal=provider_code)

    # 视频 URL 提取
    urls: list[str] = []
    for container in (raw, merged):
        if not isinstance(container, Mapping):
            continue
        for key in ("videos", "outputs", "video", "result"):
            block = container.get(key)
            if isinstance(block, list):
                for item in block:
                    if isinstance(item, str) and item.startswith(("http://", "https://")):
                        urls.append(item)
                    elif isinstance(item, Mapping):
                        value = _pick_str(item, "url", "video_url", "download_url", "fileUrl", "file_url")
                        if value:
                            urls.append(value)
            elif isinstance(block, Mapping):
                value = _pick_str(block, "url", "video_url", "download_url")
                if value:
                    urls.append(value)
            elif isinstance(block, str) and block.startswith(("http://", "https://")):
                urls.append(block)
    seen: set = set()
    ordered: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        ordered.append(u)
    outputs = _outputs_from_urls(ordered, mime_hint="video/mp4")
    progress = _pick_float(merged, "progress", "progress_percent", "percent")
    next_poll = _pick_int(merged, "poll_after_ms", "retry_after_ms")

    partial = False
    error: Optional[ViewError] = None
    if canonical == "succeeded" and not outputs:
        partial = True
        canonical = "waiting_upstream"
        recoverable_hint = True
    if canonical == "failed":
        error = _make_error(
            raw=error_raw or remote_status or "视频任务失败",
            friendly_zh=provider_message or "视频任务失败",
            retryable=recoverable_hint,
            provider_code=provider_code,
            provider_message=provider_message,
            request_id=_pick_str(merged, "request_id", "requestId", "trace_id"),
        )

    return _view(
        provider_id="openai-video",
        upstream_task_id=upstream_id,
        status=canonical,
        progress=progress,
        outputs=outputs,
        error=error,
        next_poll_after_ms=next_poll,
        recoverable=recoverable_hint,
        remote_status=remote_status,
        raw_excerpt=raw,
        partial_success=partial,
    )


def map_jimeng_task(raw: Mapping[str, Any]) -> ProviderTaskView:
    """映射 JiMeng CLI 输出。

    典型形状：`{"submit_id": ..., "gen_status": "success"|"pending"|"fail",
    "images": [...], "queue_info": {...}, "fail_reason": ...}`。

    `jimeng_pending` / `pending` + `queue_info` 归 `waiting_upstream`（补齐
    任务 PR-3 遗留字面量）。
    """

    if not isinstance(raw, Mapping):
        return _view(
            provider_id="jimeng",
            upstream_task_id=None,
            status="failed",
            progress=None,
            outputs=(),
            error=_make_error(raw="raw payload is not an object", friendly_zh="即梦响应格式非法"),
            next_poll_after_ms=None,
            recoverable=False,
            remote_status="",
            raw_excerpt={},
        )
    upstream_id = _pick_str(raw, "submit_id", "submitId", "task_id", "taskId", "id")
    remote_status = (
        _pick_str(raw, "gen_status", "status", "state")
        or ("jimeng_pending" if raw.get("jimeng_pending") else "")
    )
    error_raw = _pick_str(raw, "fail_reason", "failReason", "error", "message", "msg")
    fail_signal = str(error_raw or "").lower()
    # CB-P5-01 承接(Provider PR-A):jimeng CLI 退避信号识别 · 只识别不限流。
    # 汇总所有可能承载退避提示的字段(fail_signal + error_message +
    # queue_status),做子串匹配。命中 → rate_limited canonical + 可恢复。
    rate_limit_signal_parts: list = [fail_signal]
    rate_limit_msg = _pick_str(raw, "error_message", "rate_limit_message", "retry_message")
    if rate_limit_msg:
        rate_limit_signal_parts.append(rate_limit_msg.lower())
    queue_info_block = raw.get("queue_info") if isinstance(raw.get("queue_info"), Mapping) else {}
    queue_status_hint = _pick_str(queue_info_block, "queue_status", "status") if queue_info_block else None
    if queue_status_hint:
        rate_limit_signal_parts.append(queue_status_hint.lower())
    rate_limit_haystack = " ".join(part for part in rate_limit_signal_parts if part)
    rate_limit_hit_flag = bool(raw.get("rate_limit_hit"))
    has_retry_after = raw.get("retry_after") is not None
    # CB-P5-01 承接:只在 CLI 退避阶段(gen_status ∈ {jimeng_pending, ""})
    # 归 rate_limited。既有的 `gen_status='fail' + fail_reason='rate_limit'`
    # 场景是**上游终态错误** · 继续走 failed+error+category=rate_limit 路径
    # (保持 error_category T31 契约不变)。
    remote_lower = remote_status.lower()
    is_backoff_phase = (
        remote_lower in {"", "jimeng_pending"}
        or remote_lower in _WAITING_TOKENS
    )
    jimeng_rate_limit_hit = is_backoff_phase and (
        rate_limit_hit_flag
        or ("rate limit" in rate_limit_haystack)
        or ("rate_limit" in rate_limit_haystack)
        or ("retry after" in rate_limit_haystack)
        or ("retry_after" in rate_limit_haystack and has_retry_after)
        or ("throttl" in rate_limit_haystack)
        or ("quota" in rate_limit_haystack)
    )
    canonical: str
    recoverable_hint: bool
    partial = False
    error: Optional[ViewError] = None

    if remote_status.lower() in _CANCELLED_TOKENS:
        canonical, recoverable_hint = ("cancelled", False)
    elif jimeng_rate_limit_hit:
        canonical, recoverable_hint = ("rate_limited", True)
    elif "timeout" in fail_signal or remote_status.lower() in _TIMEOUT_TOKENS:
        canonical, recoverable_hint = ("failed", True)
    elif "rate" in fail_signal and "limit" in fail_signal:
        canonical, recoverable_hint = ("failed", True)
    else:
        canonical, recoverable_hint = _classify_status_with_error_signal(remote_status)

    outputs_urls: list[str] = []
    for key in ("images", "videos", "outputs", "urls"):
        block = raw.get(key)
        if isinstance(block, list):
            for item in block:
                if isinstance(item, str) and item.strip():
                    outputs_urls.append(item.strip())
                elif isinstance(item, Mapping):
                    value = _pick_str(item, "url", "download_url", "image_url", "video_url")
                    if value:
                        outputs_urls.append(value)
    outputs = _outputs_from_urls(outputs_urls)

    if canonical == "succeeded" and not outputs:
        # 即梦 CLI 声明 success 但零素材 —— 进入 partial 兜底
        partial = True
        canonical = "waiting_upstream"
        recoverable_hint = True

    if canonical == "failed":
        error = _make_error(
            raw=error_raw or remote_status or "即梦任务失败",
            friendly_zh=error_raw or "即梦任务失败",
            retryable=recoverable_hint,
        )
    elif canonical == "waiting_upstream" and raw.get("queue_info"):
        # 排队信息不产生 error；仅出现在 raw_excerpt 里
        pass

    queue_info = raw.get("queue_info") if isinstance(raw.get("queue_info"), Mapping) else {}
    next_poll = _pick_int(queue_info, "next_poll_after_ms", "retry_after_ms") if queue_info else None
    progress = _pick_float(raw, "progress", "percent")

    return _view(
        provider_id="jimeng",
        upstream_task_id=upstream_id,
        status=canonical,
        progress=progress,
        outputs=outputs,
        error=error,
        next_poll_after_ms=next_poll,
        recoverable=recoverable_hint,
        remote_status=remote_status,
        raw_excerpt=raw,
        partial_success=partial,
    )


def _infer_rate_limit_from_queue(queue_len: int) -> bool:
    """comfyui 通道:queue 总长度是否触发 rate_limit 识别。

    **CB-P5-01 承接(Provider PR-A · Wave 3-N.5 Batch 4 主线 B)**。
    骨架层:只做识别 · 不做限流。严格 `>` :data:`COMFYUI_QUEUE_RATE_LIMIT_THRESHOLD`
    判据 · 阈值 `= 10` 保持原类别。
    """

    try:
        length = int(queue_len)
    except (TypeError, ValueError):
        return False
    return length > COMFYUI_QUEUE_RATE_LIMIT_THRESHOLD


def map_comfy_task(raw: Mapping[str, Any]) -> ProviderTaskView:
    """映射 ComfyUI `/history/{prompt_id}` 响应。

    典型形状：`{"<prompt_id>": {"status": {"status_str": "success" |
    "error", "completed": bool, "messages": [...]}, "outputs": {...}}}`。
    空对象 `{}` 表示 prompt 还在队列中 → `waiting_upstream`。
    """

    if not isinstance(raw, Mapping):
        return _view(
            provider_id="comfyui",
            upstream_task_id=None,
            status="failed",
            progress=None,
            outputs=(),
            error=_make_error(raw="raw payload is not an object", friendly_zh="ComfyUI 响应格式非法"),
            next_poll_after_ms=None,
            recoverable=False,
            remote_status="",
            raw_excerpt={},
        )

    if not raw:
        return _view(
            provider_id="comfyui",
            upstream_task_id=None,
            status="waiting_upstream",
            progress=None,
            outputs=(),
            error=None,
            next_poll_after_ms=None,
            recoverable=True,
            remote_status="pending",
            raw_excerpt={},
        )

    # CB-P5-01 承接(Provider PR-A):comfyui `/queue` shape rate_limit 识别。
    # 顶层 `queue_running` + `queue_pending` 累计长度 > 阈值 → rate_limited。
    # `/history/{prompt_id}` shape 不含这两个 key,不影响原路径。
    if isinstance(raw.get("queue_running"), list) or isinstance(raw.get("queue_pending"), list):
        running_block = raw.get("queue_running") if isinstance(raw.get("queue_running"), list) else []
        pending_block = raw.get("queue_pending") if isinstance(raw.get("queue_pending"), list) else []
        queue_len_total = len(running_block) + len(pending_block)
        if _infer_rate_limit_from_queue(queue_len_total):
            return _view(
                provider_id="comfyui",
                upstream_task_id=None,
                status="rate_limited",
                progress=None,
                outputs=(),
                error=None,
                next_poll_after_ms=None,
                recoverable=True,
                remote_status="queue_saturated",
                raw_excerpt=raw,
            )

    prompt_id: Optional[str] = None
    payload: Mapping[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, Mapping):
            prompt_id = str(key)
            payload = value
            break

    status_block = payload.get("status") if isinstance(payload, Mapping) else None
    if not isinstance(status_block, Mapping):
        status_block = {}
    remote_status = _pick_str(status_block, "status_str", "state") or ""
    completed = bool(status_block.get("completed"))
    error_messages: list[str] = []
    messages = status_block.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, (list, tuple)) and len(msg) >= 2:
                head = str(msg[0]).lower()
                if "error" in head or "fail" in head:
                    error_messages.append(str(msg[1]))

    urls: list[str] = []
    outputs_block = payload.get("outputs")
    if isinstance(outputs_block, Mapping):
        for node_outputs in outputs_block.values():
            if not isinstance(node_outputs, Mapping):
                continue
            images = node_outputs.get("images") or node_outputs.get("gifs") or node_outputs.get("videos")
            if isinstance(images, list):
                for item in images:
                    if isinstance(item, Mapping):
                        filename = _pick_str(item, "filename")
                        subfolder = _pick_str(item, "subfolder") or ""
                        if filename:
                            rel = f"{subfolder}/{filename}" if subfolder else filename
                            urls.append(f"comfyui:/{rel}")
                    elif isinstance(item, str) and item:
                        urls.append(item)
    outputs = _outputs_from_urls(urls)

    partial = False
    error: Optional[ViewError] = None
    lowered = remote_status.lower()
    if lowered in _CANCELLED_TOKENS:
        canonical, recoverable_hint = ("cancelled", False)
    elif lowered == "error" or error_messages:
        canonical, recoverable_hint = ("failed", False)
    elif lowered == "success" or (completed and outputs):
        canonical = "succeeded"
        recoverable_hint = False
        if completed and not outputs:
            partial = True
            canonical = "waiting_upstream"
            recoverable_hint = True
    elif lowered in _RUNNING_TOKENS or (not completed and payload):
        canonical, recoverable_hint = ("running", True)
    else:
        canonical, recoverable_hint = ("waiting_upstream", True)

    if canonical == "failed":
        joined = "; ".join(error_messages) if error_messages else (remote_status or "ComfyUI prompt failed")
        error = _make_error(
            raw=joined,
            friendly_zh=(error_messages[0] if error_messages else "ComfyUI 工作流执行失败"),
            retryable=False,
        )

    return _view(
        provider_id="comfyui",
        upstream_task_id=prompt_id,
        status=canonical,
        progress=None,
        outputs=outputs,
        error=error,
        next_poll_after_ms=None,
        recoverable=recoverable_hint,
        remote_status=remote_status,
        raw_excerpt=raw,
        partial_success=partial,
    )


def map_chat_task(raw: Mapping[str, Any]) -> ProviderTaskView:
    """映射 Chat / OpenAI Responses 响应。

    Chat 大多同步返回；但 OpenAI Responses / Assistants 走 `status` +
    `id` 异步范式；本 mapper 兼容两者。

    - 有 `choices` 或 `output` 非空 → `succeeded`
    - `status="incomplete"` 且 `finish_reason="length"` → `failed` +
      retryable=True
    - 429 `rate_limit_exceeded` → `failed` + retryable=True
    """

    if not isinstance(raw, Mapping):
        return _view(
            provider_id="chat",
            upstream_task_id=None,
            status="failed",
            progress=None,
            outputs=(),
            error=_make_error(raw="raw payload is not an object", friendly_zh="Chat 响应格式非法"),
            next_poll_after_ms=None,
            recoverable=False,
            remote_status="",
            raw_excerpt={},
        )

    upstream_id = _pick_str(raw, "id", "response_id", "message_id")
    remote_status = _pick_str(raw, "status", "state", "object") or ""
    error_raw, provider_code, provider_message = _extract_error_signal(raw)

    finish_reason: Optional[str] = None
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, Mapping):
            finish_reason = _pick_str(first, "finish_reason", "stop_reason")

    partial = False
    error: Optional[ViewError] = None
    lowered = remote_status.lower()
    error_code_lower = (provider_code or "").lower()

    if error_raw and (
        "rate" in error_code_lower
        or "429" in error_code_lower
        or "rate_limit" in error_code_lower
    ):
        canonical = "failed"
        recoverable_hint = True
        error = _make_error(
            raw=error_raw,
            friendly_zh=provider_message or "调用速率超限，请稍后再试",
            retryable=True,
            provider_code=provider_code,
            provider_message=provider_message,
            request_id=_pick_str(raw, "request_id", "requestId"),
        )
    elif error_raw and ("timeout" in (error_code_lower + " " + (provider_message or "").lower())):
        canonical = "failed"
        recoverable_hint = True
        error = _make_error(
            raw=error_raw,
            friendly_zh=provider_message or "Chat 调用超时",
            retryable=True,
            provider_code=provider_code,
            provider_message=provider_message,
        )
    elif error_raw:
        canonical = "failed"
        recoverable_hint = False
        error = _make_error(
            raw=error_raw,
            friendly_zh=provider_message or "Chat 调用失败",
            retryable=False,
            provider_code=provider_code,
            provider_message=provider_message,
            request_id=_pick_str(raw, "request_id", "requestId"),
        )
    elif lowered in _CANCELLED_TOKENS:
        canonical = "cancelled"
        recoverable_hint = False
    elif lowered in {"incomplete"}:
        canonical = "failed"
        recoverable_hint = True
        error = _make_error(
            raw=finish_reason or "incomplete",
            friendly_zh="Chat 响应未完成",
            retryable=True,
        )
    elif lowered in {"completed", "success"} or (isinstance(choices, list) and choices):
        canonical = "succeeded"
        recoverable_hint = False
        if finish_reason == "length":
            # 输出被截断：算 partial
            partial = True
    elif lowered in _RUNNING_TOKENS:
        canonical = "running"
        recoverable_hint = True
    elif lowered in _WAITING_TOKENS:
        canonical = "waiting_upstream"
        recoverable_hint = True
    else:
        canonical = "failed"
        recoverable_hint = True
        error = _make_error(
            raw=remote_status or "unknown chat status",
            friendly_zh="Chat 状态未知",
            retryable=True,
        )

    return _view(
        provider_id="chat",
        upstream_task_id=upstream_id,
        status=canonical,
        progress=None,
        outputs=(),
        error=error,
        next_poll_after_ms=None,
        recoverable=recoverable_hint,
        remote_status=remote_status,
        raw_excerpt=raw,
        partial_success=partial,
    )
