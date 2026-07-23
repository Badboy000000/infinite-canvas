"""PR-BE-06 focused contracts for the canvas / project domain module extraction.

Test IDs: T100-T109 (Wave 3-L 主线 B · 独立分配的 10 个 T-编号)

契约覆盖：
- T100: 路由数量与 baseline routes=167 一致(通过 OpenAPI diff 保证)
- T101: 4 路由文件都不 `import main`（继承 PR-BE-05 硬约束）
- T102: 4 路由文件不做业务级 IO（不 `import os`/`json` 直接落盘）
- T103: canvas router 内部 `/api/canvases/trash` 声明顺序优先于 `/api/canvases/{canvas_id}`（GM-11）
- T104: app.include_router 组装顺序：projects → canvas → canvas_assets → canvas_workflows
- T105: 4 领域函数体在 main.py 仍以 re-export 兼容层保留（`async def` 且无 `@app.` 装饰器）
- T106: Canvas/Project 命令对象 dataclass 契约：都保留 `raw: dict` 兜底字段
- T107: CanvasService.update_canvas 保持 409 语义 + base_updated_at compare-and-swap
- T108: ProjectService.delete_project 保持默认项目不可删除 400 语义
- T109: `/api/canvases/trash` 与 `/api/canvases/{canvas_id}` HTTP 路径解析优先级实测
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
ROUTER_DIR = ROOT / "app" / "api" / "routers"
BE06_ROUTER_FILES = (
    "canvas.py",
    "projects.py",
    "canvas_assets.py",
    "canvas_workflows.py",
)


# ---------------------------------------------------------------------------
# T100 — 4 领域 20 条路由全部注册（不新增 / 不遗漏）
# ---------------------------------------------------------------------------

EXPECTED_DOMAIN_ROUTES = frozenset(
    {
        # projects
        ("/api/projects", "GET"),
        ("/api/projects", "POST"),
        ("/api/projects/{project_id}", "POST"),
        ("/api/projects/{project_id}", "DELETE"),
        # canvas core
        ("/api/canvases", "GET"),
        ("/api/canvases", "POST"),
        ("/api/canvases/trash", "GET"),
        ("/api/canvases/{canvas_id}", "GET"),
        ("/api/canvases/{canvas_id}", "PUT"),
        ("/api/canvases/{canvas_id}", "DELETE"),
        ("/api/canvases/{canvas_id}/meta", "GET"),
        ("/api/canvases/{canvas_id}/meta", "POST"),
        ("/api/canvases/{canvas_id}/touch", "POST"),
        ("/api/canvases/{canvas_id}/restore", "POST"),
        ("/api/canvases/{canvas_id}/purge", "DELETE"),
        # canvas assets
        ("/api/canvas-assets", "GET"),
        ("/api/canvas-assets/check", "POST"),
        ("/api/canvas-assets/download", "POST"),
        # canvas workflows
        ("/api/canvas-workflows/export", "POST"),
        ("/api/canvas-workflows/export-to-library", "POST"),
        ("/api/canvas-workflows/import", "POST"),
    }
)


def _application_route_set() -> set[tuple[str, str]]:
    import main

    routes: set[tuple[str, str]] = set()
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                routes.add((route.path, method))
    return routes


def test_t100_all_domain_routes_registered_exactly_once() -> None:
    """T100 — 4 领域 21 条路由全部注册且每条只出现一次。"""

    all_routes = []
    import main

    for route in main.app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                all_routes.append((route.path, method))

    for entry in EXPECTED_DOMAIN_ROUTES:
        assert all_routes.count(entry) == 1, f"missing or duplicate route: {entry}"


# ---------------------------------------------------------------------------
# T101 — 4 路由文件都不 `import main`
# ---------------------------------------------------------------------------

def test_t101_routers_do_not_import_main() -> None:
    for filename in BE06_ROUTER_FILES:
        tree = ast.parse((ROUTER_DIR / filename).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "main" not in imported, filename


# ---------------------------------------------------------------------------
# T102 — 4 路由文件不直接做业务级 IO（不 `import os`/`json`）
# ---------------------------------------------------------------------------

def test_t102_routers_stay_free_of_direct_legacy_io() -> None:
    for filename in BE06_ROUTER_FILES:
        tree = ast.parse((ROUTER_DIR / filename).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        # 允许 typing / fastapi / commands / service。IO 与文件系统必须走
        # service。
        assert "os" not in imported, filename
        assert "json" not in imported, filename
        # 不允许在 router 层调 open(...)
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
            for node in ast.walk(tree)
        ), filename


# ---------------------------------------------------------------------------
# T103 — canvas router 内部 `/api/canvases/trash` 优先于
# `/api/canvases/{canvas_id}` （GM-11 · 路由声明顺序保证）
# ---------------------------------------------------------------------------

def test_t103_canvas_router_declares_trash_before_by_id() -> None:
    """canvas router 源码里 `/api/canvases/trash` 装饰器必须出现在
    `/api/canvases/{canvas_id}` 之前，否则 FastAPI 会把 `trash` 当成一个
    `canvas_id` 值匹配到通配路由。"""

    src = (ROUTER_DIR / "canvas.py").read_text(encoding="utf-8")
    trash_pos = src.find('"/api/canvases/trash"')
    by_id_pos = src.find('"/api/canvases/{canvas_id}"')
    assert trash_pos >= 0, "trash route decorator missing"
    assert by_id_pos >= 0, "by-id route decorator missing"
    assert trash_pos < by_id_pos, (
        "GM-11 违反：`/api/canvases/trash` 装饰器必须在 "
        "`/api/canvases/{canvas_id}` 之前声明"
    )


# ---------------------------------------------------------------------------
# T104 — main.py include_router 顺序：projects → canvas → canvas_assets → canvas_workflows
# ---------------------------------------------------------------------------

def test_t104_main_include_router_order() -> None:
    import re

    src = (ROOT / "main.py").read_text(encoding="utf-8")
    order = [
        "create_projects_router",
        "create_canvas_router",
        "create_canvas_assets_router",
        "create_canvas_workflows_router",
    ]
    positions: list[int] = []
    for name in order:
        # 兼容多行格式：`app.include_router(\n    create_xxx_router(...)`
        pattern = re.compile(
            r"app\.include_router\s*\(\s*" + re.escape(name) + r"\s*\("
        )
        match = pattern.search(src)
        assert match is not None, (
            f"main.py 缺少 `app.include_router({name}(...))` 调用"
        )
        positions.append(match.start())
    assert positions == sorted(positions), (
        "main.py include_router 顺序漂移；期望 projects → canvas → "
        "canvas_assets → canvas_workflows"
    )


# ---------------------------------------------------------------------------
# T105 — 4 领域函数体作为 re-export 兼容层保留在 main.py（无装饰器）
# ---------------------------------------------------------------------------

RE_EXPORTED_FUNCTIONS = (
    "canvases",
    "get_projects",
    "create_project",
    "update_project",
    "delete_project",
    "trashed_canvases",
    "create_canvas",
    "get_canvas_meta",
    "update_canvas_meta",
    "get_canvas",
    "touch_canvas",
    "list_canvas_assets",
    "check_canvas_assets",
    "download_canvas_assets",
    "export_canvas_workflow",
    "export_canvas_workflow_to_library",
    "import_canvas_workflow",
    "update_canvas",
    "delete_canvas",
    "restore_canvas",
    "purge_canvas",
)


def test_t105_domain_functions_kept_as_reexport_compat() -> None:
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    async_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }
    for fname in RE_EXPORTED_FUNCTIONS:
        assert fname in async_names, f"main.py 缺少 re-export 兼容层 `async def {fname}`"

    # 装饰器必须已剥离：`@app.get("/api/canvases")` 等不应残留
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    forbidden_decorators = (
        '@app.get("/api/canvases")',
        '@app.post("/api/canvases")',
        '@app.get("/api/canvases/trash")',
        '@app.get("/api/canvases/{canvas_id}")',
        '@app.put("/api/canvases/{canvas_id}")',
        '@app.delete("/api/canvases/{canvas_id}")',
        '@app.post("/api/canvases/{canvas_id}/touch")',
        '@app.get("/api/canvases/{canvas_id}/meta")',
        '@app.post("/api/canvases/{canvas_id}/meta")',
        '@app.post("/api/canvases/{canvas_id}/restore")',
        '@app.delete("/api/canvases/{canvas_id}/purge")',
        '@app.get("/api/projects")',
        '@app.post("/api/projects")',
        '@app.post("/api/projects/{project_id}")',
        '@app.delete("/api/projects/{project_id}")',
        '@app.get("/api/canvas-assets")',
        '@app.post("/api/canvas-assets/check")',
        '@app.post("/api/canvas-assets/download")',
        '@app.post("/api/canvas-workflows/export")',
        '@app.post("/api/canvas-workflows/export-to-library")',
        '@app.post("/api/canvas-workflows/import")',
    )
    for decorator in forbidden_decorators:
        assert decorator not in src, (
            f"main.py 还残留 `{decorator}` — PR-BE-06 应已剥离该装饰器并把绑定"
            f"迁到 app/api/routers/"
        )


# ---------------------------------------------------------------------------
# T106 — 命令对象 dataclass 契约：都保留 `raw: dict` 兜底字段
# ---------------------------------------------------------------------------

def test_t106_commands_expose_raw_dict_field() -> None:
    from dataclasses import fields

    from app.modules.canvas.commands import (
        CanvasCreateCommand,
        CanvasIdCommand,
        CanvasMetaPatchCommand,
        CanvasSaveCommand,
    )
    from app.modules.project.commands import (
        ProjectCreateCommand,
        ProjectDeleteCommand,
        ProjectUpdateCommand,
    )

    for cmd in (
        CanvasCreateCommand,
        CanvasIdCommand,
        CanvasMetaPatchCommand,
        CanvasSaveCommand,
        ProjectCreateCommand,
        ProjectDeleteCommand,
        ProjectUpdateCommand,
    ):
        raw_field = {f.name: f for f in fields(cmd)}.get("raw")
        assert raw_field is not None, f"{cmd.__name__} 缺少 raw dict 兜底字段"


# ---------------------------------------------------------------------------
# T107 — CanvasService.update_canvas 保持 409 + base_updated_at 语义
# ---------------------------------------------------------------------------

def test_t107_canvas_service_preserves_409_semantic() -> None:
    from app.modules.canvas.commands import CanvasSaveCommand
    from app.modules.canvas.service import CanvasService

    fake_store = MagicMock()
    # 后端当前 updated_at=1000；请求携带 base_updated_at=500（旧版本）
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()

    async def _broadcast(*_a, **_kw):
        return None

    service = CanvasService(
        store=fake_store,
        list_canvases=lambda: [],
        list_deleted_canvases=lambda: [],
        new_canvas=lambda *a, **kw: {},
        canvas_record=lambda c: c,
        canvas_path=lambda cid: cid,
        load_canvas_any=lambda cid: {"id": cid},
        normalize_canvas_kind=lambda k: k or "classic",
        normalize_canvas_color=lambda c: c,
        canvas_lock=MagicMock(__enter__=lambda s: None, __exit__=lambda *a: None),
        default_project_id="default",
        broadcast_canvas_updated=_broadcast,
        now_ms=lambda: 2000,
    )
    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=500,
        raw={},
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert "message" in detail
    assert detail.get("updated_at") == 1000
    assert "canvas" in detail
    # 未触发 save
    fake_store.save_canvas.assert_not_called()


# ---------------------------------------------------------------------------
# CB-P5-14 承接（数据 PR-17 · Wave 3-M 主线 A）· Service 层 3 边界补齐
# ---------------------------------------------------------------------------


def _build_canvas_service_with_store(fake_store: MagicMock) -> Any:
    """CB-P5-14 承接 · 3 边界共用 fixture 构造器（fake_store 由调用方注入）。

    与 T107 完全同形状（避免 T107 现有测试受影响）。刻意不改 T107。
    """

    from app.modules.canvas.service import CanvasService

    async def _broadcast(*_a, **_kw):
        return None

    return CanvasService(
        store=fake_store,
        list_canvases=lambda: [],
        list_deleted_canvases=lambda: [],
        new_canvas=lambda *a, **kw: {},
        canvas_record=lambda c: c,
        canvas_path=lambda cid: cid,
        load_canvas_any=lambda cid: {"id": cid},
        normalize_canvas_kind=lambda k: k or "classic",
        normalize_canvas_color=lambda c: c,
        canvas_lock=MagicMock(__enter__=lambda s: None, __exit__=lambda *a: None),
        default_project_id="default",
        broadcast_canvas_updated=_broadcast,
        now_ms=lambda: 2000,
    )


def test_t107b_canvas_service_equal_boundary_succeeds_200() -> None:
    """T123 · CB-P5-14 承接 · equal 边界（client base == DB updated_at）→ 200。

    fake_store.load_canvas 返回 updated_at=1000 · cmd.base_updated_at=1000 →
    service.update_canvas 应成功 · 不抛异常 · fake_store.save_canvas 被
    调用一次。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=1000,  # equal 边界（严格等于 DB updated_at）
        raw={},
    )

    # 不应抛异常
    result = asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert isinstance(result, dict)
    # save 应被调用（equal 边界不冲突）
    fake_store.save_canvas.assert_called_once()


