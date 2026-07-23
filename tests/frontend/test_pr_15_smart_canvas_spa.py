"""Wave 3-N.7 Batch 6 主线 B · 前端 PR-15 契约测试 · smart-canvas SPA 迁移(收官).

Editorial:
    Verifies that the smart-canvas page has been migrated from pure HTML to a
    Vue 3 SPA component with proper Vue Router wiring. Legacy HTML file must
    remain untouched. This PR is the closing (100%) commit of the frontend
    componentization theme.

    Tests are static file existence + content checks — no npm install or
    Vite dev server is required.

Covers T535-T539 (5 items):

    T535  static/src/pages/SmartCanvasPage.vue 存在 · 含 template + script setup
    T536  static/src/router.js 含 /smart-canvas 路由 + SmartCanvasPage 导入
    T537  legacy static/smart-canvas.html 保留(未删除)
    T538  router.js 保留既有路由(未回退 PR-12/13/14/16)
    T539  createWebHistory base 仍为 '/static/'
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAGE_PATH = ROOT / "static/src/pages/SmartCanvasPage.vue"
ROUTER_PATH = ROOT / "static/src/router.js"
LEGACY_HTML = ROOT / "static/smart-canvas.html"


# --- T535: SmartCanvasPage.vue 存在 + template + script setup ---


def test_t535_smart_canvas_page_exists():
    """T535 · SmartCanvasPage.vue 存在 · 含 template + script setup."""
    assert PAGE_PATH.is_file(), (
        f"static/src/pages/SmartCanvasPage.vue not found at {PAGE_PATH}"
    )
    text = PAGE_PATH.read_text(encoding="utf-8")
    assert "<template>" in text, "SmartCanvasPage.vue missing <template>"
    assert "<script setup>" in text, "SmartCanvasPage.vue missing <script setup>"


# --- T536: router.js 含 /smart-canvas 路由 ---


def test_t536_router_has_smart_canvas_route():
    """T536 · static/src/router.js 含 /smart-canvas 路由 + SmartCanvasPage 导入."""
    assert ROUTER_PATH.is_file(), f"static/src/router.js not found at {ROUTER_PATH}"
    text = ROUTER_PATH.read_text(encoding="utf-8")
    assert "./pages/SmartCanvasPage.vue" in text, (
        "router.js missing SmartCanvasPage.vue import"
    )
    assert re.search(
        r"path:\s*['\"]/smart-canvas['\"]\s*,\s*component:\s*SmartCanvasPage",
        text,
    ), "router.js missing route { path: '/smart-canvas', component: SmartCanvasPage }"


# --- T537: legacy smart-canvas.html 保留 ---


def test_t537_legacy_smart_canvas_html_retained():
    """T537 · legacy static/smart-canvas.html 保留(未删除)."""
    assert LEGACY_HTML.is_file(), (
        f"Legacy HTML file smart-canvas.html was removed or not found at {LEGACY_HTML}"
    )


# --- T538: router.js 保留既有路由(未回退 PR-12/13/14/16) ---


def test_t538_router_retains_prior_routes():
    """T538 · router.js 保留 PR-12/13/14/16 既有路由(未回退)."""
    assert ROUTER_PATH.is_file()
    text = ROUTER_PATH.read_text(encoding="utf-8")
    expected_pages = [
        "EnhancePage",
        "KleinPage",
        "AnglePage",
        "ZimagePage",
        "ApiSettingsPage",
        "ComfyuiSettingsPage",
        "CanvasListPage",
        "AssetManagerPage",
    ]
    for name in expected_pages:
        assert f"./pages/{name}.vue" in text, (
            f"router.js lost prior import for {name}.vue — PR-15 must only append"
        )
    expected_paths = [
        "/enhance",
        "/klein",
        "/angle",
        "/zimage",
        "/api-settings",
        "/comfyui-settings",
        "/canvas-list",
        "/asset-manager",
    ]
    for path in expected_paths:
        assert re.search(
            rf"path:\s*['\"]{re.escape(path)}['\"]", text
        ), f"router.js lost prior route {path} — PR-15 must only append"


# --- T539: createWebHistory base 仍为 '/static/' ---


def test_t539_router_history_base_static():
    """T539 · vue-router 的 createWebHistory base 仍为 '/static/'."""
    assert ROUTER_PATH.is_file()
    text = ROUTER_PATH.read_text(encoding="utf-8")
    assert re.search(
        r"createWebHistory\s*\(\s*['\"]/static/['\"]\s*\)", text
    ), "router.js createWebHistory base is not '/static/'"
