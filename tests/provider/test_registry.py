from __future__ import annotations

from typing import Any, Mapping

import pytest

from app.adapters.provider.base import (
    AdapterCapabilities,
    BaseAdapter,
    ConnectionResult,
    Credential,
    ProviderTaskCapabilities,
    TaskError,
    TaskErrorCategory,
)
from app.adapters.provider.errors import (
    AdapterNotRegisteredError,
    AdapterRegistrationError,
    CapabilityNotSupportedError,
)
from app.adapters.provider.registry import adapter, registered_protocols, resolve_adapter


@adapter(protocol="pr01-test", capabilities={"image_generate"})
class ContractTestAdapter(BaseAdapter):
    def describe_capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(image_generate=True)

    def describe_task_capabilities(self) -> ProviderTaskCapabilities:
        return ProviderTaskCapabilities()

    async def test_connection(self, credential: Credential) -> ConnectionResult:
        return ConnectionResult(ok=True)

    def classify_error(self, exc: BaseException, context: Mapping[str, Any]) -> TaskError:
        return TaskError(
            code="internal",
            category=TaskErrorCategory.INTERNAL,
            request_id=str(context.get("request_id", "unknown")),
        )


def test_registry_resolves_registered_protocol() -> None:
    resolved = resolve_adapter(
        {"id": "provider-1", "protocol": "PR01-TEST"},
        model="image-model",
        capability="image_generate",
    )

    assert isinstance(resolved, ContractTestAdapter)
    assert resolved.provider_id == "provider-1"
    assert resolved.protocol == "pr01-test"
    assert "pr01-test" in registered_protocols()


def test_registry_honors_model_protocol_override() -> None:
    resolved = resolve_adapter(
        {
            "id": "provider-2",
            "protocol": "not-registered",
            "model_protocols": {"special-model": "pr01-test"},
        },
        model="special-model",
    )

    assert isinstance(resolved, ContractTestAdapter)


def test_unregistered_protocol_raises_structured_provider_error() -> None:
    with pytest.raises(AdapterNotRegisteredError) as caught:
        resolve_adapter({"id": "missing-provider", "protocol": "pr01-missing"})

    assert caught.value.code == "provider_adapter_not_registered"
    assert caught.value.provider_id == "missing-provider"
    assert caught.value.details == {"protocol": "pr01-missing", "model": None}
    assert caught.value.as_dict()["retryable"] is False


def test_unsupported_capability_raises_structured_provider_error() -> None:
    with pytest.raises(CapabilityNotSupportedError) as caught:
        resolve_adapter(
            {"id": "provider-3", "protocol": "pr01-test"},
            capability="video_generate",
        )

    assert caught.value.code == "provider_capability_not_supported"
    assert caught.value.details["capability"] == "video_generate"


def test_duplicate_protocol_registration_is_rejected() -> None:
    with pytest.raises(AdapterRegistrationError) as caught:

        @adapter(protocol="pr01-test")
        class DuplicateAdapter(ContractTestAdapter):
            pass

    assert caught.value.code == "duplicate_provider_adapter"