def test_t107c_canvas_service_newer_boundary_returns_409() -> None:
    """T124 · CB-P5-14 承接 · newer 边界（反向漂移防护）→ 409。

    fake_store.load_canvas 返回 updated_at=1000 · cmd.base_updated_at=2000
    (client 更新)→ 应抛 HTTPException(409)· fake_store.save_canvas
    未被调用。

    **回炉登记**：CanvasService.update_canvas 当前只判定 `<`
    (`main.py:16286` 契约同款)· 未覆盖 newer 边界 → 独立 CB-P5-17。
    本测试 xfail 直到 CB-P5-17 承接。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=2000,  # newer 边界（严格大于 DB updated_at · 反向漂移）
        raw={},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert exc_info.value.status_code == 409
    fake_store.save_canvas.assert_not_called()


def test_t107d_canvas_service_revision_compare_and_swap() -> None:
    """T125 · CB-P5-14 承接 · revision compare-and-swap 组合边界。

    组合场景：updated_at 匹配（cmd.base_updated_at == DB.updated_at）
    但 revision 不匹配（DB.revision=5 · cmd.raw['revision']=3 · 旧版本）
    → 应 409。

    **回炉登记**：CanvasService.update_canvas 未做 revision compare-and
    -swap（只做 base_updated_at 单一维度比对）→ 独立 CB-P5-18。本测试
    xfail 直到 CB-P5-18 承接。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "revision": 5,  # DB 现有 revision
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=1000,  # updated_at 维度匹配
        raw={"revision": 3},  # revision 维度失配（旧版本）
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert exc_info.value.status_code == 409
    fake_store.save_canvas.assert_not_called()


