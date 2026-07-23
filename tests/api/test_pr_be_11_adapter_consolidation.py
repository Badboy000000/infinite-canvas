"""PR-BE-11 focused contracts for adapter consolidation + 23 route extraction.

Test IDs: T500-T529（Wave 3-N.7 Batch 3 主线 A · Backend Architect subagent）

契约覆盖（30 项）：
- T500-T522: 23 抽出路由 path/method 存在于 openapi
- T523: 路由顺序敏感 — `/api/workflows` vs `/api/workflows/{name:path}`
- T524: include_router 装配齐全（comfyui 追加 2 路由）
- T525: include_router 装配齐全（workflows 追加 6 路由）
- T526: router 文件不 import main（AST 穿透验证）
- T527: adapter 文件不 import main
- T528: P0 sentinel sweep — 关键路由参数含 api_key 断言 0 leak
- T529: 23 路由各注册恰好一次
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
ADAPTER_DIR = ROOT / "app" / "adapters" / "task"


# ---------------------------------------------------------------------------
# Route inventory - 23 routes
# ---------------------------------------------------------------------------

PR_BE_11_ROUTES: set[tuple[str, str]] = {
    # update.py (6)
    ("GET", "/api/update-connectivity/probe"),
    ("GET", "/api/update-connectivity"),
    ("GET", "/api/check-update"),
    ("POST", "/api/update-from-github"),
    ("GET", "/api/update-backups"),
    ("POST", "/api/update-rollback"),
    # comfyui.py (2追加)
    ("POST", "/api/comfyui/upload-base64"),
    ("PUT", "/api/comfyui/instances"),
    # conversations.py (7)
    ("GET", "/api/conversations"),
    ("POST", "/api/conversations"),
    ("GET", "/api/conversations/{conversation_id}"),
    ("DELETE", "/api/conversations/{conversation_id}"),
    ("POST", "/api/chat"),
    ("POST", "/api/chat/agent"),
    ("POST", "/api/chat/stream"),
    # angle.py (2)
    ("POST", "/api/angle/poll_status"),
    ("POST", "/api/angle/generate"),
    # workflows.py (6追加)
    ("GET", "/api/config/token"),
    ("GET", "/api/workflows/{name:path}"),
    ("POST", "/api/workflows"),
    ("PUT", "/api/workflows/{name:path}/config"),
    ("DELETE", "/api/workflows/{name:path}"),
    ("POST", "/api/workflows/{name:path}/run"),
}

# 路由顺序敏感对：静态路径必须在参数化路径之前 include
# `/api/workflows`（静态）vs `/api/workflows/{name:path}`（参数化）
PR_BE_11_ORDERED_PATHS = [
    "/api/workflows",
    "/api/workflows/{name:path}",
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


def _router_paths_in_order() -> list[str]:
    """Return [path, ...] for GET /api/workflows* routes in registration order."""
    import main  # noqa: F811

    paths: list[str] = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            if route.path.startswith("/api/workflows"):
                if "GET" in route.methods:
                    paths.append(route.path)
    return paths


# ---------------------------------------------------------------------------
# T500-T522 — 23 routes present in openapi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, path", sorted(PR_BE_11_ROUTES),
    ids=[f"{m.lower()}_{p.replace('/', '_')}" for m, p in sorted(PR_BE_11_ROUTES)],
)
def test_t500_t522_pr_be_11_route_present(method: str, path: str) -> None:
    """T500-T522 · 各抽出路由的 path/method 存在于 openapi 中。"""
    routes = _application_routes()
    assert (path, method.upper()) in routes, (
        f"PR-BE-11 路由 {method} {path} 未在 openapi 中注册"
    )


# ---------------------------------------------------------------------------
# T523 — 路由顺序敏感 `/api/workflows` vs `/api/workflows/{name:path}`
# ---------------------------------------------------------------------------


def test_t523_workflows_route_order() -> None:
    """T523 · `/api/workflows`（静态）注册顺序优先于 `/api/workflows/{name:path}`（参数化）。

    由于 FastAPI 按注册顺序匹配路由，静态路径必须在参数化路径之前注册，
    否则 `/api/workflows` 请求可能被参数化路径错误匹配。
    """
    paths = _router_paths_in_order()
    filtered = [p for p in paths if p in PR_BE_11_ORDERED_PATHS]
    assert len(filtered) >= 2, (
        f"期望至少 2 条 workflows GET 路由，实际 {len(filtered)}: {filtered}"
    )
    # `/api/workflows` 必须在 `/api/workflows/{name:path}` 之前
    static_idx = filtered.index("/api/workflows")
    param_idx = filtered.index("/api/workflows/{name:path}")
    assert static_idx < param_idx, (
        f"路由顺序违反：`/api/workflows`(index={static_idx}) 应在 "
        f"`/api/workflows/{'{name:path}'}`(index={param_idx}) 之前"
    )


# ---------------------------------------------------------------------------
# T524 — include_router 装配齐全（comfyui 追加 2 路由）
# ---------------------------------------------------------------------------


def test_t524_comfyui_extended_routes_registered() -> None:
    """T524 · comfyui router 追加的 2 路由（upload-base64 / save instances）已注册。"""
    routes = _application_routes()
    comfyui_new = {
        ("/api/comfyui/upload-base64", "POST"),
        ("/api/comfyui/instances", "PUT"),
    }
    for path, method in comfyui_new:
        assert (path, method) in routes, (
            f"comfyui 追加路由 {method} {path} 未注册"
        )


# ---------------------------------------------------------------------------
# T525 — include_router 装配齐全（workflows 追加 6 路由）
# ---------------------------------------------------------------------------


def test_t525_workflows_extended_routes_registered() -> None:
    """T525 · workflows router 追加的 6 路由已注册。"""
    routes = _application_routes()
    workflows_new = {
        ("/api/config/token", "GET"),
        ("/api/workflows/{name:path}", "GET"),
        ("/api/workflows", "POST"),
        ("/api/workflows/{name:path}/config", "PUT"),
        ("/api/workflows/{name:path}", "DELETE"),
        ("/api/workflows/{name:path}/run", "POST"),
    }
    for path, method in workflows_new:
        assert (path, method) in routes, (
            f"workflows 追加路由 {method} {path} 未注册"
        )


# ---------------------------------------------------------------------------
# T526 — router 文件不 import main（AST 穿透验证）
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
            if node.module == "main" or (node.module and node.module.startswith("main.")):
                pytest.fail(
                    f"{label} AST 中发现 from main import: {ast.dump(node)}"
                )


NEW_ROUTER_FILES = [
    "update.py",
    "conversations.py",
    "angle.py",
]


def test_t526_router_files_do_not_import_main() -> None:
    """T526 · 新 router 文件不 import main（AST 穿透验证）。"""
    for fname in NEW_ROUTER_FILES:
        fpath = ROUTER_DIR / fname
        if fpath.exists():
            _check_file_imports_main(fpath, fname)


# ---------------------------------------------------------------------------
# T527 — adapter 文件不 import main
# ---------------------------------------------------------------------------


def test_t527_adapter_files_do_not_import_main() -> None:
    """T527 · adapter 文件不 import main（AST 穿透验证）。"""
    if ADAPTER_DIR.exists():
        for pyfile in sorted(ADAPTER_DIR.glob("*.py")):
            _check_file_imports_main(pyfile, pyfile.name)


# ---------------------------------------------------------------------------
# T528 — P0 sentinel sweep: 关键路由参数含 api_key 断言 0 leak
# ---------------------------------------------------------------------------

_SECRET_SENTINELS = (
    "sk-",
    "api_key",
    "api-key",
    "authorization",
    "Authorization",
    "Bearer ",
    "password",
    "credential",
    "token",
    "secret",
    "private_key",
    "api_secret",
)


def test_t528_p0_sentinel_sweep() -> None:
    """T528 · P0 密钥零入库 sentinel sweep。

    angle 和 chat 路由中涉及 api_key 参数，本测试确保 router 文件源码中
    sentinel 关键字的出现仅来自 import 路径或安全引用，而非实际密钥字面量。
    """
    for fname in NEW_ROUTER_FILES:
        fpath = ROUTER_DIR / fname
        if not fpath.exists():
            continue
        source = fpath.read_text(encoding="utf-8")
        lines = source.splitlines()
        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()
            # 跳过注释和空行
            if not stripped or stripped.startswith("#"):
                continue
            for sentinel in _SECRET_SENTINELS:
                if sentinel in stripped:
                    # 仅在字符串字面量中检查（排除 import 路径中的 token）
                    if '"' in stripped or "'" in stripped:
                        # 排除 import 语句
                        if "import" in stripped:
                            continue
                        pytest.fail(
                            f"P0 密钥零入库违反 · {fname}:{lineno} 出现 "
                            f"sentinel `{sentinel}`: {stripped}"
                        )


# ---------------------------------------------------------------------------
# T529 — 23 路由各注册恰好一次
# ---------------------------------------------------------------------------


def test_t529_all_23_routes_registered_exactly_once() -> None:
    """T529 · 23 抽出路由各注册恰好一次。"""
    routes = _application_routes()
    for method, path in PR_BE_11_ROUTES:
        count = routes.count((path, method.upper()))
        assert count == 1, (
            f"路由 {method} {path} 注册次数异常：期望 1，实际 {count}"
        )