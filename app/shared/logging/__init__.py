"""`request_id` 感知的日志基础设施（PR-BE-02 落地）。

提供 `get_logger()` 入口：返回一个已装配 :class:`RequestIdLogFilter` +
带 `request_id` 字段 formatter 的独立 logger。

**本 PR 不重新配置全局 logging**——`main.py` 的 root logger 与
`uvicorn.access` filter 保持不动；`get_logger()` 是一个可选的"opt-in"
入口，只影响调用方拿到的那个 logger。

使用示例（本 PR 不主动改任何调用方）::

    from app.shared.logging import get_logger
    log = get_logger(__name__)
    log.info("hello")  # 输出: 2026-07-17 ... [<request_id>] INFO app.foo: hello

参考：
- [[40 实施计划/后端模块化治理实施计划与PR清单]] PR-BE-02
- [[60 讨论记录/2026-07-17 第二批开工/2026-07-17 第二批 PR 开工协调纲要]]
  §"保活烟测 BE-15"
"""
from __future__ import annotations

from .request_id_logger import RequestIdLogFilter, get_logger

__all__ = ["RequestIdLogFilter", "get_logger"]