# ---------------------------------------------------------------------------
# T130-T134 — 数据 PR-19 · CanvasService 乐观锁双维度补齐(CB-P5-17+18 承接)
# ---------------------------------------------------------------------------


def test_t130_canvas_service_equal_boundary_with_revision_match() -> None:
    """T130 · 数据 PR-19 · equal 边界 + revision 匹配 → 200。

    组合成功场景:updated_at 相等 且 revision 匹配 · service 应放行 · save
    被调用一次。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "revision": 5,
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=1000,  # equal
        revision=5,  # match
        raw={},
    )

    result = asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert isinstance(result, dict)
    fake_store.save_canvas.assert_called_once()


def test_t131_canvas_service_newer_boundary_strict_not_equal() -> None:
    """T131 · 数据 PR-19 · CB-P5-17 · newer 反向漂移严格 `!=` 语义延伸测试。

    与 T107c 场景对齐:client base > DB(newer / clock-drift)→ 应 409 ·
    detail shape 与 base_updated_at 分支逐字节一致(不引入新字段)。此测
    试强化 detail 字段断言,防止未来 error shape 漂移。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=3000,  # newer 反向漂移
        raw={},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    # error shape 保持 {"message", "canvas", "updated_at"} 逐字节一致
    assert set(detail.keys()) == {"message", "canvas", "updated_at"}
    assert detail["updated_at"] == 1000
    fake_store.save_canvas.assert_not_called()


