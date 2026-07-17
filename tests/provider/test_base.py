from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.adapters.provider.base import (
    AdapterCapabilities,
    AssetRef,
    ProviderTaskCapabilities,
    ProviderTaskView,
    TaskError,
    TaskErrorCategory,
)
from app.adapters.provider.errors import ProviderError


def test_pr01_contract_types_are_importable() -> None:
    from app.adapters.provider import (
        AsyncProbeResult,
        BaseAdapter,
        CancelResult,
        ConnectionResult,
        Credential,
        ModelInfo,
        ProviderTaskEvent,
        ProviderTaskHandle,
        ProviderTaskRequest,
    )

    assert all(
        value is not None
        for value in (
            BaseAdapter,
            Credential,
            ProviderTaskRequest,
            ProviderTaskHandle,
            ConnectionResult,
            AsyncProbeResult,
            CancelResult,
            ModelInfo,
            ProviderTaskEvent,
        )
    )


def test_adapter_capabilities_model_dump_has_stable_defaults() -> None:
    capabilities = AdapterCapabilities(
        image_generate=True,
        supported_image_request_modes=("openai", "openai-responses"),
        credential_slots=("api_key",),
    )

    dumped = capabilities.model_dump()

    assert dumped["image_generate"] is True
    assert dumped["video_generate"] is False
    assert dumped["supported_image_request_modes"] == ("openai", "openai-responses")
    assert capabilities.supports("image_generate") is True
    assert capabilities.supports("not_a_capability") is False


def test_task_capabilities_serializes_reserved_async_field() -> None:
    capabilities = ProviderTaskCapabilities(async_=True, cancellable=True)

    assert capabilities.model_dump(by_alias=True)["async"] is True


def test_provider_task_view_validates_progress_range() -> None:
    with pytest.raises(ValidationError):
        ProviderTaskView(provider_id="demo", status="running", progress=1.1)


def test_provider_task_view_and_error_dump_nested_contract() -> None:
    view = ProviderTaskView(
        provider_id="demo",
        upstream_task_id="up-1",
        status="failed",
        outputs=(AssetRef(kind="image", source_url_or_bytes="https://example.test/a.png"),),
        error=TaskError(
            code="upstream_timeout",
            category=TaskErrorCategory.TIMEOUT,
            retryable=True,
            request_id="req-1",
        ),
        remote_status="TIMEOUT",
    )

    dumped = view.model_dump(mode="json")

    assert dumped["status"] == "failed"
    assert dumped["outputs"][0]["kind"] == "image"
    assert dumped["error"]["category"] == "TIMEOUT"


def test_provider_contract_does_not_depend_on_fastapi_or_http_exception() -> None:
    import app.adapters.provider.base as base_module
    import app.adapters.provider.errors as errors_module
    import app.adapters.provider.registry as registry_module

    sources = "\n".join(inspect.getsource(module) for module in (base_module, errors_module, registry_module))
    assert "fastapi" not in sources.lower()
    assert "HTTPException" not in sources
    assert issubclass(ProviderError, Exception)


def test_base_and_registry_import_without_loading_fastapi_or_task_package() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import app.adapters.provider.base; "
                "import app.adapters.provider.registry; "
                "assert 'fastapi' not in sys.modules; "
                "assert 'app.task' not in sys.modules"
            ),
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
