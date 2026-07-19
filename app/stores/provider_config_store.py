"""Provider config store facade — 数据模型治理 PR-0 + PR-4 shadow 双读。

包裹 `main.py` 中 API 提供商配置读写函数
`load_api_providers` / `save_api_providers`。密钥仍走 `API/.env` 现有路径，
本 facade 不做任何脱敏或转换——完全透传。

**数据 PR-4**（Wave 3-C）：`load_api_providers()` 在 JSON 读成功后惰性触发
`read_shadow()`；shadow diff 只承载 `_PROVIDER_SNAPSHOT_FIELD_ORDER` 白名单
字段 —— 密钥字段永不进 shadow diff 日志（走 `_safe_provider_records`
深层脱敏；数据 PR-3 抗回归模式）。

后续 Provider 适配体系治理 PR 落地后会补齐 provider protocol 抽象，
本 facade 的签名保持稳定。
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .legacy_snapshot import (
    SchemaVersion,
    build_snapshot,
    read_json_source,
    serialize_json,
)


DOMAIN = "provider_config"


_PROVIDER_SNAPSHOT_FIELD_ORDER = (
    "id", "name", "base_url", "protocol", "image_request_mode",
    "image_generation_endpoint", "image_edit_endpoint", "enabled", "primary",
    "image_models", "chat_models", "video_models", "model_names",
    "model_protocols", "ms_loras", "ms_defaults_version", "rh_apps",
    "rh_workflows", "volcengine_project_name", "volcengine_region",
)
PROVIDER_SNAPSHOT_FIELDS = frozenset(_PROVIDER_SNAPSHOT_FIELD_ORDER)

_SENSITIVE_FIELD_NAMES = frozenset({
    "accesstoken", "apikey", "authorization", "clientsecret", "credential",
    "key", "password", "privatekey", "secret", "secretaccesskey",
    "sessionsecret", "token", "walletkey",
})
_SENSITIVE_NAME_MARKERS = ("field", "key", "label", "name", "type")
_SENSITIVE_VALUE_FIELDS = frozenset({
    "currentvalue", "defaultvalue", "value",
})


def load_api_providers(*args: Any, **kwargs: Any) -> Any:
    from main import load_api_providers as _impl
    result = _impl(*args, **kwargs)
    # 数据 PR-4 shadow read hook；env 关闭时零开销 return。
    read_shadow(result)
    return result


def save_api_providers(*args: Any, **kwargs: Any) -> Any:
    from main import save_api_providers as _impl
    return _impl(*args, **kwargs)


def _is_sensitive_field(name: Any) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    return normalized in _SENSITIVE_FIELD_NAMES or any(
        normalized.startswith(prefix) or normalized.endswith(prefix)
        for prefix in (
            "apikey", "accesstoken", "authtoken", "clientsecret",
            "credential", "password", "privatekey", "secretaccesskey",
            "sessionsecret", "walletkey",
        )
    )


def _sanitize_url_query(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if not parsed.query or not (parsed.scheme and parsed.netloc):
        return value
    safe_query = [
        (name, item)
        for name, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not _is_sensitive_field(name)
    ]
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(safe_query, doseq=True),
        parsed.fragment,
    ))


def _has_sensitive_name_value_marker(value: dict[Any, Any]) -> bool:
    return any(
        re.sub(r"[^a-z0-9]", "", str(key).lower()) in _SENSITIVE_NAME_MARKERS
        and _is_sensitive_field(item)
        for key, item in value.items()
    )


def _sanitize_string(value: str) -> str:
    safe_value = _sanitize_url_query(value)
    stripped = safe_value.strip()
    if not stripped.startswith(("{", "[")):
        return safe_value
    try:
        nested = json.loads(stripped)
    except (TypeError, ValueError):
        return safe_value
    return serialize_json(_sanitize_nested(nested))


def _sanitize_nested(value: Any) -> Any:
    if isinstance(value, dict):
        hides_value = _has_sensitive_name_value_marker(value)
        return {
            key: _sanitize_nested(item)
            for key, item in value.items()
            if not _is_sensitive_field(key)
            and not (
                hides_value
                and re.sub(r"[^a-z0-9]", "", str(key).lower())
                in _SENSITIVE_VALUE_FIELDS
            )
        }
    if isinstance(value, list):
        return [_sanitize_nested(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    return value


def _safe_provider_records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {
            key: _sanitize_nested(item[key])
            for key in _PROVIDER_SNAPSHOT_FIELD_ORDER
            if key in item
        }
        for item in value
        if isinstance(item, dict)
    ]


def read_shadow(json_snapshot: Any, *, request_id: str | None = None) -> None:
    """Shadow-read entry；`load_api_providers` 读成功后调用。

    **硬约束**：diff 只对 `_safe_provider_records()` 输出的白名单字段做，
    密钥字段永不进入 diff 日志。
    """

    from app.shadow_read.runner import is_shadow_read_enabled, run_shadow_read

    if not is_shadow_read_enabled(DOMAIN):
        return
    # `load_api_providers` 原返回 raw list；这里先剥离到白名单字段后再送
    # runner —— 双保险：即使 runner 出错，也不会有密钥出现在 log 里。
    safe_payload = _safe_provider_records(json_snapshot)
    run_shadow_read(DOMAIN, safe_payload, request_id=request_id)


def snapshot() -> dict[str, Any]:
    from main import API_PROVIDERS_FILE

    source_payload, _ = read_json_source(API_PROVIDERS_FILE, [])
    payload = _safe_provider_records(source_payload)
    safe_raw_json = serialize_json(payload)
    return build_snapshot(
        payload,
        raw_json=safe_raw_json,
        schema_version=SchemaVersion.PROVIDER_CONFIG,
        legacy_path=API_PROVIDERS_FILE,
    )
