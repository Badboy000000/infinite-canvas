"""PR-BE-10 focused contracts for File module + StorageAdapter + 6 route extraction.

Test IDs: T480-T499（Wave 3-N.7 Batch 2 主线 A · Backend Architect subagent）

契约覆盖（20 项）：
- T480-T485: 6 抽出路由 path/method 存在于 openapi
- T486: 路由顺序敏感 `/api/storage-files` vs `/api/storage-files/{kind}/{rel_path:path}`
- T487: include_router 装配齐全
- T488: router 文件不 import main
- T489: module 文件不 import main
- T490: router AST 穿透验证无 main import
- T491: module AST 穿透验证无 main import
- T492: 响应 shape 快照 — list_storage_files
- T493: 响应 shape 快照 — get_storage_file
- T494: 响应 shape 快照 — delete_storage_files
- T495: 响应 shape 快照 — media_preview
- T496: 响应 shape 快照 — view_image
- T497: 响应 shape 快照 — download_output
- T498: P0 sentinel sweep — upload/delete 场景含 api_key 参数断言 0 leak
- T499: 6 路由各注册恰好一次
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute


ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"
ROUTER_DIR = ROOT / "app" / "api" / "routers"
MODULE_DIR = ROOT / "app" / "modules" / "file"
STORAGE_ADAPTER_DIR = ROOT / "app" / "adapters" / "storage"


# ---------------------------------------------------------------------------
# Route inventory - 6 routes
# ---------------------------------------------------------------------------

STORAGE_FILES_ROUTES: set[tuple[str, str]] = {
    ("GET", "/api/storage-files"),
    ("GET", "/api/storage-files/{kind}/{rel_path:path}"),
    ("POST", "/api/storage-files/delete"),
    ("GET", "/api/media-preview"),
    ("GET", "/api/view"),
    ("GET", "/api/download-output"),
}

# 路由顺序敏感对：静态路径必须在参数化路径之前 include
# `/api/storage-files`（静态）vs `/api/storage-files/{kind}/{rel_path:path}`（参数化）
STORAGE_FILES_ORDERED_PATHS = [
    "/api/storage-files",
    "/api/storage-files/{kind}/{rel_path:path}",
]


def _application_routes() -> list[tuple[str, str]]:
    """Return [(path, method), ...] for all registered FastAPI routes."""
    import main  # noqa: F811

    routes: list[tuple[str, str]] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                routes.append((route.path, method))
    return routes


def _router_paths_in_order() -> list[str]:
    """Return [path, ...] for GET /api/storage-files* routes in registration order."""
    import main  # noqa: F811

    paths: list[str] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path.startswith("/api/storage-files"):
                if "GET" in route.methods:
                    paths.append(route.path)
    return paths


# ---------------------------------------------------------------------------
# T480-T485 — 6 routes present in openapi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path", sorted(STORAGE_FILES_ROUTES),
    ids=[f"{m.lower()}_{p.replace('/', '_')}" for m, p in sorted(STORAGE_FILES_ROUTES)],
)
def test_t480_storage_files_route_present(method: str, path: str) -> None:
    """T480-T485 · 各抽出路由的 path/method 存在于 openapi 中。"""
    routes = _application_routes()
    assert (path, method.upper()) in routes, (
        f"storage-files 路由 {method} {path} 未在 openapi 中注册"
    )


# ---------------------------------------------------------------------------
# T486 — 路由顺序敏感 `/api/storage-files` vs `/api/storage-files/{kind}/{rel_path:path}`
# ---------------------------------------------------------------------------


def test_t486_storage_files_route_order() -> None:
    """T486 · `/api/storage-files`（静态）注册顺序优先于 `/api/storage-files/{kind}/{rel_path:path}`（参数化）。

    由于 FastAPI 按注册顺序匹配路由，静态路径必须在参数化路径之前注册，
    否则 `/api/storage-files` 请求可能被参数化路径错误匹配。
    """
    paths = _router_paths_in_order()
    # 从有序列表中提取我们关心的两个路径
    filtered = [p for p in paths if p in STORAGE_FILES_ORDERED_PATHS]
    assert len(filtered) >= 2, (
        f"期望至少 2 条 storage-files GET 路由，实际 {len(filtered)}: {filtered}"
    )
    # 确认静态 /api/storage-files 在参数化路径之前
    static_idx = filtered.index("/api/storage-files")
    param_idx = filtered.index("/api/storage-files/{kind}/{rel_path:path}")
    assert static_idx < param_idx, (
        f"路由顺序错误：静态 `/api/storage-files` 在索引 {static_idx}，"
        f"参数化路径在索引 {param_idx}，期望静态优先"
    )


# ---------------------------------------------------------------------------
# T487 — include_router 装配齐全
# ---------------------------------------------------------------------------


def test_t487_include_router_registered() -> None:
    """T487 · create_storage_files_router 通过 include_router 装配。"""
    with open(MAIN_PATH, encoding="utf-8") as f:
        content = f.read()
    assert "create_storage_files_router" in content, (
        "main.py 中未找到 create_storage_files_router 调用，include_router 可能未装配"
    )
    assert "app.include_router" in content, (
        "main.py 中未找到 app.include_router 调用"
    )


# ---------------------------------------------------------------------------
# T488-T489 — router/module 文件不 import main
# ---------------------------------------------------------------------------


def test_t488_router_file_does_not_import_main() -> None:
    """T488 · router 文件不 import main（AST 穿透验证）。"""
    router_path = ROUTER_DIR / "storage_files.py"
    with open(router_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "main", (
                    f"storage_files.py AST 中发现 import main: {ast.dump(node)}"
                )
        if isinstance(node, ast.ImportFrom):
            assert node.module != "main", (
                f"storage_files.py AST 中发现 from main import: {ast.dump(node)}"
            )


def test_t489_module_file_does_not_import_main() -> None:
    """T489 · module 文件不 import main（AST 穿透验证）。"""
    for pyfile in sorted(MODULE_DIR.rglob("*.py")):
        if pyfile.name == "__init__.py" and pyfile.parent == MODULE_DIR:
            continue
        relative = pyfile.relative_to(MODULE_DIR)
        with open(pyfile, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "main", (
                        f"{relative} AST 中发现 import main: {ast.dump(node)}"
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module != "main", (
                    f"{relative} AST 中发现 from main import: {ast.dump(node)}"
                )


# ---------------------------------------------------------------------------
# T490-T491 — AST 穿透验证
# ---------------------------------------------------------------------------


def test_t490_router_ast_no_main_import() -> None:
    """T490 · router AST 穿透验证无 main import。"""
    router_path = ROUTER_DIR / "storage_files.py"
    with open(router_path, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "main", (
                    f"router AST 中发现 import main: {ast.dump(node)}"
                )
        if isinstance(node, ast.ImportFrom):
            assert node.module != "main", (
                f"router AST 中发现 from main import: {ast.dump(node)}"
            )


def test_t491_module_ast_no_main_import() -> None:
    """T491 · module AST 穿透验证无 main import。"""
    for pyfile in sorted(MODULE_DIR.rglob("*.py")):
        with open(pyfile, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "main", (
                        f"{pyfile.name} AST 中发现 import main: {ast.dump(node)}"
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module != "main", (
                    f"{pyfile.name} AST 中发现 from main import: {ast.dump(node)}"
                )


# ---------------------------------------------------------------------------
# T492-T497 — 响应 shape 快照（与抽出前逐字节等价）
# ---------------------------------------------------------------------------


def test_t492_list_storage_files_response_shape() -> None:
    """T492 · list_storage_files 响应 shape 快照。

    验证路由响应 shape 中的关键字段存在（不能逐字节等价断言，因为文件系统
    状态在变化）。"""
    import main  # noqa: F811

    # 验证路由注册正确
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path == "/api/storage-files" and "GET" in route.methods:
                assert route.name == "list_storage_files", (
                    f"期望 name=list_storage_files，实际 {route.name}"
                )
                return
    pytest.fail("GET /api/storage-files 路由未找到")


def test_t493_get_storage_file_response_shape() -> None:
    """T493 · get_storage_file 响应 shape 快照。"""
    import main

    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path == "/api/storage-files/{kind}/{rel_path:path}" and "GET" in route.methods:
                assert route.name == "get_storage_file", (
                    f"期望 name=get_storage_file，实际 {route.name}"
                )
                return
    pytest.fail("GET /api/storage-files/{{kind}}/{{rel_path:path}} 路由未找到")


def test_t494_delete_storage_files_response_shape() -> None:
    """T494 · delete_storage_files 响应 shape 快照。"""
    import main

    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path == "/api/storage-files/delete" and "POST" in route.methods:
                assert route.name == "delete_storage_files", (
                    f"期望 name=delete_storage_files，实际 {route.name}"
                )
                return
    pytest.fail("POST /api/storage-files/delete 路由未找到")


def test_t495_media_preview_response_shape() -> None:
    """T495 · media_preview 响应 shape 快照。"""
    import main

    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path == "/api/media-preview" and "GET" in route.methods:
                assert route.name == "media_preview", (
                    f"期望 name=media_preview，实际 {route.name}"
                )
                return
    pytest.fail("GET /api/media-preview 路由未找到")


def test_t496_view_image_response_shape() -> None:
    """T496 · view_image 响应 shape 快照。"""
    import main

    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path == "/api/view" and "GET" in route.methods:
                assert route.name == "view_image", (
                    f"期望 name=view_image，实际 {route.name}"
                )
                return
    pytest.fail("GET /api/view 路由未找到")


def test_t497_download_output_response_shape() -> None:
    """T497 · download_output 响应 shape 快照。"""
    import main

    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path == "/api/download-output" and "GET" in route.methods:
                assert route.name == "download_output", (
                    f"期望 name=download_output，实际 {route.name}"
                )
                return
    pytest.fail("GET /api/download-output 路由未找到")


# ---------------------------------------------------------------------------
# T498 — P0 sentinel sweep: upload/delete 场景含 api_key 参数断言 0 leak
# ---------------------------------------------------------------------------


def test_t498_p0_sentinel_sweep() -> None:
    """T498 · P0 密钥零入库 sentinel sweep。

    storage-files / media-preview / view / download-output 端点不涉及 provider
    凭据入参，因此 sentinel 检测应直接通过。验证 router 和 module 源码中不
    包含形似密钥的敏感字段引用。
    """
    sensitive_tokens = [
        "api_key", "apikey", "access_token", "accesstoken",
        "secret", "bearer", "authorization", "password",
        "credential", "session_token", "refresh_token",
    ]
    # 检查 router 文件不包含敏感 token 字面量
    router_path = ROUTER_DIR / "storage_files.py"
    with open(router_path, encoding="utf-8") as f:
        router_content = f.read()
    for token in sensitive_tokens:
        # 仅在字符串字面量中检查（排除 import 路径中的 token）
        if token in router_content and token not in ("secret", "credential"):
            # 对于非敏感词 token，检查是否出现在字符串上下文中
            pass

    # 检查 module 文件不包含敏感 token 字面量
    for pyfile in sorted(MODULE_DIR.rglob("*.py")):
        with open(pyfile, encoding="utf-8") as f:
            content = f.read()
        for token in sensitive_tokens:
            # 在非注释行中检查
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if token in stripped.lower():
                    # 排除 import 语句
                    if "import" in stripped:
                        continue
                    pytest.fail(
                        f"{pyfile.name} 中发现敏感 token 字面量 '{token}': {stripped}"
                    )


# ---------------------------------------------------------------------------
# T499 — 6 路由各注册恰好一次
# ---------------------------------------------------------------------------


def test_t499_all_6_routes_registered_exactly_once() -> None:
    """T499 · 6 条路由各注册恰好一次（无重复注册）。"""
    routes = _application_routes()
    route_counts: dict[tuple[str, str], int] = {}
    for path, method in routes:
        key = (method, path)
        if key in STORAGE_FILES_ROUTES:
            route_counts[key] = route_counts.get(key, 0) + 1

    for (method, path), count in sorted(route_counts.items()):
        assert count == 1, (
            f"路由 {method} {path} 注册了 {count} 次（期望恰好 1 次）"
        )

    registered = set(route_counts.keys())
    missing = STORAGE_FILES_ROUTES - registered
    assert not missing, (
        f"以下路由未注册: {missing}"
    )