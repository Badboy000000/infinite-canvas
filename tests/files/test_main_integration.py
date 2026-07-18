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


def test_file_service_never_calls_adapter_put():
    path = ROOT / "app" / "services" / "files" / "file_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(isinstance(call.func, ast.Attribute) and call.func.attr in {"put", "open_writable_stream"} for call in calls)


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
