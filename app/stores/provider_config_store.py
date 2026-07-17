"""Provider config store facade — 数据模型治理 PR-0。

包裹 `main.py` 中 API 提供商配置读写函数
`load_api_providers` / `save_api_providers`。密钥仍走 `API/.env` 现有路径，
本 facade 不做任何脱敏或转换——完全透传。

后续 Provider 适配体系治理 PR 落地后会补齐 provider protocol 抽象，
本 facade 的签名保持稳定。
"""
from __future__ import annotations

from typing import Any


def load_api_providers(*args: Any, **kwargs: Any) -> Any:
    from main import load_api_providers as _impl
    return _impl(*args, **kwargs)


def save_api_providers(*args: Any, **kwargs: Any) -> Any:
    from main import save_api_providers as _impl
    return _impl(*args, **kwargs)