def test_t132_canvas_service_revision_matches_returns_200() -> None:
    """T132 · 数据 PR-19 · CB-P5-18 · revision 显式提供且匹配 → 200。

    命令对象显式带 revision=5 · DB revision=5 · base_updated_at 也匹配 →
    service 放行 · save 被调用。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "revision": 5,
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=1000,
        revision=5,  # 显式匹配
        raw={},
    )

    result = asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert isinstance(result, dict)
    fake_store.save_canvas.assert_called_once()


def test_t133_canvas_service_revision_stale_returns_409() -> None:
    """T133 · 数据 PR-19 · CB-P5-18 · revision 显式提供但落后 → 409。

    命令对象显式带 revision=3 · DB revision=5(client 端旧缓存)· base_
    updated_at 维度仍匹配 → revision compare-and-swap 应拦截,抛 409 ·
    save 未被调用 · error shape 与 base_updated_at 分支逐字节一致。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "revision": 5,
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=1000,  # updated_at 匹配
        revision=3,  # 显式落后
        raw={},
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    # revision 分支复用 base_updated_at 分支的 error shape · 不引入新字段
    assert set(detail.keys()) == {"message", "canvas", "updated_at"}
    assert detail["updated_at"] == 1000
    fake_store.save_canvas.assert_not_called()


