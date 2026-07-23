"""Wave 3-N.7 Batch 6 主线 A · 前端 PR-14 契约测试 · canvas SPA 迁移.

Editorial:
    Verifies that the classic canvas page (`static/canvas.html`) has been
    migrated to a Vue 3 SPA skeleton component with Vue Router wiring.
    Skeleton migration only — UI layout + basic template. Full functional
    replication is deferred. Legacy HTML file must remain on disk.

    Tests are static file existence + content checks; no npm install or
    Vite dev server is required.

Covers T530-T534 (5 items):

    T530  static/src/pages/CanvasPage.vue exists · template + script setup
    T531  static/src/router.js contains CanvasPage import
    T532  static/src/router.js contains /canvas route
    T533  static/src/router.js retains prior routes (no regression)
    T534  Legacy static/canvas.html retained (untouched)
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


# --- T530: Vue 骨架组件存在 ---


def test_t530_canvas_page_vue_exists():
    """T530 · CanvasPage.vue 存在 · 含 template + script setup."""
    page = ROOT / "static/src/pages/CanvasPage.vue"
    assert page.is_file(), f"static/src/pages/CanvasPage.vue not found at {page}"
    text = page.read_text(encoding="utf-8")
    assert "<template>" in text, "CanvasPage.vue missing <template>"
    assert "<script setup>" in text, "CanvasPage.vue missing <script setup>"


# --- T531: router.js 追加 CanvasPage import ---


def test_t531_router_js_imports_canvas_page():
    """T531 · router.js 含 CanvasPage.vue import."""
    router = ROOT / "static/src/router.js"
    assert router.is_file(), f"static/src/router.js not found at {router}"
    text = router.read_text(encoding="utf-8")
    assert "./pages/CanvasPage.vue" in text, (
        "router.js missing import for CanvasPage.vue"
    )


# --- T532: router.js 追加 /canvas 路由 ---


def test_t532_router_js_has_canvas_route():
    """T532 · router.js 含 /canvas 路由."""
    router = ROOT / "static/src/router.js"
    text = router.read_text(encoding="utf-8")
    assert re.search(r"path:\s*['\"]/canvas['\"]", text), (
        "router.js missing route path /canvas"
    )
    # base preserved (PR-16 invariant)
    assert re.search(r"createWebHistory\s*\(\s*['\"]/static/['\"]\s*\)", text), (
        "router.js missing createWebHistory('/static/')"
    )


# --- T533: 保留原有路由 ---


def test_t533_router_js_retains_prior_routes():
    """T533 · router.js 保留 PR-10/12/13/16 累计路由,不删除任何 import."""
    router = ROOT / "static/src/router.js"
    text = router.read_text(encoding="utf-8")

    prior_pages = [
        "EnhancePage",
        "KleinPage",
        "AnglePage",
        "ZimagePage",
        "ApiSettingsPage",
        "ComfyuiSettingsPage",
        "CanvasListPage",
        "AssetManagerPage",
    ]
    for name in prior_pages:
        assert f"./pages/{name}.vue" in text, (
            f"router.js lost prior import for {name}.vue"
        )

    prior_routes = [
        "enhance",
        "klein",
        "angle",
        "zimage",
        "api-settings",
        "comfyui-settings",
        "canvas-list",
        "asset-manager",
    ]
    for route in prior_routes:
        assert re.search(rf"path:\s*['\"]/{re.escape(route)}['\"]", text), (
            f"router.js lost prior route path /{route}"
        )


# --- T534: legacy canvas.html 保留 ---


def test_t534_legacy_canvas_html_retained():
    """T534 · legacy static/canvas.html 保留(骨架迁移不删旧文件)."""
    legacy = ROOT / "static/canvas.html"
    assert legacy.is_file(), (
        f"Legacy HTML canvas.html was removed by PR-14 skeleton migration at {legacy}"
    )
