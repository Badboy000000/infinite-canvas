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
from app.adapters.provider.mappers import (
    canvas_task_payload_to_view,
    comfyui_payload_to_view,
    generic_image_payload_to_view,
    jimeng_payload_to_view,
    runninghub_payload_to_view,
    video_payload_to_view,
)
from app.adapters.provider.classifiers import (
    classify_chat_error,
    classify_generic_image_error,
    classify_jimeng_error,
    classify_runninghub_error,
    classify_video_error,
    is_retryable,
)
from app.adapters.provider import error_messages_zh
from app.adapters.provider import schema_v2

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
