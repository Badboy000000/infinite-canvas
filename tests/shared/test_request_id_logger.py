"""PR-BE-02 契约测试：`RequestIdLogFilter` / `get_logger`。

覆盖：
- ContextVar 有值时 `record.request_id` == ctx.request_id。
- ContextVar 无值时 `record.request_id` == "-"。
- formatter 输出包含 `[request_id]` 段。
- `get_logger` 幂等（重复调用不叠加 handler）。
"""
from __future__ import annotations

import logging

from app.api.context import RequestContextVar
from app.identity.request_context import RequestContext
from app.shared.logging import RequestIdLogFilter, get_logger


def _make_ctx(rid: str) -> RequestContext:
    return RequestContext(
        request_id=rid,
        legacy_user_key=None,
        x_user_id=None,
        workspace_id=None,
        project_id=None,
        client_id=None,
        ip=None,
        user_agent=None,
        auth_mode="anonymous_or_legacy",
    )


def _make_record(name: str = "test") -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )


def test_filter_injects_request_id_from_context_var() -> None:
    token = RequestContextVar.set(_make_ctx("rid-abc"))
    try:
        rec = _make_record()
        assert RequestIdLogFilter().filter(rec) is True
        assert rec.request_id == "rid-abc"
    finally:
        RequestContextVar.reset(token)


def test_filter_falls_back_to_dash_when_context_missing() -> None:
    # 显式清空（其他测试可能残留）。
    RequestContextVar.set(None)
    rec = _make_record()
    assert RequestIdLogFilter().filter(rec) is True
    assert rec.request_id == "-"


def test_get_logger_formatter_contains_request_id(capsys) -> None:
    log = get_logger("pr_be_02.smoke.formatter", level=logging.INFO)
    token = RequestContextVar.set(_make_ctx("rid-fmt-1"))
    try:
        log.info("smoke-line")
    finally:
        RequestContextVar.reset(token)
    err = capsys.readouterr().err
    assert "rid-fmt-1" in err
    assert "[rid-fmt-1]" in err
    assert "smoke-line" in err
    assert "pr_be_02.smoke.formatter" in err


def test_get_logger_is_idempotent() -> None:
    a = get_logger("pr_be_02.smoke.idempotent")
    handlers_before = list(a.handlers)
    b = get_logger("pr_be_02.smoke.idempotent")
    assert a is b
    assert list(b.handlers) == handlers_before  # 未叠加 handler
