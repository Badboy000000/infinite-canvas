"""Transport-neutral ProviderAdapter contract for Provider PR-01."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Literal, Mapping, Never, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.adapters.provider.errors import UnsupportedAdapterOperationError


ProviderTaskViewStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "waiting_upstream",
]


class ContractModel(BaseModel):
    """Frozen value object used at the Provider adapter boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TaskErrorCategory(str, Enum):
    AUTH = "AUTH"
    QUOTA = "QUOTA"
    RATE_LIMIT = "RATE_LIMIT"
    VALIDATION = "VALIDATION"
    CONTENT_POLICY = "CONTENT_POLICY"
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    UPSTREAM_5XX = "UPSTREAM_5XX"
    TIMEOUT = "TIMEOUT"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    COST_EXCEEDED = "COST_EXCEEDED"
    CANCELLED = "CANCELLED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    RECOVERABLE_UNKNOWN = "RECOVERABLE_UNKNOWN"
    INTERNAL = "INTERNAL"


class AssetRef(ContractModel):
    kind: str
    source_url_or_bytes: str | bytes
    mime: Optional[str] = None
    size_hint: Optional[int] = Field(default=None, ge=0)


class AdapterCapabilities(ContractModel):
    image_generate: bool = False
    image_edit: bool = False
    video_generate: bool = False
    chat: bool = False
    chat_stream: bool = False
    workflow_run: bool = False
    asset_upload: bool = False
    asset_authentication: bool = False
    models_dynamic_fetch: bool = False
    requires_local_binary: bool = False
    stateful_session: bool = False
    streaming_stdout: bool = False
    supported_image_request_modes: tuple[str, ...] = ()
    credential_slots: tuple[str, ...] = ()

    def supports(self, capability: str) -> bool:
        value = getattr(self, capability, None)
        return value is True


class ProviderTaskCapabilities(ContractModel):
    async_: bool = Field(default=False, alias="async", serialization_alias="async")
    streaming: bool = False
    cancellable: bool = False
    cancel_scope: Literal["none", "local_wait", "upstream_task"] = "none"
    recoverable_by_handle: bool = False
    partial_outputs: bool = False
    progress: bool = False
    cost_class: Literal["free", "low", "medium", "high", "per_second_video"] = "medium"
    recommended_poll_ms: int = Field(default=1000, ge=0)
    max_poll_ms: int = Field(default=30000, ge=0)
    supports_idempotency_key: bool = False
    required_worker_pool: Literal["image", "video", "comfy", "cli", "download"] = "image"
    execution_hint: Literal["inline_async", "subprocess", "http_polling", "ws_events"] = (
        "inline_async"
    )


class Credential(ContractModel):
    provider_id: str
    level: Literal["system", "workspace", "user"]
    slots: Mapping[str, str] = Field(repr=False)
    metadata: Mapping[str, Any] = Field(default_factory=dict)
    fingerprint: str
    ref_id: str


class ProviderTaskRequest(ContractModel):
    operation: Literal[
        "generate_image",
        "edit_image",
        "generate_video",
        "run_workflow",
        "chat",
        "upload_asset",
        "verify_asset",
    ]
    model: str
    params: Mapping[str, Any] = Field(default_factory=dict)
    inputs: tuple[AssetRef, ...] = ()
    idempotency_hint: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    request_id: str


class ProviderTaskHandle(ContractModel):
    provider_id: str
    upstream_task_id: str
    upstream_task_kind: str
    query_params: Mapping[str, Any] = Field(default_factory=dict)


class TaskError(ContractModel):
    code: str
    category: TaskErrorCategory
    provider_code: Optional[str] = None
    provider_message: Optional[str] = None
    retryable: bool = False
    raw_excerpt: Mapping[str, Any] = Field(default_factory=dict)
    request_id: str