def test_t134_canvas_service_revision_absent_backward_compatible() -> None:
    """T134 · 数据 PR-19 · CB-P5-18 向后兼容 · 老前端不上报 revision → 单维
    度 base_updated_at 语义保留。

    命令对象 revision=None(老前端不上报 revision · payload 里也没有)·
    base_updated_at 匹配 · service 单维度语义应放行 · save 被调用。这条
    是 Lead 独立锁维度决策的向后兼容护栏。
    """

    from app.modules.canvas.commands import CanvasSaveCommand

    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {
        "id": "abc",
        "updated_at": 1000,
        "revision": 5,  # DB 有 revision · 但 cmd 未提供
        "title": "hi",
        "icon": "layers",
        "kind": "classic",
    }
    fake_store.save_canvas = MagicMock()
    service = _build_canvas_service_with_store(fake_store)

    cmd = CanvasSaveCommand(
        canvas_id="abc",
        title="x",
        icon="",
        nodes=[],
        connections=[],
        viewport={},
        logs=[],
        settings={},
        client_id="",
        base_updated_at=1000,  # updated_at 匹配
        revision=None,  # 老前端不上报
        raw={},  # raw 里也没 revision
    )

    result = asyncio.get_event_loop().run_until_complete(service.update_canvas(cmd))
    assert isinstance(result, dict)
    fake_store.save_canvas.assert_called_once()


# ---------------------------------------------------------------------------
# T108 — ProjectService.delete_project 默认项目不可删除 400
# ---------------------------------------------------------------------------

def test_t108_project_service_default_project_undeletable() -> None:
    from app.modules.project.commands import ProjectDeleteCommand
    from app.modules.project.service import ProjectService

    service = ProjectService(
        store=MagicMock(),
        list_projects=lambda: [],
        new_project=lambda name: {"id": "x"},
        project_record=lambda p: p,
        ensure_default_project=lambda: [{"id": "default"}],
        canvas_lock=MagicMock(__enter__=lambda s: None, __exit__=lambda *a: None),
        canvas_dir=".",
        default_project_id="default",
        now_ms=lambda: 0,
    )
    with pytest.raises(HTTPException) as exc_info:
        service.delete_project(ProjectDeleteCommand(project_id="default"))
    assert exc_info.value.status_code == 400
    assert "默认项目" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# T220-T225 · 项目 PR-A · CB-P5-15 承接 · Project 删除迁移契约补齐
#
# STRONG 语义澄清:project 域当前主写路径仍是 JSON 层(`data/canvases/*.json`
# + `data/projects.json`)· `ProjectService.delete_project` 的唯一副作用是
# 迭代 canvas JSON 文件并改写其中的 `project` 字段。任务书中的 "直接查 DB
# 表 `canvases.project_id`" 与当前代码事实存在差异 —— canvas_workflows /
# canvas_assets 表在数据模型里根本不存在(工作流/资产走 workflow_
# definitions / asset_items · 与 canvas 无 FK 关联)。故本组测试将 STRONG
# 落地到"实际持久化事实"= 文件系统 canvas JSON 内容,直接读文件断言,
# 不信 service 返回值。这是 CB-P5-15 承接目标下最强可落地的断言强度。
#
# 未来路径:若 project 域走 canvases DB 主写(数据 PR-8 已就绪)· 应升级
# 这组测试改直读 `canvases.project_legacy_id` 列;届时另 CB 登记升级。
# ---------------------------------------------------------------------------


