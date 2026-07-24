"""`app.adapters.provider.schema_v2` — ApiProvider Schema v2 分组结构(Provider PR-07 骨架层)。

**定位**:Pydantic v2 分组模型 + v1 ↔ v2 双向映射纯函数 · **不接入路由** · 数据文件保持 v1 结构。

**分组结构**(治理方案 Provider 配置 Schema v2 §):
- ``identity``:id / name / protocol / description
- ``connection``:base_url / timeout / proxy_url
- ``credentials``(只读)· 永不出明文:has_key / key_fingerprint / key_env / key_updated_at
- ``capabilities``:image_generate / chat / video_generate / workflow_run 等
- ``models``:chat_models / image_models / video_models
- ``platform_specific``:volcengine / modelscope / runninghub / jimeng / codex / gemini_cli / comfyui
- ``runtime_hints``:cost_class / recommended_poll_ms 等

**契约要求**:
- v2 ``credentials`` 分组永远不出明文
- v1 ↔ v2 双向映射幂等
- ``platform_specific`` 只承接命名 provider 特有字段

**不做**:
- 不改 main.py 中的 ``normalize_provider()``
- 不改 ``/api/providers`` 路由
- 不改 ``data/api_providers.json`` 落盘结构

见 [[40 实施计划/Provider 适配体系治理实施计划与PR清单]] PR-07。
"""
from __future__ import annotations

import os
from typing import Any, Literal, Mapping, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# env flag
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})

PROVIDER_SCHEMA_V2_ENABLED_ENV = "PROVIDER_SCHEMA_V2_ENABLED"


def is_schema_v2_enabled() -> bool:
    """``PROVIDER_SCHEMA_V2_ENABLED`` 是否已开启(默认 false)。"""
    return os.environ.get(PROVIDER_SCHEMA_V2_ENABLED_ENV, "").strip() in _TRUTHY


# ---------------------------------------------------------------------------
# 分组模型
# ---------------------------------------------------------------------------


class ProviderConfigModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class IdentityGroup(ProviderConfigModel):
    id: str
    name: str
    protocol: str
    description: Optional[str] = None
    display_name: Optional[str] = None


class ConnectionGroup(ProviderConfigModel):
    base_url: Optional[str] = None
    timeout: Optional[int] = Field(default=None, ge=0)
    proxy_url: Optional[str] = None


class CredentialsGroup(ProviderConfigModel):
    """凭据分组 · 只读 · 永不出明文。"""

    has_key: bool = False
    key_fingerprint: Optional[str] = None
    key_env: Optional[str] = None
    key_updated_at: Optional[str] = None
    key_preview: Optional[str] = None


class CapabilitiesGroup(ProviderConfigModel):
    image_generate: bool = False
    image_edit: bool = False
    chat: bool = False
    chat_stream: bool = False
    video_generate: bool = False
    workflow_run: bool = False
    asset_upload: bool = False


class ModelsGroup(ProviderConfigModel):
    chat_models: Tuple[str, ...] = ()
    image_models: Tuple[str, ...] = ()
    video_models: Tuple[str, ...] = ()


class PlatformSpecificGroup(ProviderConfigModel):
    """平台特有字段 · 只承接命名 provider · 未列平台走 extras。"""

    volcengine: Optional[Mapping[str, Any]] = None
    modelscope: Optional[Mapping[str, Any]] = None
    runninghub: Optional[Mapping[str, Any]] = None
    jimeng: Optional[Mapping[str, Any]] = None
    codex: Optional[Mapping[str, Any]] = None
    gemini_cli: Optional[Mapping[str, Any]] = None
    comfyui: Optional[Mapping[str, Any]] = None


class RuntimeHintsGroup(ProviderConfigModel):
    cost_class: Literal["free", "low", "medium", "high", "per_second_video"] = "medium"
    recommended_poll_ms: int = Field(default=1000, ge=0)
    max_poll_ms: int = Field(default=30000, ge=0)


class ApiProviderPayloadV2(ProviderConfigModel):
    """Schema v2 · 分组结构主入口。"""

    identity: IdentityGroup
    connection: ConnectionGroup = Field(default_factory=lambda: ConnectionGroup())
    credentials: CredentialsGroup = Field(default_factory=lambda: CredentialsGroup())
    capabilities: CapabilitiesGroup = Field(default_factory=lambda: CapabilitiesGroup())
    models: ModelsGroup = Field(default_factory=lambda: ModelsGroup())
    platform_specific: PlatformSpecificGroup = Field(default_factory=lambda: PlatformSpecificGroup())
    runtime_hints: RuntimeHintsGroup = Field(default_factory=lambda: RuntimeHintsGroup())


# ---------------------------------------------------------------------------
# v1 ↔ v2 双向映射
# ---------------------------------------------------------------------------


