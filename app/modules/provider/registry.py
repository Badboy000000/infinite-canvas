"""ProviderRegistry facade (PR-BE-08 · Wave 3-N.6 Batch 2 主线 A).

薄 facade。委派给已有的 `app.adapters.provider.registry::resolve_adapter`
（保留 `model_protocols` 表映射能力）。**不重实现** protocol 分派 · 不替
换 `is_xxx_provider()` / `provider_protocol()` legacy 分支（硬约束）。

裁决 3(GM-14 圆桌自治第 7 次实证 · Lead ratify)· 双参 `resolve(provider_id,
model=None) -> ProviderResolution | None`:
- 单参 case → 走默认 protocol
- 双参 case → 通过 `model_protocols` 表映射到 protocol
- 空 model 与 explicit None 行为一致

`ProviderResolution` 三字段冻结:`provider: dict, protocol: str,
adapter: BaseAdapter`(参照 canvas 域 command 对象 pattern)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.adapters.provider.base import BaseAdapter
from app.adapters.provider.errors import (
    AdapterNotRegisteredError,
    CapabilityNotSupportedError,
)
from app.adapters.provider.registry import (
    registered_protocols as _registered_protocols,
    resolve_adapter as _resolve_adapter,
)


@dataclass(frozen=True)
class ProviderResolution:
    """Provider 解析三元组 —— provider 记录 + 生效 protocol + adapter 实例。

    字段冻结（参照 canvas 域 command 对象 pattern）：
    - `provider`: 从 `provider_config_store.load_api_providers()` 拿到的
      整条 provider dict（含 model_protocols 表）
    - `protocol`: 生效 protocol 字符串（可能因 `model` 参数走 model_protocols
      表映射）
    - `adapter`: 已注册 BaseAdapter 实例
    """

    provider: dict[str, Any]
    protocol: str
    adapter: BaseAdapter


class ProviderRegistry:
    """Provider registry facade.

    提供三个高层方法：
    - `resolve(provider_id, model=None) -> ProviderResolution | None`
    - `list_protocols() -> list[str]`
    - `capability(provider_id, capability_name) -> bool`

    provider dict 由外部注入的 `load_providers` callback 承接（默认走
    `app.stores.provider_config_store.load_api_providers`）。不 `import
    main`；不重实现 legacy 分支。
    """

    def __init__(
        self,
        *,
        load_providers: Callable[[], list[dict[str, Any]]],
    ) -> None:
        self._load_providers = load_providers

    def _find_provider(self, provider_id: str) -> dict[str, Any] | None:
        for provider in self._load_providers():
            if str(provider.get("id") or "") == provider_id:
                return provider
        return None

    def resolve(
        self, provider_id: str, model: str | None = None
    ) -> ProviderResolution | None:
        """按 provider_id + 可选 model 解析 adapter。

        `model` 走既有 `model_protocols` 表映射能力（裁决 3 硬约束）·
        单参 case 走默认 protocol · 空串 / None 语义一致 · 未注册的
        provider_id / protocol 返回 None（而非抛错，以便调用方走 legacy
        分支兜底）。
        """

        provider = self._find_provider(provider_id)
        if provider is None:
            return None
        effective_model = model or None
        try:
            adapter = _resolve_adapter(provider, model=effective_model)
        except (AdapterNotRegisteredError, CapabilityNotSupportedError):
            return None
        protocol = getattr(adapter, "protocol", "") or ""
        return ProviderResolution(
            provider=dict(provider), protocol=protocol, adapter=adapter
        )

    def list_protocols(self) -> list[str]:
        """列出已注册的 protocol 集合（稳定排序）。"""

        return list(_registered_protocols())

    def capability(self, provider_id: str, capability_name: str) -> bool:
        """检查 provider 的默认 adapter 是否支持某个 capability。

        委派给 `AdapterCapabilities.supports()`（已有实装 · 硬约束不重实现）。
        """

        resolution = self.resolve(provider_id)
        if resolution is None:
            return False
        try:
            capabilities = resolution.adapter.describe_capabilities()
        except Exception:
            return False
        return bool(capabilities.supports(capability_name))


__all__ = ["ProviderRegistry", "ProviderResolution"]
