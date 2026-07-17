"""Provider adapter contract and inert registry."""

from app.adapters.provider.base import (
    AdapterCapabilities,
    AssetRef,
    AsyncProbeResult,
    BaseAdapter,
    CancelResult,
    ConnectionResult,
    Credential,
    ModelInfo,
    ProviderTaskCapabilities,
    ProviderTaskEvent,
    ProviderTaskHandle,
    ProviderTaskRequest,
    ProviderTaskView,
    ProviderTaskViewStatus,
    TaskError,
    TaskErrorCategory,
)
from app.adapters.provider.errors import (
    AdapterNotRegisteredError,
    AdapterRegistrationError,
    CapabilityNotSupportedError,
    ProviderError,
    UnsupportedAdapterOperationError,
)
from app.adapters.provider.registry import adapter, registered_protocols, resolve_adapter
from app.adapters.provider.status import (
    provider_view_status_to_task_status,
    task_status_to_provider_view_status,
)

__all__ = [
    "BaseAdapter",
    "AdapterCapabilities",
    "ProviderTaskCapabilities",
    "Credential",
    "ProviderTaskRequest",
    "ProviderTaskHandle",
    "ProviderTaskView",
    "ProviderTaskViewStatus",
    "AssetRef",
    "ProviderError",
    "AdapterRegistrationError",
    "AdapterNotRegisteredError",
    "CapabilityNotSupportedError",
    "UnsupportedAdapterOperationError",
    "TaskError",
    "TaskErrorCategory",
    "ConnectionResult",
    "AsyncProbeResult",
    "CancelResult",
    "ModelInfo",
    "ProviderTaskEvent",
    "adapter",
    "registered_protocols",
    "resolve_adapter",
    "provider_view_status_to_task_status",
    "task_status_to_provider_view_status",
]
