"""`app.logging.redaction` — 日志脱敏纯函数库(部署 PR-10 骨架层)。

**定位**:纯函数 · env flag 默认关闭 · 与旧行为等价。

**骨架契约**:
- ``SENSITIVE_HEADERS``:敏感 header 名字 frozenset(大小写不敏感匹配)
- ``SENSITIVE_QUERY_KEYS``:敏感 query key frozenset
- ``REDACTION_MARKER``:统一替换标记 ``"***"``
- ``redact_headers(headers)``:纯函数 · dict → dict
- ``redact_query_string(qs)``:纯函数 · str → str
- ``redact_text(text)``:正则兜底 · str → str
- ``is_log_redaction_enabled()``:env flag ``LOG_REDACTION_ENABLED`` 判据

**默认策略**(治理方案 M4 明示):
- Headers: Authorization / X-API-Key / Cookie / Set-Cookie / X-CSRF-Token
- Query keys: X-Amz-Signature / X-Amz-Credential / X-Amz-Security-Token /
  signature / token / access_token / api_key / key
- Regex 兜底: ``(?i)(api[_-]?key|authorization|bearer\\s)[\\s:=]+[A-Za-z0-9\\-._~+/=]{6,}``

**P0 密钥零泄漏防线扩展**:与权限 PR-7 AuditService `_ALLOWED_AUDIT_FIELDS`
互补 · AuditService 是"白名单只让通过 17 字段" · Redaction 是"黑名单兜底
剔除敏感头 / query" · 双层防线。

**不做**:
- 不替换 uvicorn access log formatter(生产切换归后续 PR)
- 不接入 FastAPI request/response logger
- 不改错误响应体 traceback 行为
- 不引入结构化日志框架(需架构评审)

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] PR-10。
"""
from __future__ import annotations

import os
import re
from typing import Dict, Iterable, Mapping, Optional


# ---------------------------------------------------------------------------
# env flag
# ---------------------------------------------------------------------------

_TRUTHY = frozenset({"1", "true", "yes", "on", "TRUE"})

LOG_REDACTION_ENABLED_ENV = "LOG_REDACTION_ENABLED"


def is_log_redaction_enabled() -> bool:
    """``LOG_REDACTION_ENABLED`` 是否已开启(默认 false)。"""
    return os.environ.get(LOG_REDACTION_ENABLED_ENV, "").strip() in _TRUTHY


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

REDACTION_MARKER = "***"

# 大小写不敏感 · 存储为小写
SENSITIVE_HEADERS = frozenset({
    "authorization",
    "x-api-key",
    "cookie",
    "set-cookie",
    "x-csrf-token",
    "x-auth-token",
    "proxy-authorization",
})

# 敏感 query key(小写比对)
SENSITIVE_QUERY_KEYS = frozenset({
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-date",
    "signature",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "key",
    "secret",
    "password",
    "client_secret",
})


# ---------------------------------------------------------------------------
# 正则兜底
# ---------------------------------------------------------------------------

# 覆盖 3 类高风险模式:
# 1. api_key / api-key / apikey [:=] <token>
# 2. authorization <token>
# 3. bearer <token>
# 4. sk-<32+ chars>(OpenAI/Anthropic API key 模板)
_REDACTION_PATTERNS = (
    re.compile(
        r"(?i)(api[_-]?key|authorization|bearer\s)[\s:=]+[A-Za-z0-9\-._~+/=]{6,}"
    ),
    re.compile(r"(?i)(sk-[A-Za-z0-9_-]{20,})"),
    re.compile(r"(?i)(x-api-key)[\s:=]+[A-Za-z0-9\-._~+/=]{6,}"),
)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def redact_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    """脱敏 headers · 大小写不敏感匹配。

    敏感 header 值替换为 ``REDACTION_MARKER``;其他 header 原样保留。

    Args:
        headers: header dict(header 名 · header 值)。

    Returns:
        新 dict · 敏感值已替换。
    """
    result: Dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in SENSITIVE_HEADERS:
            result[name] = REDACTION_MARKER
        else:
            result[name] = value
    return result


def redact_query_string(qs: str) -> str:
    """脱敏 query string · key=value 分段 · 敏感 key 值替换。

    支持 ``&`` 分隔 · 无 value 的 key 原样保留 · URL-encode 保留。

    Args:
        qs: 原 query string(不含前导 ``?``)。

    Returns:
        脱敏后 query string。
    """
    if not qs:
        return qs

    parts = qs.split("&")
    out = []
    for part in parts:
        if "=" not in part:
            out.append(part)
            continue
        key, _, value = part.partition("=")
        if key.lower() in SENSITIVE_QUERY_KEYS:
            out.append(f"{key}={REDACTION_MARKER}")
        else:
            out.append(part)
    return "&".join(out)


def redact_text(text: str) -> str:
    """正则兜底脱敏 · 用于 access log / body preview 等自由文本。

    命中 3 类模式(见 _REDACTION_PATTERNS):
        1. api_key / api-key / apikey / authorization / bearer + token
        2. sk-<token>(OpenAI/Anthropic 模板)
        3. x-api-key <token>

    模式 1/3 替换为 ``<key_name>=***``(保留 key 名);
    模式 2 整段替换为 ``***``(不保留 token 值)。

    Args:
        text: 原始文本。

    Returns:
        脱敏后文本。
    """
    if not text:
        return text

    result = text
    for idx, pattern in enumerate(_REDACTION_PATTERNS):
        if idx == 1:
            # sk- 模式:整段替换为 ***,不保留 token 值
            result = pattern.sub(REDACTION_MARKER, result)
        else:
            result = pattern.sub(
                lambda m: f"{m.group(1)}={REDACTION_MARKER}",
                result,
            )
    return result


def redact_url_full(url: str) -> str:
    """脱敏完整 URL(scheme://host/path?query)· 只脱敏 query 段。

    Args:
        url: 完整 URL。

    Returns:
        query 段已脱敏的 URL。
    """
    if not url or "?" not in url:
        return url
    base, _, qs = url.partition("?")
    return f"{base}?{redact_query_string(qs)}"


__all__ = [
    "LOG_REDACTION_ENABLED_ENV",
    "REDACTION_MARKER",
    "SENSITIVE_HEADERS",
    "SENSITIVE_QUERY_KEYS",
    "redact_headers",
    "redact_query_string",
    "redact_text",
    "redact_url_full",
    "is_log_redaction_enabled",
]
