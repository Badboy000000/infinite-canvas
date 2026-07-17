"""Provider adapter errors independent from HTTP transport concerns."""

from __future__ import annotations

from typing import Any, Mapping, Optional


class ProviderError(Exception):
    """Structured error raised by Provider adapters and their registry."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        provider_id: Optional[str] = None,
        provider_code: Optional[str] = None,
        provider_message: Optional[str] = None,
        retryable: bool = False,
        request_id: Optional[str] = None,
        details: Optional[Mapping[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.code = code
        self.provider_id = provider_id
        self.provider_code = provider_code
        self.provider_message = provider_message
        self.retryable = retryable
        self.request_id = request_id
        self.details = dict(details or {})
        self.cause = cause
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        """Return the transport-neutral public error shape."""

        return {
            "code": self.code,
            "message": str(self),
            "provider_id": self.provider_id,
            "provider_code": self.provider_code,
            "provider_message": self.provider_message,
            "retryable": self.retryable,
            "request_id": self.request_id,
            "details": dict(self.details),
        }


class AdapterRegistrationError(ProviderError):
    """Raised when an adapter registration is invalid or duplicated."""


class AdapterNotRegisteredError(ProviderError):
    """Raised when no adapter is registered for the effective protocol."""


class CapabilityNotSupportedError(ProviderError):
    """Raised when an adapter does not declare a requested capability."""


class UnsupportedAdapterOperationError(ProviderError):
    """Raised for optional operations an adapter does not implement."""


__all__ = [
    "ProviderError",
    "AdapterRegistrationError",
    "AdapterNotRegisteredError",
    "CapabilityNotSupportedError",
    "UnsupportedAdapterOperationError",
]
