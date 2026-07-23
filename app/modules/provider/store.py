"""Provider 持久化 facade（PR-BE-08）。

`ProviderStore` 是路由层之外看到的**唯一**provider 配置持久化入口。它委派
给 `app.stores.provider_config_store`（该 store facade 已在早期 PR 中锁定，
含 `_safe_provider_records` 深度脱敏 + `read_shadow` 双写读取 hook + 20 字
段 `PROVIDER_SNAPSHOT_FIELDS` 白名单），**不重新实现 IO**，也不直接
`import main`。

严格约束（任务书零触碰第 11 项）：
- **不改** `app.stores.provider_config_store` 内部实现（那是 P0 密钥零入库
  防线所在的 store facade）。本类只做同签名的薄委派。
- `read_shadow` 双写读取路径由 store facade 自动生效 —— 本类不做绕行。
"""

from __future__ import annotations

from typing import Any

from app.stores import provider_config_store as _provider_config_store_facade


class ProviderStore:
    """薄委派 store —— 让 service 层不用直接 `import` facade 模块。"""

    def load_api_providers(self) -> list[dict[str, Any]]:
        return _provider_config_store_facade.load_api_providers()

    def save_api_providers(self, providers: list[dict[str, Any]]) -> Any:
        return _provider_config_store_facade.save_api_providers(providers)


__all__ = ["ProviderStore"]