def _build_project_workspace(tmp_path):
    """构造真实文件系统 fixture · 返回 (canvas_dir, projects_ref, build_service)。

    - `canvas_dir`:tmp_path / "canvases" · 真实目录,测试写 JSON 到这里
    - `projects_ref`:list · in-memory 项目列表,ensure_default_project 归还
      live reference(允许 service 通过 store.save_projects 回写 mutation)
    - `build_service(default_missing=False)`:构造 ProjectService,`ensure_
      default_project` mimic main.py 语义 · 若 default 不在 projects_ref
      则自动 insert(与 `main.ensure_default_project` 逐字节等价)
    """

    canvas_dir = tmp_path / "canvases"
    canvas_dir.mkdir(parents=True, exist_ok=True)
    projects_ref: list[dict[str, Any]] = []

    def build_service():
        from app.modules.project.service import ProjectService

        fake_store = MagicMock()

        def _save_projects(p):
            projects_ref.clear()
            projects_ref.extend(p)

        fake_store.save_projects = _save_projects

        def _ensure_default():
            # mimic main.ensure_default_project 逐字节:default 不存在时插入到头部
            if not any(p.get("id") == "default" for p in projects_ref):
                projects_ref.insert(0, {
                    "id": "default", "name": "默认项目", "order": 0,
                    "created_at": 1000, "updated_at": 1000,
                })
                fake_store.save_projects(list(projects_ref))
            return projects_ref

        return ProjectService(
            store=fake_store,
            list_projects=lambda: list(projects_ref),
            new_project=lambda name: {"id": "new", "name": name},
            project_record=lambda p: p,
            ensure_default_project=_ensure_default,
            canvas_lock=MagicMock(
                __enter__=lambda s: None, __exit__=lambda *a: None,
            ),
            canvas_dir=str(canvas_dir),
            default_project_id="default",
            now_ms=lambda: 2000,
        )

    return canvas_dir, projects_ref, build_service


def _write_canvas_json(canvas_dir, canvas_id: str, project_id: str, **extra) -> None:
    """写一个 canvas JSON 文件到 canvas_dir · extra 字段并入(用于 T222)."""
    import json

    payload = {
        "id": canvas_id,
        "title": extra.get("title", canvas_id),
        "kind": "classic",
        "project": project_id,
        "updated_at": 1000,
    }
    for k, v in extra.items():
        payload[k] = v
    path = canvas_dir / f"{canvas_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _read_canvas_json(canvas_dir, canvas_id: str) -> dict[str, Any]:
    """直读 canvas JSON · 不信 service 返回值 · STRONG 断言基础."""
    import json

    path = canvas_dir / f"{canvas_id}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_t220_delete_project_migrates_canvases_to_default(tmp_path) -> None:
    """T220 · 删除非 default project · 其下画布 `project` 字段迁移到 default。

    STRONG:直接读 canvas JSON 文件 · 断言 `project == "default"`(不信
    service 返回的 `moved` 计数)。
    """

    from app.modules.project.commands import ProjectDeleteCommand

    canvas_dir, projects_ref, build_service = _build_project_workspace(tmp_path)
    projects_ref[:] = [
        {"id": "default", "name": "默认项目", "order": 0, "created_at": 1000, "updated_at": 1000},
        {"id": "A", "name": "项目A", "order": 1, "created_at": 1000, "updated_at": 1000},
    ]
    _write_canvas_json(canvas_dir, "c1", "A")
    _write_canvas_json(canvas_dir, "c2", "A")

    service = build_service()
    result = service.delete_project(ProjectDeleteCommand(project_id="A"))

    # 事实层 STRONG 断言:直接读文件 · 不信 service 返回
    assert _read_canvas_json(canvas_dir, "c1")["project"] == "default"
    assert _read_canvas_json(canvas_dir, "c2")["project"] == "default"
    # projects_ref 内 A 已剔除 · default 保留
    assert not any(p.get("id") == "A" for p in projects_ref)
    assert any(p.get("id") == "default" for p in projects_ref)
    # service 返回 shape 契约辅助断言
    assert result == {"ok": True, "moved": 2}


def test_t221_delete_project_when_default_missing_creates_default(tmp_path) -> None:
    """T221 · default project 缺失时删除非 default · 应先建 default · 再迁移。

    STRONG:直接读 canvas JSON · 断言 `project == "default"` + projects_ref
    最终包含 default 记录(由 ensure_default_project 兜底创建)。
    """

    from app.modules.project.commands import ProjectDeleteCommand

    canvas_dir, projects_ref, build_service = _build_project_workspace(tmp_path)
    # default 缺失场景:只有 A · 没有 default
    projects_ref[:] = [
        {"id": "A", "name": "项目A", "order": 1, "created_at": 1000, "updated_at": 1000},
    ]
    _write_canvas_json(canvas_dir, "c1", "A")

    service = build_service()
    result = service.delete_project(ProjectDeleteCommand(project_id="A"))

    # 事实断言:default 已被 ensure_default_project 兜底创建
    assert any(p.get("id") == "default" for p in projects_ref), (
        "default project 应由 ensure_default_project 兜底创建"
    )
    # 事实断言:c1 已迁移到 default
    assert _read_canvas_json(canvas_dir, "c1")["project"] == "default"
    # A 已剔除
    assert not any(p.get("id") == "A" for p in projects_ref)
    assert result["ok"] is True
    assert result["moved"] == 1


