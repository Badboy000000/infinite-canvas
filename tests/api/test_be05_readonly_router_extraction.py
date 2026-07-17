"""PR-BE-05 focused contracts for the first read-only router extraction."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
TARGET_ROUTES = (
    ("/api/app-info", "GET"),
    ("/api/config", "GET"),
    ("/api/models", "GET"),
    ("/api/history", "GET"),
    ("/api/comfyui/instances", "GET"),
    ("/api/workflows", "GET"),
)
EXPECTED_ROUTER_ROUTES = {
    "system.py": {("/api/app-info", "get")},
    "storage.py": {("/api/config", "get"), ("/api/models", "get")},
    "history.py": {("/api/history", "get")},
    "comfyui.py": {("/api/comfyui/instances", "get")},
    "workflows.py": {("/api/workflows", "get")},
}


def _application_routes() -> list[tuple[str, str]]:
    import main

    routes = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            routes.extend((route.path, method) for method in sorted(route.methods))
    return routes


def _declared_router_routes(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    declared = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not decorator.args:
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            route_path = decorator.args[0]
            if isinstance(route_path, ast.Constant) and isinstance(route_path.value, str):
                declared.add((route_path.value, decorator.func.attr))
    return declared


def test_six_readonly_routes_are_registered_once_in_original_order() -> None:
    routes = _application_routes()

    for route in TARGET_ROUTES:
        assert routes.count(route) == 1, route

    target_positions = [routes.index(route) for route in TARGET_ROUTES]
    assert target_positions == sorted(target_positions)


def test_order_sensitive_neighbors_match_pre_extraction_order() -> None:
    routes = _application_routes()

    expected_runs = (
        (("/api/app-info", "GET"), ("/api/update-connectivity/probe", "GET")),
        (
            ("/api/config", "GET"),
            ("/api/models", "GET"),
            ("/api/providers", "GET"),
        ),
        (("/api/history", "GET"), ("/api/queue_status", "GET")),
        (
            ("/api/comfyui/instances", "GET"),
            ("/api/comfyui/instances", "PUT"),
            ("/api/workflows", "GET"),
            ("/api/workflows/{name:path}", "GET"),
        ),
    )
    for expected in expected_runs:
        start = routes.index(expected[0])
        assert tuple(routes[start : start + len(expected)]) == expected


def test_selected_openapi_operations_match_frozen_pre_extraction_shape() -> None:
    import main

    baseline = json.loads((ROOT / "tools" / "openapi_baseline.json").read_text(encoding="utf-8"))
    current = main.app.openapi()

    for path, _method in TARGET_ROUTES:
        assert current["paths"][path]["get"] == baseline["paths"][path]["get"]


def test_router_modules_declare_only_the_six_approved_get_routes() -> None:
    router_dir = ROOT / "app" / "api" / "routers"

    actual = {
        filename: _declared_router_routes(router_dir / filename)
        for filename in EXPECTED_ROUTER_ROUTES
    }
    assert actual == EXPECTED_ROUTER_ROUTES


def test_router_modules_never_import_main_or_own_legacy_io() -> None:
    router_dir = ROOT / "app" / "api" / "routers"

    for filename in EXPECTED_ROUTER_ROUTES:
        tree = ast.parse((router_dir / filename).read_text(encoding="utf-8"))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert "main" not in imported_modules, filename
        assert "os" not in imported_modules, filename
        assert "json" not in imported_modules, filename
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
            for node in ast.walk(tree)
        ), filename


def test_router_factories_dispatch_through_explicit_callbacks() -> None:
    from app.api.routers.comfyui import create_router as create_comfyui_router
    from app.api.routers.history import create_router as create_history_router
    from app.api.routers.storage import create_router as create_storage_router
    from app.api.routers.system import create_router as create_system_router
    from app.api.routers.workflows import create_router as create_workflows_router

    calls = []

    def app_info_callback():
        calls.append(("app_info", None))
        return {"source": "callback"}

    async def config_callback():
        calls.append(("config", None))
        return {"config": "callback"}

    async def models_callback():
        calls.append(("models", None))
        return {"models": ["callback"]}

    async def history_callback(history_type):
        calls.append(("history", history_type))
        return [{"type": history_type}]

    def comfyui_callback():
        calls.append(("comfyui", None))
        return {"instances": ["callback:8188"]}

    def workflows_callback():
        calls.append(("workflows", None))
        return {"workflows": [{"name": "callback.json"}]}

    synthetic_app = FastAPI()
    synthetic_app.include_router(create_system_router(app_info_callback))
    synthetic_app.include_router(create_storage_router(config_callback, models_callback))
    synthetic_app.include_router(create_history_router(history_callback))
    synthetic_app.include_router(create_comfyui_router(comfyui_callback))
    synthetic_app.include_router(create_workflows_router(workflows_callback))
    client = TestClient(synthetic_app)

    assert client.get("/api/app-info").json() == {"source": "callback"}
    assert client.get("/api/config").json() == {"config": "callback"}
    assert client.get("/api/models").json() == {"models": ["callback"]}
    assert client.get("/api/history?type=video").json() == [{"type": "video"}]
    assert client.get("/api/comfyui/instances").json() == {"instances": ["callback:8188"]}
    assert client.get("/api/workflows").json() == {
        "workflows": [{"name": "callback.json"}]
    }
    assert calls == [
        ("app_info", None),
        ("config", None),
        ("models", None),
        ("history", "video"),
        ("comfyui", None),
        ("workflows", None),
    ]


def test_main_assembly_injects_local_helpers_without_importing_main() -> None:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    main_imports = [
        node
        for node in ast.walk(tree)
        if (
            isinstance(node, ast.Import)
            and any(alias.name == "main" for alias in node.names)
        )
        or (isinstance(node, ast.ImportFrom) and node.module == "main")
    ]
    assert main_imports == []

    expected_factory_args = {
        "create_system_router": ("app_info",),
        "create_storage_router": ("ai_config", "ai_models"),
        "create_history_router": ("get_history_api",),
        "create_comfyui_router": ("get_comfyui_instances",),
        "create_workflows_router": ("list_workflows",),
    }
    actual_factory_args = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id not in expected_factory_args:
            continue
        actual_factory_args[node.func.id] = tuple(
            argument.id for argument in node.args if isinstance(argument, ast.Name)
        )
    assert actual_factory_args == expected_factory_args


def test_write_provider_runninghub_cli_and_websocket_routes_remain_in_main() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    required_main_decorators = (
        '@app.put("/api/comfyui/instances")',
        '@app.get("/api/workflows/{name:path}")',
        '@app.post("/api/workflows")',
        '@app.get("/api/providers")',
        '@app.get("/api/runninghub/app-info")',
        '@app.get("/api/jimeng/status")',
        '@app.websocket("/ws/stats")',
    )
    for decorator in required_main_decorators:
        assert decorator in source

    for path, _method in TARGET_ROUTES:
        assert f'@app.get("{path}")' not in source
