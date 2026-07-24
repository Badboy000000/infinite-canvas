"""`app.adapters.provider.error_messages_zh` — 中文用户错误文案(Provider PR-03 骨架层)。

**定位**:纯文案表 · 按 `TaskError.code` 索引的用户可读文案。
每个 `code` 必须有唯一文案 · 文案不包含上游原文(provider_message 单独展示)。

**不做**:
- 不改旧 `friendly_*` 函数(新老并行两周 · 生产 PR 切换)
- 不改前端错误 UI

见 [[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-03。
"""
from __future__ import annotations

from typing import Mapping

# 文案表:code → 用户可读中文文案
ERROR_MESSAGES_ZH: Mapping[str, str] = {
    # 通用图像
    "generic_image.auth": "平台认证失败，请检查 API Key 是否有效",
    "generic_image.quota": "平台额度不足，请检查账户余额",
    "generic_image.rate_limit": "请求过于频繁，请稍后重试",
    "generic_image.validation": "请求参数有误，请检查输入内容",
    "generic_image.content_policy": "内容审核未通过，请调整输入内容",
    "generic_image.model_not_found": "模型不存在或已下线，请选择其他模型",
    "generic_image.upstream_5xx": "平台服务暂时不可用，请稍后重试",
    "generic_image.timeout": "平台响应超时，请稍后重试",
    "generic_image.download_failed": "图片下载失败，请检查网络连接",
    "generic_image.cost_exceeded": "任务成本超限，请降低复杂度或联系管理员",
    "generic_image.cancelled": "任务已取消",
    "generic_image.upstream_unavailable": "上游服务暂不可用，请稍后重试",
    "generic_image.recoverable_unknown": "任务异常，正在自动恢复",
    "generic_image.internal": "内部错误，请查看日志详情",

    # Chat
    "chat.auth": "对话认证失败，请检查 API Key",
    "chat.quota": "对话额度不足",
    "chat.rate_limit": "对话请求过于频繁，请稍后重试",
    "chat.content_policy": "对话内容审核未通过",
    "chat.timeout": "对话响应超时",
    "chat.internal": "对话服务内部错误",

    # RunningHub
    "runninghub.auth": "RunningHub 认证失败，请检查 API Key",
    "runninghub.quota": "RunningHub 钱包余额不足",
    "runninghub.rate_limit": "RunningHub 请求频率超限",
    "runninghub.timeout": "RunningHub 任务超时",
    "runninghub.upstream_5xx": "RunningHub 服务暂时不可用",
    "runninghub.content_policy": "RunningHub 内容审核未通过",
    "runninghub.internal": "RunningHub 内部错误",

    # Jimeng
    "jimeng.auth": "即梦 CLI 认证失败，请检查登录状态",
    "jimeng.rate_limit": "即梦请求频率超限，请稍后重试",
    "jimeng.content_policy": "即梦内容审核未通过，请调整提示词",
    "jimeng.timeout": "即梦任务超时，请稍后重试",
    "jimeng.internal": "即梦 CLI 执行异常",

    # 视频
    "video.auth": "视频平台认证失败",
    "video.quota": "视频生成额度不足",
    "video.download_failed": "视频下载失败，请检查网络连接",
    "video.content_policy": "视频内容审核未通过",
    "video.timeout": "视频生成超时",
    "video.internal": "视频服务内部错误",

    # 兜底
    "unknown.error": "发生未知错误，请联系管理员",
}


def get_error_message(code: str) -> str:
    """按 code 查中文文案 · 未命中返回兜底。"""
    return ERROR_MESSAGES_ZH.get(code, ERROR_MESSAGES_ZH["unknown.error"])


__all__ = [
    "ERROR_MESSAGES_ZH",
    "get_error_message",
]