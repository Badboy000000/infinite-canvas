"""Inert ProviderAdapter registration and resolution scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, TypeVar

from app.adapters.provider.base import BaseAdapter
from app.adapters.provider.errors import (
    AdapterNotRegisteredError,
    AdapterRegistrationError,
    CapabilityNotSupportedError,
)


AdapterType = TypeVar("AdapterType", bound=type[BaseAdapter])


@dataclass(frozen=True)
class AdapterRegistration:
    protocol: str
    adapter_type: type[BaseAdapter]
    capabilities: frozenset[str]
    inherits: Optional[str] = None
    provider_id_hint: Optional[str] = None


_REGISTRY: dict[str, AdapterRegistration] = {}


def _normalize_protocol(protocol: str) -> str:
    normalized = protocol.strip().lower()
    if not normalized:
        raise AdapterRegistrationError(
            "invalid_provider_protocol",
            "Provider adapter protocol must not be empty",
        )
    return normalized


def adapter(
    *,
    protocol: str,
    capabilities: Iterable[str] = (),
    inherits: Optional[str] = None,
    provider_id_hint: Optional[str] = None,
) -> Callable[[AdapterType], AdapterType]:
    """Register an adapter class without wiring it into application startup."""

    normalized = _normalize_protocol(protocol)

    def decorate(adapter_type: AdapterType) -> AdapterType:
        if not issubclass(adapter_type, BaseAdapter):
            raise AdapterRegistrationError(
                "invalid_provider_adapter",
                f"Registered type for protocol {normalized!r} must extend BaseAdapter",
                details={"protocol": normalized},
            )
        if normalized in _REGISTRY:
            raise AdapterRegistrationError(
                "duplicate_provider_adapter",
                f"Provider adapter protocol {normalized!r} is already registered",
                details={"protocol": normalized},
            )
        adapter_type.protocol = normalized
        _REGISTRY[normalized] = AdapterRegistration(
            protocol=normalized,
            adapter_type=adapter_type,
            capabilities=frozenset(capabilities),
            inherits=_normalize_protocol(inherits) if inherits else None,
            provider_id_hint=provider_id_hint,
        )
        return adapter_type

    return decorate


def registered_protocols() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def _provider_value(provider: object, key: str, default: Any = None) -> Any:
    if isinstance(provider, Mapping):
        return provider.get(key, default)
    return getattr(provider, key, default)


def _effective_protocol(provider: object, model: Optional[str]) -> str:
    model_protocols = _provider_value(provider, "model_protocols", {})
    if model and isinstance(model_protocols, Mapping) and model in model_protocols:
        return _normalize_protocol(str(model_protocols[model]))
    return _normalize_protocol(str(_provider_value(provider, "protocol", "openai")))


def resolve_adapter(
    provider: object,
    model: Optional[str] = None,
    capability: Optional[str] = None,
) -> BaseAdapter:
    """Resolve an adapter by effective protocol; no application wiring occurs."""

    provider_id = str(_provider_value(provider, "id", ""))
    protocol = _effective_protocol(provider, model)
    registration = _REGISTRY.get(protocol)
    if registration is None:
        raise AdapterNotRegisteredError(
            "provider_adapter_not_registered",
            f"No Provider adapter is registered for protocol {protocol!r}",
            provider_id=provider_id or None,
            details={"protocol": protocol, "model": model},
        )

    resolved = registration.adapter_type(provider_id=provider_id, protocol=protocol)
    if capability and not resolved.describe_capabilities().supports(capability):
        raise CapabilityNotSupportedError(
            "provider_capability_not_supported",
            f"Provider adapter {protocol!r} does not support capability {capability!r}",
            provider_id=provider_id or None,
            details={"protocol": protocol, "capability": capability, "model": model},
        )
    return resolved


__all__ = [
    "AdapterRegistration",
    "adapter",
    "registered_protocols",
    "resolve_adapter",
]