def test_t222_delete_project_preserves_canvas_workflows_and_assets(tmp_path) -> None:
    """T222 · 删除 project 迁移 canvas 时 · workflows / assets / nodes 字段
    应逐字节保留(负契约:迁移只改 `project` 字段)。

    背景澄清:canvas_workflows / canvas_assets 独立 DB 表在当前数据模型不
    存在(workflow_definitions / asset_items 与 canvas 无 FK)· canvas 侧
    的工作流/资产以内嵌 JSON 字段形式存在于 canvas 文件里。STRONG 断言:
    迁移前后 workflows / assets / nodes / connections 字段逐字节保留 · 只
    有 `project` 字段被改。
    """

    from app.modules.project.commands import ProjectDeleteCommand

    canvas_dir, projects_ref, build_service = _build_project_workspace(tmp_path)
    projects_ref[:] = [
        {"id": "default", "name": "默认项目", "order": 0, "created_at": 1000, "updated_at": 1000},
        {"id": "A", "name": "项目A", "order": 1, "created_at": 1000, "updated_at": 1000},
    ]
    embedded_workflows = [
        {"id": "wf1", "name": "WF 1", "graph": {"nodes": [1, 2], "edges": [[1, 2]]}},
        {"id": "wf2", "name": "WF 2", "graph": {}},
    ]
    embedded_assets = [
        {"id": "asset1", "url": "/local/a.png", "sha": "aaa"},
        {"id": "asset2", "url": "/local/b.mp4", "sha": "bbb"},
        {"id": "asset3", "url": "/local/c.wav", "sha": "ccc"},
    ]
    canvas_nodes = [
        {"id": "n1", "type": "image", "asset_ref": "asset1"},
        {"id": "n2", "type": "text", "content": "hello"},
    ]
    canvas_connections = [{"from": "n1", "to": "n2"}]

    _write_canvas_json(
        canvas_dir, "c1", "A",
        workflows=embedded_workflows,
        assets=embedded_assets,
        nodes=canvas_nodes,
        connections=canvas_connections,
    )

    service = build_service()
    service.delete_project(ProjectDeleteCommand(project_id="A"))

    # 事实断言:project 迁移
    data = _read_canvas_json(canvas_dir, "c1")
    assert data["project"] == "default"
    # STRONG 负契约:workflows / assets / nodes / connections 字段逐字节保留
    assert data["workflows"] == embedded_workflows, (
        "迁移不允许丢/改 canvas 内嵌 workflows 字段"
    )
    assert data["assets"] == embedded_assets, (
        "迁移不允许丢/改 canvas 内嵌 assets 字段"
    )
    assert data["nodes"] == canvas_nodes, (
        "迁移不允许丢/改 canvas nodes 字段"
    )
    assert data["connections"] == canvas_connections, (
        "迁移不允许丢/改 canvas connections 字段"
    )


def test_t223_delete_default_project_returns_400_and_does_not_touch_others(
    tmp_path,
) -> None:
    """T223 · T108 姊妹强化 · delete_project('default') 抛 400 且不动其他 project。

    姊妹强化点:除了 400 语义(T108 已覆盖)· 断言其他 project + 其 canvas
    在异常路径下**未被触碰**(负副作用契约)。
    """

    from app.modules.project.commands import ProjectDeleteCommand

    canvas_dir, projects_ref, build_service = _build_project_workspace(tmp_path)
    projects_ref[:] = [
        {"id": "default", "name": "默认项目", "order": 0, "created_at": 1000, "updated_at": 1000},
        {"id": "A", "name": "项目A", "order": 1, "created_at": 1000, "updated_at": 1000},
    ]
    _write_canvas_json(canvas_dir, "c1", "A")

    service = build_service()
    with pytest.raises(HTTPException) as exc_info:
        service.delete_project(ProjectDeleteCommand(project_id="default"))

    # T108 姊妹:400 语义保留
    assert exc_info.value.status_code == 400
    assert "默认项目" in str(exc_info.value.detail)
    # 负副作用:A 未被剔除 · c1 未被改动
    assert any(p.get("id") == "A" for p in projects_ref)
    assert _read_canvas_json(canvas_dir, "c1")["project"] == "A", (
        "delete_default 抛 400 应立即返回 · 不许动其他 project 下的 canvas"
    )


