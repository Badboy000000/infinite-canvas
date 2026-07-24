"""`app.security.cors` — CORS 按部署模式生效策略(部署 PR-07 骨架层)。

**定位**:纯函数 + frozen dataclass · env flag 默认关闭 · 与旧行为等价(`allow_origins=["*"]`)。

**骨架契约**:
- ``CorsPolicy``:frozen dataclass · 按部署模式保存 CORS 配置
- ``build_cors_policy(mode, allowed_origins)``:纯函数 · 返回 ``CorsPolicy``
- ``is_cors_mode_aware_enabled()``:env flag ``CORS_MODE_AWARE_ENABLED`` 判据

**默认策略**(治理方案 M2 明示):
- ``local_personal``:``allow_origins=["*"]`` · ``allow_credentials=False``
- ``intranet_team``:读取 ``IC_CORS_ALLOWED_ORIGINS`` · 空则回退同源(``[]``)
- ``public_team``:必须白名单非空 · 缺失即 fail-fast

**不做**:
- 不替换 ``main.py`` 现有 ``CORSMiddleware(allow_origins=["*"])`` (生产切换归后续 PR)
- 不实现 CSRF(归后续 PR)
- 不改 Cookie 策略

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] PR-07。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Tuple

DeploymentMode = Literal["local_personal", "intranet_team", "public_team"]


# ---------------------------------------------------------------------------
# env flag
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})

CORS_MODE_AWARE_ENABLED_ENV = "CORS_MODE_AWARE_ENABLED"


def is_cors_mode_aware_enabled() -> bool:
    """``CORS_MODE_AWARE_ENABLED`` 是否已开启(默认 false)。"""
    return os.environ.get(CORS_MODE_AWARE_ENABLED_ENV, "").strip() in _TRUTHY


# ---------------------------------------------------------------------------
# CorsPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorsPolicy:
    """CORS 策略 · frozen · 与 FastAPI CORSMiddleware 参数一一映射。

    Attributes:
        allow_origins: 允许的 origin 列表(``["*"]`` = 全部允许)。
        allow_credentials: 是否允许携带凭据(``*`` 与 ``allow_credentials=True`` 互斥)。
        allow_methods: 允许的 HTTP 方法(默认 ``["*"]``)。
        allow_headers: 允许的 HTTP 请求头。
        fail_fast: ``public_team`` 白名单为空时是否 fail-fast。
    """

    allow_origins: Tuple[str, ...] = ("*",)
    allow_credentials: bool = False
    allow_methods: Tuple[str, ...] = ("*",)
    allow_headers: Tuple[str, ...] = ("*",)
    fail_fast: bool = False


# 默认策略:对应 local_personal(与旧行为等价)
DEFAULT_CORS_POLICY = CorsPolicy()


# public_team 精确方法列表
_PUBLIC_TEAM_METHODS = (
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
)

# public_team 精确请求头列表(含 X-CSRF-Token)
_PUBLIC_TEAM_HEADERS = (
    "Accept",
    "Authorization",
    "Content-Type",
    "X-Request-Id",
    "X-CSRF-Token",
    "X-User-Id",
)


def build_cors_policy(
    mode: DeploymentMode = "local_personal",
    allowed_origins: Optional[List[str]] = None,
) -> CorsPolicy:
    """按部署模式构建 CORS 策略 · 纯函数。

    Args:
        mode: 部署模式。
        allowed_origins: 白名单(来自 ``IC_CORS_ALLOWED_ORIGINS`` 解析结果)。

    Returns:
        ``CorsPolicy``。

    Raises:
        ValueError: ``public_team`` 模式下白名单为空或 None。
    """
    if mode == "local_personal":
        return CorsPolicy(
            allow_origins=("*",),
            allow_credentials=False,
            allow_methods=("*",),
            allow_headers=("*",),
        )

    if mode == "intranet_team":
        origins = tuple(allowed_origins) if allowed_origins else ()
        return CorsPolicy(
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=("*",),
            allow_headers=("*",),
        )

    # public_team
    if not allowed_origins:
        raise ValueError(
            "public_team mode requires non-empty IC_CORS_ALLOWED_ORIGINS"
        )
    return CorsPolicy(
        allow_origins=tuple(allowed_origins),
        allow_credentials=True,
        allow_methods=_PUBLIC_TEAM_METHODS,
        allow_headers=_PUBLIC_TEAM_HEADERS,
        fail_fast=True,
    )


def parse_allowed_origins(raw: Optional[str]) -> List[str]:
    """解析 ``IC_CORS_ALLOWED_ORIGINS`` 环境变量 · 逗号分隔。

    Args:
        raw: 原始值(可为 None 或空字符串)。

    Returns:
        strip 后的 origin 列表。
    """
    if not raw:
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


__all__ = [
    "CORS_MODE_AWARE_ENABLED_ENV",
    "CorsPolicy",
    "DEFAULT_CORS_POLICY",
    "build_cors_policy",
    "parse_allowed_origins",
    "is_cors_mode_aware_enabled",
    "DeploymentMode",
]