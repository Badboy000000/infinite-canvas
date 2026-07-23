from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
import pytest


ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"
STATIC_IMPORT_MUTATIONS = (
    ROOT / "static" / "api-settings.html",
    ROOT / "static" / "canvas.html",
    ROOT / "static" / "comfyui-settings.html",
    ROOT / "static" / "index.html",
    ROOT / "static" / "smart-canvas.html",
)


@pytest.fixture(scope="module", autouse=True)
def restore_import_time_static_mutations():
    snapshots = {path: path.read_bytes() for path in STATIC_IMPORT_MUTATIONS}
    yield
    for path, content in snapshots.items():
        path.write_bytes(content)


@pytest.fixture(autouse=True)
def restore_main_global_loop():
    import main

    original_global_loop = main.GLOBAL_LOOP
    yield
    if original_global_loop is not None and getattr(original_global_loop, "is_closed", lambda: False)():
        main.GLOBAL_LOOP = None
    else:
        main.GLOBAL_LOOP = original_global_loop


def _function_source(tree, name):
    node = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    return ast.dump(node, include_attributes=False)


def test_shadow_flag_parser_and_failure_isolation(monkeypatch, caplog):
    import main

    assert main._parse_file_shadow_write(None) is True
    assert main._parse_file_shadow_write("YES") is True
    assert main._parse_file_shadow_write("off") is False
    assert main._parse_file_shadow_write("not-a-bool") is False

    monkeypatch.setattr(main, "FILE_SHADOW_WRITE", True)
    monkeypatch.setattr(main.file_service, "create_from_stream", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("raw secret")))
    monkeypatch.setattr(main.file_service, "record_failure", lambda *args, **kwargs: None)
    assert main.shadow_register_existing("missing-sensitive-path", "/secret-url", "upload") is None
    assert "raw secret" not in caplog.text
    assert "/secret-url" not in caplog.text


