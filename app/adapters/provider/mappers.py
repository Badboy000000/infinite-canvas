"""`app.adapters.provider.mappers` — 六套现存轮询响应 → ProviderTaskView(Provider PR-02 骨架层)。

**定位**:纯函数 · 每个映射函数接收上游 payload dict · 返回 `ProviderTaskView` frozen value object。
本模块**不 hook** main.py 中的六处响应挂载点 · 生产切换归后续 PR。

**六个映射函数**(治理方案现存函数迁移映射 §):
- ``generic_image_payload_to_view(payload) -> ProviderTaskView``:通用图像 provider(Comfly / APIMart / ModelScope 等)
- ``runninghub_payload_to_view(payload) -> ProviderTaskView``:RunningHub OpenAPI 任务
- ``video_payload_to_view(payload) -> ProviderTaskView``:视频 provider(Veo3-fast 等)
- ``jimeng_payload_to_view(payload) -> ProviderTaskView``:即梦 CLI 输出
- ``comfyui_payload_to_view(payload) -> ProviderTaskView``:ComfyUI /history 轮询
- ``canvas_task_payload_to_view(payload) -> ProviderTaskView``:画布本地任务

**契约要求**:
- 只输出 `providerTaskView` 副字段 · 不删除任何上游字段
- `status` 严格来自 `ProviderTaskViewStatus` 6 值枚举
- `outputs: tuple[AssetRef, ...]` 保留原路径来源
- `raw_excerpt` 只保留白名单字段并脱敏(P0 密钥零泄漏防线)

**不做**:
- 不修改 main.py 六处响应组装点
- 不引入 Adapter 分派
- 不改数据库 / 文件

见 [[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-02。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from app.adapters.provider.base import (
    AssetRef,
    ProviderTaskView,
    ProviderTaskViewStatus,
    TaskError,
    TaskErrorCategory,
)


# ---------------------------------------------------------------------------
# 常量 · 状态映射表
# ---------------------------------------------------------------------------


# 通用图像 provider 状态映射(Comfly / APIMart / ModelScope)
_GENERIC_STATUS_MAP: Mapping[str, ProviderTaskViewStatus] = {
    "pending": "queued",
    "queued": "queued",
    "in_progress": "running",
    "running": "running",
    "succeeded": "succeeded",
    "completed": "succeeded",
    "success": "succeeded",
    "failed": "failed",
    "error": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "waiting": "waiting_upstream",
}

# RunningHub 状态映射
_RUNNINGHUB_STATUS_MAP: Mapping[str, ProviderTaskViewStatus] = {
    "queued": "queued",
    "pending": "queued",
    "running": "running",
    "success": "succeeded",
    "succeeded": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

# 视频 provider 状态
_VIDEO_STATUS_MAP: Mapping[str, ProviderTaskViewStatus] = {
    "pending": "queued",
    "queued": "queued",
    "processing": "running",
    "running": "running",
    "succeeded": "succeeded",
    "completed": "succeeded",
    "failed": "failed",
    "error": "failed",
    "cancelled": "cancelled",
}

# Jimeng CLI 状态
_JIMENG_STATUS_MAP: Mapping[str, ProviderTaskViewStatus] = {
    "pending": "queued",
    "jimeng_pending": "waiting_upstream",
    "waiting_upstream": "waiting_upstream",
    "running": "running",
    "succeeded": "succeeded",
    "success": "succeeded",
    "failed": "failed",
    "error": "failed",
    "rate_limit": "failed",
}

# ComfyUI 状态(基于 /history 消息形态)
_COMFYUI_STATUS_MAP: Mapping[str, ProviderTaskViewStatus] = {
    "queued": "queued",
    "running": "running",
    "success": "succeeded",
    "succeeded": "succeeded",
    "failed": "failed",
    "error": "failed",
}

# 画布本地任务
_CANVAS_STATUS_MAP: Mapping[str, ProviderTaskViewStatus] = {
    "queued": "queued",
    "running": "running",
    "succeeded": "succeeded",
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
    "waiting": "waiting_upstream",
}


# raw_excerpt 白名单(严禁字段 · 与部署 PR-10 redaction 双层防线)
_ALLOWED_RAW_EXCERPT_FIELDS = frozenset({
    "status",
    "state",
    "message",
    "progress",
    "task_id",
    "id",
    "created_at",
    "updated_at",
    "elapsed_ms",
})


def _sanitize_raw_excerpt(payload: Mapping[str, Any]) -> dict:
    """从 payload 抽取白名单字段 · 严禁密钥泄漏。"""
    return {
        k: v for k, v in payload.items()
        if k in _ALLOWED_RAW_EXCERPT_FIELDS
    }


def _map_status(
    raw_status: Optional[str],
    status_map: Mapping[str, ProviderTaskViewStatus],
    default: ProviderTaskViewStatus = "running",
) -> ProviderTaskViewStatus:
    """状态映射兜底(未识别时返回 default)。"""
    if not raw_status:
        return default
    return status_map.get(raw_status.lower(), default)


def _extract_outputs(
    payload: Mapping[str, Any],
    *,
    url_keys: tuple[str, ...] = ("url", "output_url", "image_url"),
) -> tuple[AssetRef, ...]:
    """从 payload 抽取 outputs(URL 或 local_path)。

    骨架层只处理 url 类 · 复杂 outputs 结构留给生产 PR。
    """
    outputs: list[AssetRef] = []

    # 常见:images 数组
    images = payload.get("images")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict):
                url = None
                for k in url_keys:
                    if k in item:
                        url = item[k]
                        break
                if url:
                    outputs.append(AssetRef(kind="url", source_url_or_bytes=str(url)))
            elif isinstance(item, str):
                outputs.append(AssetRef(kind="url", source_url_or_bytes=item))

    # outputs 数组(RunningHub)
    if not outputs:
        outputs_field = payload.get("outputs")
        if isinstance(outputs_field, list):
            for item in outputs_field:
                if isinstance(item, str):
                    outputs.append(AssetRef(kind="url", source_url_or_bytes=item))
                elif isinstance(item, dict):
                    for k in url_keys:
                        if k in item:
                            outputs.append(
                                AssetRef(kind="url", source_url_or_bytes=str(item[k]))
                            )
                            break

    # 单一 url / output_url 字段
    if not outputs:
        for k in url_keys:
            if k in payload and isinstance(payload[k], str):
                outputs.append(AssetRef(kind="url", source_url_or_bytes=payload[k]))
                break

    return tuple(outputs)


# ---------------------------------------------------------------------------
# 六个 mapper 主入口
# ---------------------------------------------------------------------------


def generic_image_payload_to_view(payload: Mapping[str, Any]) -> ProviderTaskView:
    """通用图像 provider payload → ProviderTaskView(Comfly / APIMart / ModelScope)。

    Args:
        payload: 上游轮询响应字典。

    Returns:
        ProviderTaskView。
    """
    status = _map_status(
        payload.get("status") or payload.get("state"),
        _GENERIC_STATUS_MAP,
    )
    outputs = _extract_outputs(payload)
    remote_status = str(payload.get("status") or payload.get("state") or "")

    progress = payload.get("progress")
    if isinstance(progress, (int, float)):
        progress = float(progress)
        if progress > 1.0:
            progress = progress / 100.0
    else:
        progress = None

    return ProviderTaskView(
        provider_id=str(payload.get("provider_id") or payload.get("provider") or "generic"),
        upstream_task_id=payload.get("task_id") or payload.get("id"),
        status=status,
        progress=progress,
        outputs=outputs,
        remote_status=remote_status,
        raw_excerpt=_sanitize_raw_excerpt(payload),
    )


def runninghub_payload_to_view(payload: Mapping[str, Any]) -> ProviderTaskView:
    """RunningHub OpenAPI 任务 payload → ProviderTaskView。"""
    status = _map_status(
        payload.get("status") or payload.get("taskStatus"),
        _RUNNINGHUB_STATUS_MAP,
    )
    outputs = _extract_outputs(payload)
    remote_status = str(payload.get("status") or payload.get("taskStatus") or "")

    return ProviderTaskView(
        provider_id="runninghub",
        upstream_task_id=payload.get("taskId") or payload.get("task_id"),
        status=status,
        outputs=outputs,
        remote_status=remote_status,
        raw_excerpt=_sanitize_raw_excerpt(payload),
    )


def video_payload_to_view(payload: Mapping[str, Any]) -> ProviderTaskView:
    """视频 provider 任务 payload → ProviderTaskView。"""
    status = _map_status(
        payload.get("status"),
        _VIDEO_STATUS_MAP,
    )
    outputs = _extract_outputs(payload, url_keys=("video_url", "url", "output_url"))
    remote_status = str(payload.get("status") or "")

    return ProviderTaskView(
        provider_id=str(payload.get("provider") or "video"),
        upstream_task_id=payload.get("task_id") or payload.get("id"),
        status=status,
        outputs=outputs,
        remote_status=remote_status,
        raw_excerpt=_sanitize_raw_excerpt(payload),
    )


def jimeng_payload_to_view(payload: Mapping[str, Any]) -> ProviderTaskView:
    """即梦 CLI 输出 → ProviderTaskView。"""
    status = _map_status(
        payload.get("gen_status") or payload.get("status"),
        _JIMENG_STATUS_MAP,
    )
    outputs = _extract_outputs(payload)
    remote_status = str(payload.get("gen_status") or payload.get("status") or "")

    return ProviderTaskView(
        provider_id="jimeng",
        upstream_task_id=payload.get("task_id"),
        status=status,
        outputs=outputs,
        remote_status=remote_status,
        raw_excerpt=_sanitize_raw_excerpt(payload),
    )


def comfyui_payload_to_view(payload: Mapping[str, Any]) -> ProviderTaskView:
    """ComfyUI /history 轮询 payload → ProviderTaskView。"""
    # ComfyUI 状态判断:优先 status_str · fallback 从 outputs 推断
    raw_status = payload.get("status_str") or payload.get("status")
    if not raw_status:
        # 有 outputs = success · 有 error = failed · 都无 = running
        if payload.get("error"):
            raw_status = "failed"
        elif payload.get("outputs") or payload.get("images"):
            raw_status = "success"
        else:
            raw_status = "running"

    status = _map_status(raw_status, _COMFYUI_STATUS_MAP)
    outputs = _extract_outputs(payload)
    remote_status = str(raw_status or "")

    return ProviderTaskView(
        provider_id="comfyui",
        upstream_task_id=payload.get("prompt_id") or payload.get("task_id"),
        status=status,
        outputs=outputs,
        remote_status=remote_status,
        raw_excerpt=_sanitize_raw_excerpt(payload),
    )


def canvas_task_payload_to_view(payload: Mapping[str, Any]) -> ProviderTaskView:
    """画布本地任务 payload → ProviderTaskView。"""
    status = _map_status(
        payload.get("status"),
        _CANVAS_STATUS_MAP,
    )
    outputs = _extract_outputs(payload)
    remote_status = str(payload.get("status") or "")

    return ProviderTaskView(
        provider_id=str(payload.get("provider_id") or "canvas_local"),
        upstream_task_id=payload.get("task_id") or payload.get("id"),
        status=status,
        outputs=outputs,
        remote_status=remote_status,
        raw_excerpt=_sanitize_raw_excerpt(payload),
    )


__all__ = [
    "generic_image_payload_to_view",
    "runninghub_payload_to_view",
    "video_payload_to_view",
    "jimeng_payload_to_view",
    "comfyui_payload_to_view",
    "canvas_task_payload_to_view",
]
