"""`app.logging` — 日志脱敏骨架包。

**定位**:日志中间件级敏感数据脱敏。骨架层只暴露纯函数
``redact_headers(...)`` / ``redact_query_string(...)`` / ``redact_text(...)``,
以 env flag ``LOG_REDACTION_ENABLED`` 默认关闭 · 与旧行为等价。

**当前骨架成员**(Wave 3-N.8 Batch 5):

- ``redaction``:sensitive header / query key / regex 三层兜底(部署 PR-10)

**分层交付原则**:不改 uvicorn access log formatter;不接入
FastAPI request/response logger。生产切换归后续 PR 承接。

见 [[40 实施计划/部署与安全治理实施计划与PR清单]] M4 · PR-10。
"""
from __future__ import annotations

from app.logging.redaction import (
    LOG_REDACTION_ENABLED_ENV,
    REDACTION_MARKER,
    SENSITIVE_HEADERS,
    SENSITIVE_QUERY_KEYS,
    is_log_redaction_enabled,
    redact_headers,
    redact_query_string,
    redact_text,
    redact_url_full,
)

__all__ = [
    "LOG_REDACTION_ENABLED_ENV",
    "REDACTION_MARKER",
    "SENSITIVE_HEADERS",
    "SENSITIVE_QUERY_KEYS",
    "is_log_redaction_enabled",
    "redact_headers",
    "redact_query_string",
    "redact_text",
    "redact_url_full",
]
