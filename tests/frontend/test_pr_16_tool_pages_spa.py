"""Wave 3-N.7 Batch 3 主线 B · 前端 PR-16 契约测试 · 4 工具页 SPA 迁移.

Editorial:
    Verifies that 4 low-coupling tool pages (enhance, klein, angle, zimage)
    have been migrated from pure HTML to Vue 3 SPA components with proper
    Vue Router wiring. Legacy HTML files must remain untouched.

    Tests are static file existence + content checks — no npm install or
    Vite dev server is required.

Covers T510-T519 (10 items):

    T510  static/src/pages/EnhancePage.vue 存在 · 含 template + script setup
    T511  static/src/pages/KleinPage.vue 存在 · 含 template + script setup
    T512  static/src/pages/AnglePage.vue 存在 · 含 template + script setup
    T513  static/src/pages/ZimagePage.vue 存在 · 含 template + script setup
    T514  static/src/router.js 存在 · 配置 4 条路由 · base: '/static/'
    T515  static/src/main.js 含 router.use 调用
    T516  static/package.json 含 vue-router 依赖
    T517  legacy HTML 文件保留(enhance.html 仍存在)
    T518  legacy HTML 文件保留(klein.html 仍存在)
    T519  vue-router 的 createWebHistory base 为 '/static/'
"""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# --- T510-T513: 4 Vue 组件文件存在 ---

PAGE_NAMES = ["EnhancePage", "KleinPage", "AnglePage", "ZimagePage"]
PAGE_ROUTES = ["enhance", "klein", "angle", "zimage"]


@pytest.mark.parametrize("name,route", list(zip(PAGE_NAMES, PAGE_ROUTES)))
def test_t510_t513_vue_page_exists(name, route):
    """T510-T513 · Vue 组件文件存在 · 含 template + script setup."""
    page = ROOT / f"static/src/pages/{name}.vue"
    assert page.is_file(), f"static/src/pages/{name}.vue not found at {page}"
    text = page.read_text(encoding="utf-8")
    assert "<template>" in text, f"{name}.vue missing <template>"
    assert "<script setup>" in text, f"{name}.vue missing <script setup>"


# --- T514: router.js 配置 ---


def test_t514_router_js_exists():
    """T514 · static/src/router.js 存在 · 配置 4 条路由 · base: '/static/'."""
    router = ROOT / "static/src/router.js"
    assert router.is_file(), f"static/src/router.js not found at {router}"
    text = router.read_text(encoding="utf-8")
    # Check base
    assert re.search(r"createWebHistory\s*\(\s*['\"]/static/['\"]\s*\)", text), (
        "router.js missing createWebHistory('/static/')"
    )
    # Check all 4 page imports
    for name in PAGE_NAMES:
        assert f"./pages/{name}.vue" in text, (
            f"router.js missing import for {name}.vue"
        )
    # Check all 4 route paths
    for route in PAGE_ROUTES:
        assert f"/{route}" in text, (
            f"router.js missing route path /{route}"
        )


# --- T515: main.js 含 router.use ---


def test_t515_main_js_has_router_use():
    """T515 · static/src/main.js 含 router.use 调用."""
    main = ROOT / "static/src/main.js"
    assert main.is_file(), f"static/src/main.js not found at {main}"
    text = main.read_text(encoding="utf-8")
    assert "router" in text, "main.js missing 'router' reference"
    assert "use(router)" in text or 'use(router)' in text, (
        "main.js missing app.use(router)"
    )


# --- T516: package.json 含 vue-router ---


def test_t516_package_json_has_vue_router():
    """T516 · static/package.json 含 vue-router 依赖."""
    pkg = ROOT / "static/package.json"
    assert pkg.is_file(), f"static/package.json not found at {pkg}"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    deps = data.get("dependencies", {})
    assert "vue-router" in deps, (
        "dependencies missing 'vue-router'"
    )


# --- T517-T518: legacy HTML 文件保留 ---


@pytest.mark.parametrize("html_file", ["enhance.html", "klein.html", "angle.html", "zimage.html"])
def test_t517_t518_legacy_html_retained(html_file):
    """T517-T518 · legacy HTML 文件保留(enhance/klein/angle/zimage.html 仍存在)."""
    legacy = ROOT / f"static/{html_file}"
    assert legacy.is_file(), (
        f"Legacy HTML file {html_file} was removed or not found at {legacy}"
    )


# --- T519: createWebHistory base 为 '/static/' ---


def test_t519_router_history_base_static():
    """T519 · vue-router 的 createWebHistory base 为 '/static/'."""
    router = ROOT / "static/src/router.js"
    assert router.is_file()
    text = router.read_text(encoding="utf-8")
    assert "createWebHistory" in text, "router.js missing createWebHistory"
    assert re.search(r"createWebHistory\s*\(\s*['\"]/static/['\"]\s*\)", text), (
        "createWebHistory base is not '/static/'"
    )