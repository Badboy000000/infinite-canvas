"""Wave 3-N.7 Batch 5 主线 B · 前端 PR-13 契约测试 · 3 settings/manager 页 SPA 迁移.

Editorial:
    Verifies that 3 settings/manager pages (comfyui-settings, canvas-list,
    asset-manager) have been migrated from pure HTML to Vue 3 SPA
    skeleton components with Vue Router wiring. Legacy HTML files remain
    untouched.

    Skeleton migration only — UI layout + basic template. Full functional
    replication is deferred. Tests are static file existence + content
    checks; no npm install or Vite dev server required.

Covers T525-T529 (5 items):

    T525  static/src/pages/ComfyuiSettingsPage.vue exists · template + script setup
    T526  static/src/pages/CanvasListPage.vue exists · template + script setup
    T527  static/src/pages/AssetManagerPage.vue exists · template + script setup
    T528  static/src/router.js contains 3 new routes + imports
    T529  Legacy HTMLs retained (comfyui-settings, canvas-list,
          asset-manager .html files remain on disk).
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PAGE_NAMES = ["ComfyuiSettingsPage", "CanvasListPage", "AssetManagerPage"]
PAGE_ROUTES = ["comfyui-settings", "canvas-list", "asset-manager"]
LEGACY_HTMLS = ["comfyui-settings.html", "canvas-list.html", "asset-manager.html"]


# --- T525-T527: 3 Vue 组件文件存在 ---


@pytest.mark.parametrize("name", PAGE_NAMES)
def test_t525_t527_vue_page_exists(name):
    """T525-T527 · Vue 骨架组件存在 · 含 template + script setup."""
    page = ROOT / f"static/src/pages/{name}.vue"
    assert page.is_file(), f"static/src/pages/{name}.vue not found at {page}"
    text = page.read_text(encoding="utf-8")
    assert "<template>" in text, f"{name}.vue missing <template>"
    assert "<script setup>" in text, f"{name}.vue missing <script setup>"


# --- T528: router.js 追加 3 路由 ---


def test_t528_router_js_has_new_routes():
    """T528 · router.js 追加 3 路由 · 保留原 4 路由 · base 仍为 '/static/'."""
    router = ROOT / "static/src/router.js"
    assert router.is_file(), f"static/src/router.js not found at {router}"
    text = router.read_text(encoding="utf-8")

    # Base preserved (PR-16 invariant)
    assert re.search(r"createWebHistory\s*\(\s*['\"]/static/['\"]\s*\)", text), (
        "router.js missing createWebHistory('/static/')"
    )

    # New page imports
    for name in PAGE_NAMES:
        assert f"./pages/{name}.vue" in text, (
            f"router.js missing import for {name}.vue"
        )

    # New route paths
    for route in PAGE_ROUTES:
        assert re.search(
            rf"path:\s*['\"]/{re.escape(route)}['\"]", text
        ), f"router.js missing route path /{route}"

    # PR-16 routes still present
    for route in ("enhance", "klein", "angle", "zimage"):
        assert f"/{route}" in text, (
            f"router.js lost prior PR-16 route /{route}"
        )


# --- T529: legacy HTML 保留 ---


@pytest.mark.parametrize("html_file", LEGACY_HTMLS)
def test_t529_legacy_html_retained(html_file):
    """T529 · legacy HTML 保留(comfyui-settings/canvas-list/asset-manager.html)."""
    legacy = ROOT / f"static/{html_file}"
    assert legacy.is_file(), (
        f"Legacy HTML {html_file} was removed by PR-13 skeleton migration"
    )
