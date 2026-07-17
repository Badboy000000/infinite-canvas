"""API 错误 handler 占位。

PR-BE-12（M4）在此定义全局 exception handler、`{code, message, details,
request_id}` envelope、`Deprecation` / `Sunset` 响应头等。M0 阶段仅冻
结路径，不实现任何 handler；根 `main.py` 现有错误行为保持不变。
"""
