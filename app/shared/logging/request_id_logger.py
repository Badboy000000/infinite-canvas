"""`request_id` 感知的 logging filter / formatter 工具。

`RequestIdLogFilter` 从 :data:`app.api.context.RequestContextVar` 读取
当前请求上下文，把 `request_id` 注入到 `LogRecord.request_id` 字段；
未设时填 `"-"`，保证 formatter 永远拿到非空字符串。

`get_logger(name)` 返回一个已装配 filter + formatter 的独立 logger，
`propagate=False` 避免与 root logger 双写。

本模块**不改全局 logging 配置**——仅在被调用时创建 opt-in logger。
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

_FORMAT = "%(asctime)s [%(request_id)s] %(levelname)s %(name)s: %(message)s"


class RequestIdLogFilter(logging.Filter):
    """向 `LogRecord` 注入 `request_id` 字段。

    读取 `app.api.context.RequestContextVar`——延迟 import 避免包加载期
    的循环依赖（`app.shared.logging` 是基础工具、`app.api.context` 依赖
    FastAPI，两者不同层）。
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401 - stdlib API
        try:
            # 延迟 import：避免模块加载期循环依赖。
            from app.api.context import RequestContextVar
            ctx = RequestContextVar.get()
        except Exception:  # noqa: BLE001 - 极端 startup 期防御
            ctx = None
        record.request_id = ctx.request_id if ctx is not None else "-"
        return True


def get_logger(name: str, level: Optional[int] = None) -> logging.Logger:
    """返回一个 request_id 感知的独立 logger。

    - `name`：logger 名（通常 `__name__`）。
    - `level`：可选日志级别；未指定时沿用父 logger / root 的等级。

    幂等：同名再次调用返回同一实例，且不重复挂 handler / filter。
    """
    logger = logging.getLogger(name)
    if getattr(logger, "_request_id_configured", False):
        if level is not None:
            logger.setLevel(level)
        return logger

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(RequestIdLogFilter())
    logger.addHandler(handler)
    # 关闭向 root 冒泡，避免 uvicorn root handler 再打印一遍无 request_id 版本。
    logger.propagate = False
    if level is not None:
        logger.setLevel(level)
    logger._request_id_configured = True  # type: ignore[attr-defined]
    return logger


__all__ = ["RequestIdLogFilter", "get_logger"]