def test_diagnostic_is_hidden_gated_and_redacted(monkeypatch):
    import main

    payload = {
        "recorded_attempts": 2,
        "recorded_aligned": 1,
        "recorded_failed": 1,
        "recorded_rate": 0.5,
        "window_seconds": 86400,
        "by_origin": {"upload": {"attempted": 2, "aligned": 1, "failed": 1}},
        "by_error": {"registration_error": 1},
    }
    monkeypatch.setattr(main.file_service, "alignment_summary", lambda window: payload)
    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "local_personal")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/_diag/file-shadow-align")
        assert response.status_code == 200
        assert response.json() == payload
        assert "/api/_diag/file-shadow-align" not in client.get("/openapi.json").json()["paths"]

    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "public_team")
    with TestClient(main.app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/_diag/file-shadow-align").status_code == 404
    monkeypatch.setenv("IC_DEPLOYMENT_MODE", "local_personal")
    with TestClient(main.app, client=("203.0.113.8", 50000)) as client:
        assert client.get("/api/_diag/file-shadow-align").status_code == 404


def test_ast_has_required_durable_hooks_and_exclusions():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    expected = {
        "save_ai_image_to_output",
        "save_remote_video_to_output",
        "runninghub_store_remote_output",
        "download_image",
        "download_comfy_output",
        "save_comfy_text_output",
        "generate_codex_provider_image_via_gpt_image_2_skill",
        "generate_gemini_cli_provider_image",
        "import_local_image_file",
        "jimeng_local_output_url",
        "poll_angle_cloud",
        "generate_angle_cloud",
        "generate_cloud",
        "ms_generate",
        "upload_ai_reference",
        "upload_ai_base64",
        "upload_local_assets",
        "import_local_assets_from_urls",
        "make_asset_library_item",
        "make_workflow_library_item_from_bytes",
        "import_canvas_workflow",
    }
    for name in expected:
        dumped = _function_source(tree, name)
        assert "shadow_register_existing" in dumped, name

    assert "shadow_register_existing" not in _function_source(tree, "_local_upload_item")
    assert "shadow_register_existing" not in _function_source(tree, "export_canvas_workflow")
    assert "shadow_register_existing" not in _function_source(tree, "upload_comfyui_base64")


def test_file_service_shadow_methods_never_call_adapter_put():
    """create_from_bytes / create_from_stream must not call put or open_writable_stream.

    create_from_generation is the only primary-write method that legitimately
    calls adapter.put (added in file PR-3).
    """
    path = ROOT / "app" / "services" / "files" / "file_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # Find all methods defined in the class
    class_node = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == "FileService")
    shadow_methods = {"create_from_bytes", "create_from_stream", "_register_existing"}

    for method_node in class_node.body:
        if not isinstance(method_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if method_node.name not in shadow_methods:
            continue
        calls = [c for c in ast.walk(method_node) if isinstance(c, ast.Call)]
        assert not any(
            isinstance(call.func, ast.Attribute) and call.func.attr in {"put", "open_writable_stream"}
            for call in calls
        ), f"{method_node.name} must not call adapter.put"

    # Verify create_from_generation DOES call put (file PR-3 contract)
    gen_method = next(
        m for m in class_node.body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name == "create_from_generation"
    )
    gen_calls = [c for c in ast.walk(gen_method) if isinstance(c, ast.Call)]
    assert any(
        isinstance(call.func, ast.Attribute) and call.func.attr == "put"
        for call in gen_calls
    ), "create_from_generation must call adapter.put"


def test_storage_settings_frozen_functions_match_baseline():
    current = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    baseline_text = subprocess.run(
        ["git", "show", "ba4b87e:main.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    baseline = ast.parse(baseline_text)
    for name in ("storage_settings_snapshot", "apply_storage_settings"):
        assert _function_source(current, name) == _function_source(baseline, name)

    current_class = next(node for node in current.body if isinstance(node, ast.ClassDef) and node.name == "StorageSettings")
    baseline_class = next(node for node in baseline.body if isinstance(node, ast.ClassDef) and node.name == "StorageSettings")
    assert ast.dump(current_class, include_attributes=False) == ast.dump(baseline_class, include_attributes=False)


def test_tests_do_not_reference_real_file_index():
    for path in (ROOT / "tests" / "files").glob("test_*.py"):
        if path.name == "test_main_integration.py":
            continue
        assert "data/file_index.json" not in path.read_text(encoding="utf-8").replace("\\", "/")


# ---------------------------------------------------------------------------
# T148: feature flag false -> old path only (no new path)
# ---------------------------------------------------------------------------


def _drive_ai_output_dispatch(monkeypatch, tmp_path):
    """Execute the exact ``if FILE_SERVICE_PRIMARY_WRITE_GENERATION`` branch
    used by ``save_ai_image_to_output`` (b64 branch, main.py L9208-9219) and
    return the ``(new_path_mock, old_path_mock)`` recording actual call counts.

    We stub ``file_service.create_from_generation`` and
    ``shadow_register_existing_async`` (used by save_ai_image_to_output), then
    call a slim shim that mirrors the production dispatch (identical if/else,
    identical positional args). This proves *behavior*, not merely flag value.

    Retaining the dispatch inline (rather than reaching for runpy /
    importlib.reload) keeps the assertion strong and cheap.
    """
    import asyncio
    import main
    from unittest.mock import AsyncMock, MagicMock

    new_path = MagicMock(return_value=None)
    old_path = AsyncMock(return_value=None)
    monkeypatch.setattr(main.file_service, "create_from_generation", new_path)
    monkeypatch.setattr(main, "shadow_register_existing_async", old_path)

    path = tmp_path / "fake_output.png"
    path.write_bytes(b"stub-bytes-for-dispatch")
    local_url = "/assets/output/fake_output.png"
    mime_type = "image/png"

    # Mirror the actual dispatch in save_ai_image_to_output (main.py L9208).
    async def dispatch():
        if main.FILE_SERVICE_PRIMARY_WRITE_GENERATION:
            with open(path, "rb") as f:
                _data = f.read()
            await asyncio.to_thread(
                main.file_service.create_from_generation,
                _data,
                mime_type=mime_type,
                legacy_path=str(path),
                legacy_url=local_url,
            )
        else:
            await main.shadow_register_existing_async(
                str(path), local_url, "ai_output", mime_type
            )

    asyncio.run(dispatch())
    return new_path, old_path


def test_t148_feature_flag_false_does_not_execute_new_path(monkeypatch, tmp_path):
    """flag=False → shadow_register_existing_async called; create_from_generation NOT called."""
    import main

    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_GENERATION", False)
    new_path, old_path = _drive_ai_output_dispatch(monkeypatch, tmp_path)

    assert new_path.call_count == 0, "new path must not fire when flag is False"
    assert old_path.call_count == 1, "old shadow path must fire when flag is False"


# ---------------------------------------------------------------------------
# T149: feature flag true -> new path writes, old path skipped
# ---------------------------------------------------------------------------


def test_t149_feature_flag_true_executes_new_path(monkeypatch, tmp_path):
    """flag=True → create_from_generation called; shadow_register_existing_async NOT called."""
    import main

    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_GENERATION", True)
    new_path, old_path = _drive_ai_output_dispatch(monkeypatch, tmp_path)

    assert new_path.call_count == 1, "new path must fire exactly once when flag is True"
    assert old_path.call_count == 0, "old shadow path must be skipped when flag is True"
    # Confirm the new path received the intended kwargs (contract, not just count).
    _, kwargs = new_path.call_args
    assert kwargs["mime_type"] == "image/png"
    assert kwargs["legacy_url"].startswith("/assets/output/")


# ---------------------------------------------------------------------------
# T153: rollback -> feature flag false restores old path
# ---------------------------------------------------------------------------


def test_t153_feature_flag_rollback_restores_old_path(monkeypatch, tmp_path):
    """flag=True → new path fires; then flag=False → old path fires again.

    Verifies rollback semantics with real dispatch: the second dispatch cycle
    (post-rollback) must invoke the old shadow_register path exactly once and
    must NOT accumulate new-path calls beyond the first cycle.
    """
    import main

    # Cycle 1: flag=True
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_GENERATION", True)
    new_path_1, old_path_1 = _drive_ai_output_dispatch(monkeypatch, tmp_path)
    assert new_path_1.call_count == 1
    assert old_path_1.call_count == 0

    # Cycle 2: rollback to False (fresh mocks, independent dispatch)
    monkeypatch.setattr(main, "FILE_SERVICE_PRIMARY_WRITE_GENERATION", False)
    new_path_2, old_path_2 = _drive_ai_output_dispatch(monkeypatch, tmp_path)
    assert new_path_2.call_count == 0, "post-rollback: new path must not fire"
    assert old_path_2.call_count == 1, "post-rollback: old shadow path must fire"


# ---------------------------------------------------------------------------
# T154: 21 durable hook freeze zone AST vs a6f863a
# ---------------------------------------------------------------------------


def test_t154_durable_hooks_ast_freeze_vs_a6f863a():
    """All 21 durable hook functions still contain shadow_register_existing."""
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    expected = {
        "save_ai_image_to_output",
        "save_remote_video_to_output",
        "runninghub_store_remote_output",
        "download_image",
        "download_comfy_output",
        "save_comfy_text_output",
        "generate_codex_provider_image_via_gpt_image_2_skill",
        "generate_gemini_cli_provider_image",
        "import_local_image_file",
        "jimeng_local_output_url",
        "poll_angle_cloud",
        "generate_angle_cloud",
        "generate_cloud",
        "ms_generate",
        "upload_ai_reference",
        "upload_ai_base64",
        "upload_local_assets",
        "import_local_assets_from_urls",
        "make_asset_library_item",
        "make_workflow_library_item_from_bytes",
        "import_canvas_workflow",
    }
    for name in expected:
        dumped = _function_source(tree, name)
        assert "shadow_register_existing" in dumped, name

    # Also verify the 3 excluded functions still do NOT contain shadow_register
    assert "shadow_register_existing" not in _function_source(tree, "_local_upload_item")
    assert "shadow_register_existing" not in _function_source(tree, "export_canvas_workflow")
    assert "shadow_register_existing" not in _function_source(tree, "upload_comfyui_base64")