class ProviderTaskView(ContractModel):
    provider_id: str
    upstream_task_id: Optional[str] = None
    status: ProviderTaskViewStatus
    progress: Optional[float] = Field(default=None, ge=0, le=1)
    outputs: tuple[AssetRef, ...] = ()
    error: Optional[TaskError] = None
    next_poll_after_ms: Optional[int] = Field(default=None, ge=0)
    recoverable: bool = False
    remote_status: str = ""
    raw_excerpt: Mapping[str, Any] = Field(default_factory=dict)


class ConnectionResult(ContractModel):
    ok: bool
    latency_ms: Optional[int] = Field(default=None, ge=0)
    capability_probe: Mapping[str, Any] = Field(default_factory=dict)
    error: Optional[TaskError] = None


class AsyncProbeResult(ContractModel):
    supported: bool
    task_capabilities: Optional[ProviderTaskCapabilities] = None
    remote_status: Optional[str] = None
    raw_excerpt: Mapping[str, Any] = Field(default_factory=dict)


class CancelResult(ContractModel):
    accepted: bool
    scope: Literal["none", "local_wait", "upstream_task"]
    status: ProviderTaskViewStatus
    message: Optional[str] = None


class ModelInfo(ContractModel):
    id: str
    kind: str
    display_name: Optional[str] = None
    metadata: Mapping[str, Any] = Field(default_factory=dict)


class ProviderTaskEvent(ContractModel):
    event_type: str
    status: Optional[ProviderTaskViewStatus] = None
    occurred_at: datetime
    payload: Mapping[str, Any] = Field(default_factory=dict)


class BaseAdapter(ABC):
    """Protocol translation port; persistence and retry belong to TaskService."""

    provider_id: str = ""
    protocol: str = ""

    def __init__(
        self,
        *,
        provider_id: Optional[str] = None,
        protocol: Optional[str] = None,
    ) -> None:
        if provider_id is not None:
            self.provider_id = provider_id
        if protocol is not None:
            self.protocol = protocol

    @abstractmethod
    def describe_capabilities(self) -> AdapterCapabilities:
        raise NotImplementedError

    @abstractmethod
    def describe_task_capabilities(self) -> ProviderTaskCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def test_connection(self, credential: Credential) -> ConnectionResult:
        raise NotImplementedError

    @abstractmethod
    def classify_error(self, exc: BaseException, context: Mapping[str, Any]) -> TaskError:
        raise NotImplementedError

    async def list_models(self, credential: Credential, kind: str) -> list[ModelInfo]:
        self._unsupported("list_models")

    async def probe_async(self, credential: Credential) -> AsyncProbeResult:
        self._unsupported("probe_async")

    async def submit_task(
        self, request: ProviderTaskRequest, credential: Credential
    ) -> ProviderTaskView:
        self._unsupported("submit_task")

    async def query_task(
        self, handle: ProviderTaskHandle, credential: Credential
    ) -> ProviderTaskView:
        self._unsupported("query_task")

    async def cancel_task(
        self, handle: ProviderTaskHandle, credential: Credential
    ) -> CancelResult:
        self._unsupported("cancel_task")

    async def fetch_outputs(
        self, handle: ProviderTaskHandle, credential: Credential
    ) -> list[AssetRef]:
        self._unsupported("fetch_outputs")

    async def stream_events(
        self, handle: ProviderTaskHandle, credential: Credential
    ) -> AsyncIterator[ProviderTaskEvent]:
        self._unsupported("stream_events")
        if False:  # pragma: no cover - keeps this method an async generator
            yield ProviderTaskEvent(event_type="unreachable", occurred_at=datetime.min)

    def _unsupported(self, operation: str) -> Never:
        raise UnsupportedAdapterOperationError(
            "provider_operation_not_supported",
            f"Adapter protocol {self.protocol!r} does not implement {operation}",
            provider_id=self.provider_id or None,
            details={"protocol": self.protocol, "operation": operation},
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
    "TaskError",
    "TaskErrorCategory",
    "ConnectionResult",
    "AsyncProbeResult",
    "CancelResult",
    "ModelInfo",
    "ProviderTaskEvent",
]