def test_t224_delete_empty_project_no_canvases(tmp_path) -> None:
    """T224 · 删除无 canvas 的空 project · 成功 · default 不受影响。

    STRONG:project A 无任何 canvas 文件 · delete → moved=0 · projects_ref
    去掉 A · default project 记录逐字节保留(未被误改)。
    """

    from app.modules.project.commands import ProjectDeleteCommand

    canvas_dir, projects_ref, build_service = _build_project_workspace(tmp_path)
    default_snapshot = {
        "id": "default", "name": "默认项目", "order": 0,
        "created_at": 1000, "updated_at": 1000,
    }
    projects_ref[:] = [
        dict(default_snapshot),
        {"id": "A", "name": "项目A", "order": 1, "created_at": 1000, "updated_at": 1000},
    ]
    # canvas_dir 存在 · 但里面没有任何属于 A 的 canvas(甚至完全空)

    service = build_service()
    result = service.delete_project(ProjectDeleteCommand(project_id="A"))

    assert result == {"ok": True, "moved": 0}
    assert not any(p.get("id") == "A" for p in projects_ref)
    default_after = next(p for p in projects_ref if p.get("id") == "default")
    assert default_after == default_snapshot, (
        "empty project delete 不许触碰 default project 记录"
    )


# T225(可选强化 · test_t108g_delete_project_concurrent_canvas_write)按任务书
# §决策边界"若 T225 并发场景实现复杂度过高 · 允许延后"条款延后:
# - 现服务层用 threading.Lock 单进程锁 · pytest 内多线程真起 canvas PUT
#   走 CanvasService.update_canvas · 涉及 broadcast callback / DB writer / json
#   写盘多重外部依赖 fixture 组装 · 复杂度显著高于当前 PR 收益(该边界
#   在现有单锁语义下"要么迁移完 PUT 落 default · 要么 PUT 等锁"是决定
#   性行为)。延后归后续 project 域并发契约 PR · 登记为遗留项。



# ---------------------------------------------------------------------------
# T109 — `/api/canvases/trash` HTTP 路径解析优先级（synthetic FastAPI app）
# ---------------------------------------------------------------------------

def test_t109_trash_route_wins_over_by_id_wildcard() -> None:
    from fastapi import FastAPI

    from app.api.routers.canvas import create_router
    from app.modules.canvas.commands import CanvasCreateCommand, CanvasIdCommand
    from app.modules.canvas.service import CanvasService

    # Prepare a fake service that records which method was invoked.
    fake_store = MagicMock()
    fake_store.load_canvas.return_value = {"id": "trash", "kind": "classic"}

    async def _broadcast(*_a, **_kw):
        return None

    service = CanvasService(
        store=fake_store,
        list_canvases=lambda: [{"id": "a"}],
        list_deleted_canvases=lambda: [{"id": "deleted"}],
        new_canvas=lambda *a, **kw: {"id": "new"},
        canvas_record=lambda c: c,
        canvas_path=lambda cid: cid,
        load_canvas_any=lambda cid: {"id": cid},
        normalize_canvas_kind=lambda k: k or "classic",
        normalize_canvas_color=lambda c: c,
        canvas_lock=MagicMock(__enter__=lambda s: None, __exit__=lambda *a: None),
        default_project_id="default",
        broadcast_canvas_updated=_broadcast,
        now_ms=lambda: 0,
    )

    # Import DTOs from main.py to preserve shape/kind契约.
    import main

    synth_app = FastAPI()
    synth_app.include_router(
        create_router(
            service=service,
            canvas_create_dto=main.CanvasCreateRequest,
            canvas_meta_update_dto=main.CanvasMetaUpdate,
            canvas_save_dto=main.CanvasSaveRequest,
        )
    )
    client = TestClient(synth_app)

    # `/trash` 必须命中 list_deleted_canvases（而不是把 "trash" 当作 canvas_id）
    response = client.get("/api/canvases/trash")
    assert response.status_code == 200
    body = response.json()
    assert body == {"canvases": [{"id": "deleted"}], "retention_days": 30}

    # `/{canvas_id}` 通配路径仍可正常工作
    response = client.get("/api/canvases/abc123")
    assert response.status_code == 200
    assert response.json()["canvas"]["id"] == "trash"  # 来自 fake_store
