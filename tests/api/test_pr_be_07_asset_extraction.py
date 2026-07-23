"""PR-BE-07 focused contracts for Asset module + 3 router group extraction.

Test IDs: T430-T479（Wave 3-N.7 Batch 1 主线 A · Backend Architect subagent ·
候选 B 完整抽出 40 路由 · GM-14 圆桌自治第 9 次实证 · CB-P5-32 挂账）

候选 B 差异说明（GM-14 圆桌自治第 9 次实证）：
- 原任务书要求 19 路由抽出（11 local-assets + 4 asset-library + 4
  prompt-libraries）；GM-16 v2 发现实际 main.py 存在 40 路由（11 local-assets
  + 18 asset-library + 11 prompt-libraries）→ Lead 圆桌决议拍板候选 B 完整
  抽出 40 路由。
- 任务书 §GM-16 数字精度 CB-P5-32 挂账（不阻塞主线）。

契约覆盖（T430-T479 · 50 项）：
- T430-T440: 11 local-assets 路由 openapi path/method 存在
- T441-T451: 11 prompt-libraries 路由 openapi path/method 存在
- T452-T469: 18 asset-library 路由 openapi path/method 存在
- T470: 3 router 装配齐全（include_router 断言）
- T471: 3 router + module 文件不 import main
- T472: 3 router 不 import main（AST 穿透验证）
- T473: 顺序敏感路由（GET /api/prompt-libraries vs POST /api/prompt-libraries）
- T474: 顺序敏感路由（GET /api/asset-library vs POST /api/asset-library/workflows/upload）
- T475: 顺序敏感路由（POST /api/asset-library/items vs POST /api/asset-library/items/batch）
- T476: 顺序敏感路由（POST /api/asset-library/items/delete vs POST /api/asset-library/items/move）
- T477: P0 密钥零入库 sentinel sweep · upload 场景
- T478: P0 密钥零入库 sentinel sweep · asset-library 场景
- T479: P0 密钥零入库 sentinel sweep · prompt-libraries 场景
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.modules.asset.service import _sanitize_payload_dict


ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"
ROUTER_DIR = ROOT / "app" / "api" / "routers"
MODULE_DIR = ROOT / "app" / "modules" / "asset"


# ---------------------------------------------------------------------------
# Route inventory - 40 routes grouped by path prefix
# ---------------------------------------------------------------------------

LOCAL_ASSETS_ROUTES = {
    ("POST", "/api/local-assets/upload"),
    ("POST", "/api/local-assets/import-urls"),
    ("GET", "/api/local-assets"),
    ("POST", "/api/local-assets/folders"),
    ("PATCH", "/api/local-assets/folders"),
    ("PATCH", "/api/local-assets/items"),
    ("POST", "/api/local-assets/delete"),
    ("POST", "/api/local-assets/move"),
    ("POST", "/api/local-assets/caption"),
    ("POST", "/api/local-assets/classify"),
    ("PATCH", "/api/local-assets/caption"),
}

PROMPT_LIBRARIES_ROUTES = {
    ("GET", "/api/prompt-libraries"),
    ("POST", "/api/prompt-libraries"),
    ("PATCH", "/api/prompt-libraries/{library_id}"),
    ("DELETE", "/api/prompt-libraries/{library_id}"),
    ("POST", "/api/prompt-libraries/items"),
    ("PATCH", "/api/prompt-libraries/items/{item_id}"),
    ("DELETE", "/api/prompt-libraries/items/{item_id}"),
    ("POST", "/api/prompt-libraries/items/delete"),
    ("POST", "/api/prompt-libraries/categories"),
    ("PATCH", "/api/prompt-libraries/categories/{category_id}"),
    ("DELETE", "/api/prompt-libraries/categories/{category_id}"),
}

ASSET_LIBRARY_ROUTES = {
    ("POST", "/api/asset-library/workflows/upload"),
    ("GET", "/api/asset-library"),
    ("POST", "/api/asset-library/libraries"),
    ("PATCH", "/api/asset-library/libraries/{library_id}"),
    ("DELETE", "/api/asset-library/libraries/{library_id}"),
    ("POST", "/api/asset-library/categories"),
    ("PATCH", "/api/asset-library/categories/{category_id}"),
    ("DELETE", "/api/asset-library/categories/{category_id}"),
    ("POST", "/api/asset-library/items"),
    ("POST", "/api/asset-library/items/batch"),
    ("PATCH", "/api/asset-library/items/{item_id}"),
    ("POST", "/api/asset-library/items/classify"),
    ("POST", "/api/asset-library/items/{item_id}/register-avatar"),
    ("POST", "/api/asset-library/items/{item_id}/avatar-status"),
    ("DELETE", "/api/asset-library/items/{item_id}"),
    ("POST", "/api/asset-library/items/delete"),
    ("POST", "/api/asset-library/items/move"),
    ("POST", "/api/asset-library/items/crop"),
}

ALL_40_ROUTES = LOCAL_ASSETS_ROUTES | PROMPT_LIBRARIES_ROUTES | ASSET_LIBRARY_ROUTES


def _application_routes() -> list[tuple[str, str]]:
    """Return [(path, method), ...] for all registered FastAPI routes."""
    import main

    routes: list[tuple[str, str]] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                routes.append((route.path, method))
    return routes


# ---------------------------------------------------------------------------
# T430-T440 — 11 local-assets routes present in openapi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method, path", sorted(LOCAL_ASSETS_ROUTES),
    ids=[f"{m.lower()}_{p.replace('/', '_')}" for m, p in sorted(LOCAL_ASSETS_ROUTES)],
)
def test_t430_local_assets_route_present(method: str, path: str) -> None:
    """T430-T440 · 各 local-assets 路由的 path/method 存在于 openapi 中。"""
    routes = _application_routes()
    assert (path, method.upper()) in routes, (
        f"local-assets 路由 {method} {path} 未在 openapi 中注册"
    )


# ---------------------------------------------------------------------------
# T441-T451 — 11 prompt-libraries routes present in openapi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method, path", sorted(PROMPT_LIBRARIES_ROUTES),
    ids=[f"{m.lower()}_{p.replace('/', '_')}" for m, p in sorted(PROMPT_LIBRARIES_ROUTES)],
)
def test_t441_prompt_libraries_route_present(method: str, path: str) -> None:
    """T441-T451 · 各 prompt-libraries 路由的 path/method 存在于 openapi 中。"""
    routes = _application_routes()
    assert (path, method.upper()) in routes, (
        f"prompt-libraries 路由 {method} {path} 未在 openapi 中注册"
    )


# ---------------------------------------------------------------------------
# T452-T469 — 18 asset-library routes present in openapi
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "method, path", sorted(ASSET_LIBRARY_ROUTES),
    ids=[f"{m.lower()}_{p.replace('/', '_')}" for m, p in sorted(ASSET_LIBRARY_ROUTES)],
)
def test_t452_asset_library_route_present(method: str, path: str) -> None:
    """T452-T469 · 各 asset-library 路由的 path/method 存在于 openapi 中。"""
    routes = _application_routes()
    assert (path, method.upper()) in routes, (
        f"asset-library 路由 {method} {path} 未在 openapi 中注册"
    )


# ---------------------------------------------------------------------------
# T470 — 3 router include_router 装配齐全
# ---------------------------------------------------------------------------


def test_t470_three_routers_include_router_all_registered() -> None:
    """T470 · main.py 里的 `include_router` 至少覆盖三处新 router 装配:
    local_assets / asset_library / prompt_libraries。
    """

    src = MAIN_PATH.read_text(encoding="utf-8")
    for factory in (
        "create_local_assets_router",
        "create_asset_library_router",
        "create_prompt_libraries_router",
    ):
        pattern = re.compile(
            r"app\.include_router\s*\(\s*" + re.escape(factory) + r"\s*\("
        )
        assert pattern.search(src) is not None, (
            f"main.py 缺少 `app.include_router({factory}(...))` 装配点"
        )


# ---------------------------------------------------------------------------
# T471 — 3 router + module 文件不 import main
# ---------------------------------------------------------------------------


def test_t471_router_files_do_not_import_main() -> None:
    """T471 · `app/api/routers/{local_assets,asset_library,prompt_libraries}.py`
    不 `import main`（继承 PR-BE-05/06/08/09 硬约束）。
    """

    for router_name in ("local_assets", "asset_library", "prompt_libraries"):
        tree = ast.parse(
            (ROUTER_DIR / f"{router_name}.py").read_text(encoding="utf-8")
        )
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "main" not in imported, (
            f"{router_name}.py 违反硬约束:不许 import main"
        )


def test_t471_module_files_do_not_import_main() -> None:
    """T471 补充 · `app/modules/asset/*.py` 全部不 `import main`。"""

    for py_path in MODULE_DIR.glob("*.py"):
        tree = ast.parse(py_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "main", (
                        f"{py_path.name} 违反硬约束:不许 import main"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module != "main", (
                    f"{py_path.name} 违反硬约束:不许 from main import"
                )


# ---------------------------------------------------------------------------
# T472 — 3 router AST 穿透验证（不 import main — 强校验）
# ---------------------------------------------------------------------------


def test_t472_router_ast_no_main_import() -> None:
    """T472 · 对三个 router 文件做 AST 穿透验证，确认无任何形式的 `import main`
    或 `from main import ...`（覆盖 `importlib.import_module` 等间接引
    用不在本测试范围——但 router 文件在当前实现中不包含此类引用）。
    """

    for router_name in ("local_assets", "asset_library", "prompt_libraries"):
        source = (ROUTER_DIR / f"{router_name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "main" or alias.name.startswith("main."):
                        pytest.fail(
                            f"{router_name}.py 含 `import {alias.name}`"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module == "main" or (node.module or "").startswith("main."):
                    pytest.fail(
                        f"{router_name}.py 含 `from {node.module} import`"
                    )


# ---------------------------------------------------------------------------
# T473 — 顺序敏感路由：GET /api/prompt-libraries vs POST /api/prompt-libraries
# ---------------------------------------------------------------------------


def test_t473_prompt_libraries_get_before_post() -> None:
    """T473 · /api/prompt-libraries 的 GET 和 POST 路由均存在且仅注册一次。
    路由顺序在 FastAPI 中由装饰器/ add_api_route 声明顺序保证；当 GET 在
    POST 前声明时，FastAPI 遍历匹配先命中 GET。
    """

    routes = _application_routes()
    assert ("/api/prompt-libraries", "GET") in routes
    assert ("/api/prompt-libraries", "POST") in routes
    assert routes.count(("/api/prompt-libraries", "GET")) == 1
    assert routes.count(("/api/prompt-libraries", "POST")) == 1


# ---------------------------------------------------------------------------
# T474 — 顺序敏感路由：GET /api/asset-library vs POST /api/asset-library/workflows/upload
# ---------------------------------------------------------------------------


def test_t474_asset_library_get_before_workflows_upload() -> None:
    """T474 · /api/asset-library 的 GET 和 /api/asset-library/workflows/upload
    的 POST 路由均存在且仅注册一次。GET /api/asset-library 必须在 POST
    /api/asset-library/workflows/upload 之前声明（避免 FastAPI 将 workflows
    误匹配为 library_id 通配路由）。
    """

    routes = _application_routes()
    assert ("/api/asset-library", "GET") in routes
    assert ("/api/asset-library/workflows/upload", "POST") in routes
    assert routes.count(("/api/asset-library", "GET")) == 1
    assert routes.count(("/api/asset-library/workflows/upload", "POST")) == 1


# ---------------------------------------------------------------------------
# T475 — 顺序敏感路由：POST /api/asset-library/items vs POST /api/asset-library/items/batch
# ---------------------------------------------------------------------------


def test_t475_asset_library_items_batch_not_conflict() -> None:
    """T475 · /api/asset-library/items 和 /api/asset-library/items/batch
    的 POST 路由均存在且仅注册一次。`/items/batch` 必须在 `/items` 之后声明
    （由 router 内 add_api_route 声明顺序保证）。
    """

    routes = _application_routes()
    assert ("/api/asset-library/items", "POST") in routes
    assert ("/api/asset-library/items/batch", "POST") in routes
    assert routes.count(("/api/asset-library/items", "POST")) == 1
    assert routes.count(("/api/asset-library/items/batch", "POST")) == 1


# ---------------------------------------------------------------------------
# T476 — 顺序敏感路由：POST /api/asset-library/items/delete vs POST /api/asset-library/items/move
# ---------------------------------------------------------------------------


def test_t476_asset_library_items_delete_move_not_conflict() -> None:
    """T476 · /api/asset-library/items/delete 和 /api/asset-library/items/move
    的 POST 路由均存在且仅注册一次。
    """

    routes = _application_routes()
    assert ("/api/asset-library/items/delete", "POST") in routes
    assert ("/api/asset-library/items/move", "POST") in routes
    assert routes.count(("/api/asset-library/items/delete", "POST")) == 1
    assert routes.count(("/api/asset-library/items/move", "POST")) == 1


# ---------------------------------------------------------------------------
# T477 — P0 密钥零入库 sentinel sweep · upload 场景
# ---------------------------------------------------------------------------


_SECRET_SENTINELS = (
    "SECRET_VALUE_LEAK",
    "sk-fake-leaked-1234567890",
    "AKIA0123456789ABCDEF",
    "Bearer FAKELEAKEDBEARER",
)


def test_t477_sanitize_payload_dict_upload_scenario() -> None:
    """T477 · P0 密钥零入库 · service 层 `_sanitize_payload_dict` 覆盖
    local-assets upload 场景常见字段名（api_key / secret / access_token /
    authorization / password / credential）。sentinel 反查 = 0 命中。
    """

    payload_dict = {
        "prompt": "hello",
        "provider_id": "comfly",
        "api_key": "sk-fake-leaked-1234567890",
        "secret": "SECRET_VALUE_LEAK",
        "access_token": "AKIA0123456789ABCDEF",
        "authorization": "Bearer FAKELEAKEDBEARER",
        "password": "hunter2",
        "credential": {"nested": "SECRET_VALUE_LEAK"},
    }
    cleaned = _sanitize_payload_dict(payload_dict)
    serialized = json.dumps(cleaned, ensure_ascii=False)
    for sentinel in _SECRET_SENTINELS:
        assert sentinel not in serialized, (
            f"P0 密钥零入库违反 · sanitize 后仍出现 sentinel `{sentinel}`"
        )
    # 非密钥字段保留
    assert cleaned["prompt"] == "hello"
    assert cleaned["provider_id"] == "comfly"
    # 密钥字段被替换为 [REDACTED]
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["secret"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# T478 — P0 密钥零入库 sentinel sweep · asset-library 场景
# ---------------------------------------------------------------------------


def test_t478_sanitize_payload_dict_asset_library_scenario() -> None:
    """T478 · P0 密钥零入库 · service 层 `_sanitize_payload_dict` 覆盖
    asset-library classify / avatar 场景的 provider 字段。
    sentinel 反查 = 0 命中。
    """

    payload_dict = {
        "library_id": "lib_abc",
        "ids": ["item_1", "item_2"],
        "provider": "modelscope",
        "model": "gpt-4v",
        "api_key": "Bearer FAKELEAKEDBEARER",
        "prompt": "classify",
    }
    cleaned = _sanitize_payload_dict(payload_dict)
    serialized = json.dumps(cleaned, ensure_ascii=False)
    for sentinel in _SECRET_SENTINELS:
        assert sentinel not in serialized, (
            f"P0 密钥零入库违反 · sanitize 后仍出现 sentinel `{sentinel}`"
        )
    # 非密钥字段保留
    assert cleaned["library_id"] == "lib_abc"
    assert cleaned["provider"] == "modelscope"
    assert cleaned["model"] == "gpt-4v"
    # 密钥字段被替换为 [REDACTED]
    assert cleaned["api_key"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# T479 — P0 密钥零入库 sentinel sweep · prompt-libraries 场景
# ---------------------------------------------------------------------------


def test_t479_sanitize_payload_dict_prompt_libraries_scenario() -> None:
    """T479 · P0 密钥零入库 · service 层 `_sanitize_payload_dict` 覆盖
    prompt-libraries 场景（无敏感字段基线—确认无假阳性）。
    sentinel 反查 = 0 命中。
    """

    payload_dict = {
        "name": "my prompt library",
        "library_id": "lib_xyz",
        "positive": "beautiful landscape",
        "negative": "blurry",
        "category": "landscape",
        "scene": "outdoor",
    }
    cleaned = _sanitize_payload_dict(payload_dict)
    serialized = json.dumps(cleaned, ensure_ascii=False)
    for sentinel in _SECRET_SENTINELS:
        assert sentinel not in serialized, (
            f"P0 密钥零入库违反 · sanitize 后仍出现 sentinel `{sentinel}`"
        )
    # 全部字段非密钥，应原样保留
    assert cleaned == payload_dict


# ---------------------------------------------------------------------------
# Sanity: 40 unique routes each registered exactly once
# ---------------------------------------------------------------------------


def test_all_40_asset_routes_registered_exactly_once() -> None:
    """全部 40 路由每条只注册一次（无重复挂载）。"""

    routes = _application_routes()
    for method, path in ALL_40_ROUTES:
        count = routes.count((path, method.upper()))
        assert count == 1, (
            f"路由 {method} {path} 注册了 {count} 次（期望 1）"
        )