# v1 扁平字段名 → v2 分组路径
_V1_FIELD_TO_GROUP: Mapping[str, str] = {
    # identity
    "id": "identity.id",
    "name": "identity.name",
    "protocol": "identity.protocol",
    "description": "identity.description",
    "display_name": "identity.display_name",
    # connection
    "base_url": "connection.base_url",
    "timeout": "connection.timeout",
    "proxy_url": "connection.proxy_url",
    # credentials(read-only 分组)
    "has_key": "credentials.has_key",
    "key_fingerprint": "credentials.key_fingerprint",
    "key_env": "credentials.key_env",
    "key_updated_at": "credentials.key_updated_at",
    "key_preview": "credentials.key_preview",
    # capabilities
    "image_generate": "capabilities.image_generate",
    "image_edit": "capabilities.image_edit",
    "chat": "capabilities.chat",
    "chat_stream": "capabilities.chat_stream",
    "video_generate": "capabilities.video_generate",
    "workflow_run": "capabilities.workflow_run",
    "asset_upload": "capabilities.asset_upload",
    # models
    "chat_models": "models.chat_models",
    "image_models": "models.image_models",
    "video_models": "models.video_models",
    # runtime_hints
    "cost_class": "runtime_hints.cost_class",
    "recommended_poll_ms": "runtime_hints.recommended_poll_ms",
    "max_poll_ms": "runtime_hints.max_poll_ms",
}


_PLATFORM_KEYS = frozenset({
    "volcengine", "modelscope", "runninghub", "jimeng",
    "codex", "gemini_cli", "comfyui",
})


# P0 密钥零泄漏:v1 → v2 剔除的字段
_V1_SECRET_FIELDS = frozenset({
    "api_key",
    "wallet_api_key",
    "access_key_id",
    "secret_access_key",
    "volcengine_access_key_id",
    "volcengine_secret_access_key",
})


def v1_to_v2(v1_payload: Mapping[str, Any]) -> dict:
    """v1 扁平结构 → v2 分组结构 · 纯函数。

    P0 密钥零泄漏:严禁字段(_V1_SECRET_FIELDS)在输出中不出现。

    Args:
        v1_payload: v1 扁平字段字典(通常来自 GET /api/providers)。

    Returns:
        v2 分组 dict(直接 dict · 便于测试断言;正式使用可 ``ApiProviderPayloadV2.model_validate``)。
    """
    result: dict = {
        "identity": {},
        "connection": {},
        "credentials": {},
        "capabilities": {},
        "models": {},
        "platform_specific": {},
        "runtime_hints": {},
    }

    for key, value in v1_payload.items():
        # P0 密钥严禁通过
        if key in _V1_SECRET_FIELDS:
            continue

        if key in _V1_FIELD_TO_GROUP:
            group, subkey = _V1_FIELD_TO_GROUP[key].split(".")
            result[group][subkey] = value
        elif key in _PLATFORM_KEYS and isinstance(value, dict):
            # 平台特有 · 剔除密钥字段
            result["platform_specific"][key] = {
                k: v for k, v in value.items()
                if k not in _V1_SECRET_FIELDS
            }
        # 其他扁平字段 · 骨架层放入 extras(通过 extra="allow" 保留)
        else:
            result.setdefault("extras", {})[key] = value

    return result


def v2_to_v1(v2_payload: Mapping[str, Any]) -> dict:
    """v2 分组结构 → v1 扁平字段 · 纯函数。

    v2 → v1 幂等:v1_to_v2 → v2_to_v1 应等价于原 v1(不含密钥字段)。

    Args:
        v2_payload: v2 分组字典。

    Returns:
        v1 扁平字段 dict。
    """
    result: dict = {}

    # 反向映射
    reverse: dict = {}
    for v1_key, path in _V1_FIELD_TO_GROUP.items():
        group, subkey = path.split(".")
        reverse[(group, subkey)] = v1_key

    for group, group_payload in v2_payload.items():
        if group == "platform_specific" and isinstance(group_payload, dict):
            for platform, platform_data in group_payload.items():
                if platform_data is not None:
                    result[platform] = dict(platform_data)
            continue
        if group == "extras" and isinstance(group_payload, dict):
            result.update(group_payload)
            continue
        if not isinstance(group_payload, dict):
            continue
        for subkey, value in group_payload.items():
            v1_key = reverse.get((group, subkey))
            if v1_key:
                result[v1_key] = value

    return result


__all__ = [
    "PROVIDER_SCHEMA_V2_ENABLED_ENV",
    "IdentityGroup",
    "ConnectionGroup",
    "CredentialsGroup",
    "CapabilitiesGroup",
    "ModelsGroup",
    "PlatformSpecificGroup",
    "RuntimeHintsGroup",
    "ApiProviderPayloadV2",
    "v1_to_v2",
    "v2_to_v1",
    "is_schema_v2_enabled",
]
