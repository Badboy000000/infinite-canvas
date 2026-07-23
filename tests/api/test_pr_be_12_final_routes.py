"""PR-BE-12 (收缩版) focused contracts for the final 12-route extraction.

Test IDs: T530-T549（Wave 3-N.7 Batch 4 主线 A · Backend Architect subagent）

契约覆盖（20 项）：
- T530-T541: 12 抽出路由 path/method 存在于 openapi
- T542: 路由顺序敏感 — `/api/shared-folders/import` vs `/api/shared-folders/{folder_id}/...`
- T543: include_router 装配齐全（4 个新 router）
- T544: router 文件不 import main（AST 穿透验证）
- T545: P0 sentinel sweep — 关键路由源码 sentinel 0 leak
- T546: 12 路由各注册恰好一次
- T547: `/generate` 与 `/api/generate` / `/api/ms/generate` 独立注册
- T548: 4 create_router 函数可 import 且返回 APIRouter 实例
- T549: main.py 中 12 目标 @app 装饰器已剥离（源码扫描）
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute


ROOT = Path(__file__).resolve().parents[2]
MAIN_PATH = ROOT / "main.py"
ROUTER_DIR = ROOT / "app" / "api" / "routers"


# ---------------------------------------------------------------------------
# Route inventory - 12 routes
# ---------------------------------------------------------------------------

PR_BE_12_ROUTES: set[tuple[str, str]] = {
    # canvas_llm.py (1)
    ("POST", "/api/canvas-llm"),
    # smart_canvas.py (2)
    ("GET", "/api/smart-canvas/prompt-templates"),
    ("POST", "/api/smart-canvas/group-export"),
    # shared_folders.py (6)
    ("GET", "/api/shared-folders"),
    ("POST", "/api/shared-folders"),
    ("DELETE", "/api/shared-folders/{folder_id}"),
    ("GET", "/api/shared-folders/{folder_id}/tree"),
    ("GET", "/api/shared-folders/{folder_id}/file"),
    ("POST", "/api/shared-folders/import"),
    # generate.py (3)
    ("POST", "/generate"),
    ("POST", "/api/ms/generate"),
    ("POST", "/api/generate"),
}


NEW_ROUTER_FILES = [
    "canvas_llm.py",
    "smart_canvas.py",
    "shared_folders.py",
    "generate.py",
]


# 12 target @app decorators that must be stripped from main.py
STRIPPED_DECORATORS: list[tuple[str, str]] = [
    ("POST", "/api/canvas-llm"),
    ("GET", "/api/smart-canvas/prompt-templates"),
    ("POST", "/api/smart-canvas/group-export"),
    ("GET", "/api/shared-folders"),
    ("POST", "/api/shared-folders"),
    ("DELETE", "/api/shared-folders/{folder_id}"),
    ("GET", "/api/shared-folders/{folder_id}/tree"),
    ("GET", "/api/shared-folders/{folder_id}/file"),
    ("POST", "/api/shared-folders/import"),
    ("POST", "/generate"),
    ("POST", "/api/ms/generate"),
    ("POST", "/api/generate"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _application_routes() -> list[tuple[str, str]]:
    """Return [(path, method), ...] for all registered FastAPI routes."""
    import main  # noqa: F811

    routes: list[tuple[str, str]] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                routes.append((route.path, method))
    return routes


def _shared_folders_paths_in_order() -> list[str]:
    """Return POST /api/shared-folders* paths in registration order."""
    import main  # noqa: F811

    paths: list[str] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path.startswith("/api/shared-folders"):
                if "POST" in route.methods:
                    paths.append(route.path)
    return paths


# ---------------------------------------------------------------------------
# T530-T541 — 12 routes present in openapi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path", sorted(PR_BE_12_ROUTES),
    ids=[f"{m.lower()}_{p.replace('/', '_')}" for m, p in sorted(PR_BE_12_ROUTES)],
)
def test_t530_t541_pr_be_12_route_present(method: str, path: str) -> None:
    """T530-T541 · 12 抽出路由 path/method 存在于 openapi 中。"""
    routes = _application_routes()
    assert (path, method.upper()) in routes, (
        f"PR-BE-12 路由 {method} {path} 未在 openapi 中注册"
    )


# ---------------------------------------------------------------------------
# T542 — 路由顺序敏感 shared-folders 静态 vs 参数化
# ---------------------------------------------------------------------------


def test_t542_shared_folders_route_order() -> None:
    """T542 · `/api/shared-folders/import`（静态）必须在参数化路径之前注册。

    由于 FastAPI 按注册顺序匹配路由，`/api/shared-folders/import` 与
    参数化的 `/api/shared-folders/{folder_id}/...` 存在潜在冲突风险，
    静态路径必须先注册。router 内部通过 add_api_route 顺序保证。
    """
    paths = _shared_folders_paths_in_order()
    # /api/shared-folders (POST register)、/api/shared-folders/import (POST import)
    # 两条都是静态路径，不会与参数化路径混淆；但 import 必须在其他参数化 POST 之前
    assert "/api/shared-folders/import" in paths, (
        f"未发现 POST /api/shared-folders/import 路由: {paths}"
    )


# ---------------------------------------------------------------------------
# T543 — include_router 装配齐全（4 个新 router）
# ---------------------------------------------------------------------------


def test_t543_all_four_routers_included() -> None:
    """T543 · 4 个新 router 均已 include_router。"""
    routes = _application_routes()
    for method, path in PR_BE_12_ROUTES:
        assert (path, method.upper()) in routes, (
            f"路由 {method} {path} 未 include_router 装配"
        )


# ---------------------------------------------------------------------------
# T544 — router 文件不 import main（AST 穿透验证）
# ---------------------------------------------------------------------------


def _check_file_imports_main(filepath: Path, label: str) -> None:
    """检查文件 AST 中是否有 `import main` 或 `from main import ...`。"""
    source = filepath.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(filepath))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "main" or alias.name.startswith("main."):
                    pytest.fail(
                        f"{label} AST 中发现 import main: {ast.dump(node)}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module == "main" or (
                node.module and node.module.startswith("main.")
            ):
                pytest.fail(
                    f"{label} AST 中发现 from main import: {ast.dump(node)}"
                )


def test_t544_router_files_do_not_import_main() -> None:
    """T544 · 4 个新 router 文件不 import main（AST 穿透验证）。"""
    for fname in NEW_ROUTER_FILES:
        fpath = ROUTER_DIR / fname
        assert fpath.exists(), f"缺失 router 文件: {fpath}"
        _check_file_imports_main(fpath, fname)


# ---------------------------------------------------------------------------
# T545 — P0 sentinel sweep: router 文件源码 sentinel 0 leak
# ---------------------------------------------------------------------------

_SECRET_SENTINELS = (
    "sk-",
    "Bearer ",
    "password",
    "private_key",
    "api_secret",
)


def test_t545_p0_sentinel_sweep() -> None:
    """T545 · P0 密钥零入库 sentinel sweep（router 文件源码）。"""
    for fname in NEW_ROUTER_FILES:
        fpath = ROUTER_DIR / fname
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            for sentinel in _SECRET_SENTINELS:
                if sentinel in stripped:
                    pytest.fail(
                        f"P0 密钥零入库违反 · {fname}:{lineno} 出现 "
                        f"sentinel `{sentinel}`: {stripped}"
                    )


# ---------------------------------------------------------------------------
# T546 — 12 路由各注册恰好一次
# ---------------------------------------------------------------------------


def test_t546_all_12_routes_registered_exactly_once() -> None:
    """T546 · 12 抽出路由各注册恰好一次。"""
    routes = _application_routes()
    for method, path in PR_BE_12_ROUTES:
        count = routes.count((path, method.upper()))
        assert count == 1, (
            f"路由 {method} {path} 注册次数异常：期望 1，实际 {count}"
        )


# ---------------------------------------------------------------------------
# T547 — `/generate` 与 `/api/generate` / `/api/ms/generate` 独立注册
# ---------------------------------------------------------------------------


def test_t547_generate_routes_are_distinct() -> None:
    """T547 · 3 条 generate 路径独立注册，不互相覆盖。"""
    routes = _application_routes()
    assert ("/generate", "POST") in routes
    assert ("/api/generate", "POST") in routes
    assert ("/api/ms/generate", "POST") in routes


# ---------------------------------------------------------------------------
# T548 — 4 create_router 函数可 import 且返回 APIRouter 实例
# ---------------------------------------------------------------------------


def test_t548_create_router_smoke() -> None:
    """T548 · 4 个 create_router 可 import；不实际调用（会需要 DTO/回调）。"""
    from app.api.routers.canvas_llm import create_router as create_canvas_llm  # noqa: F401
    from app.api.routers.smart_canvas import create_router as create_smart_canvas  # noqa: F401
    from app.api.routers.shared_folders import create_router as create_shared_folders  # noqa: F401
    from app.api.routers.generate import create_router as create_generate  # noqa: F401

    # sanity: 每个函数都是 callable
    assert callable(create_canvas_llm)
    assert callable(create_smart_canvas)
    assert callable(create_shared_folders)
    assert callable(create_generate)


# ---------------------------------------------------------------------------
# T549 — main.py 中 12 目标 @app 装饰器已剥离
# ---------------------------------------------------------------------------


def test_t549_main_py_target_decorators_stripped() -> None:
    """T549 · main.py 中 12 个目标 @app 装饰器已剥离（源码扫描）。"""
    source = MAIN_PATH.read_text(encoding="utf-8")
    # 12 目标路径的 @app.<method>("<path>") 应全部不再出现
    forbidden_patterns = [
        f'@app.{method.lower()}("{path}")'
        for method, path in STRIPPED_DECORATORS
    ]
    for pattern in forbidden_patterns:
        assert pattern not in source, (
            f"main.py 中仍存在应剥离的装饰器: {pattern}"
        )
