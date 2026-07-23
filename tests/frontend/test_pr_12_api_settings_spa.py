"""Wave 3-N.7 Batch 5 主线 A · 前端 PR-12 契约测试 · api-settings SPA 迁移.

Editorial:
    Verifies that api-settings has been migrated from pure HTML to a Vue 3
    SPA component (skeleton), that vue-router now serves it at
    ``/api-settings``, and that the legacy ``static/api-settings.html``
    remains in place (骨架迁移, not a full functional replacement).

    Static file existence + content checks — no npm install or Vite dev
    server is required.

Covers T520-T524 (5 items):

    T520  static/src/pages/ApiSettingsPage.vue 存在 · 含 <template> + <script setup>
    T521  static/src/router.js 追加 /api-settings 路由 · 保留既有 4 条路由
    T522  static/src/router.js 保留 createWebHistory('/static/') base
    T523  legacy static/api-settings.html 保留(未被删除)
    T524  ApiSettingsPage.vue 含 provider 相关 UI 骨架文案(平台列表 + 平台名称)
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PAGE_PATH = ROOT / "static/src/pages/ApiSettingsPage.vue"
ROUTER_PATH = ROOT / "static/src/router.js"
LEGACY_HTML_PATH = ROOT / "static/api-settings.html"

EXISTING_PAGES = ["EnhancePage", "KleinPage", "AnglePage", "ZimagePage"]
EXISTING_ROUTES = ["/enhance", "/klein", "/angle", "/zimage"]


# --- T520: ApiSettingsPage.vue 存在 ---


def test_t520_api_settings_page_exists():
    """T520 · static/src/pages/ApiSettingsPage.vue 存在 · 含 template + script setup."""
    assert PAGE_PATH.is_file(), (
        f"static/src/pages/ApiSettingsPage.vue not found at {PAGE_PATH}"
    )
    text = PAGE_PATH.read_text(encoding="utf-8")
    assert "<template>" in text, "ApiSettingsPage.vue missing <template>"
    assert "<script setup>" in text, "ApiSettingsPage.vue missing <script setup>"


# --- T521: router.js 追加 /api-settings 路由 · 保留既有路由 ---


def test_t521_router_has_api_settings_route():
    """T521 · router.js 追加 /api-settings 路由 · 保留既有 4 条路由."""
    assert ROUTER_PATH.is_file(), f"router.js not found at {ROUTER_PATH}"
    text = ROUTER_PATH.read_text(encoding="utf-8")

    # 新路由:导入 + path
    assert "./pages/ApiSettingsPage.vue" in text, (
        "router.js missing import for ApiSettingsPage.vue"
    )
    assert re.search(
        r"path:\s*['\"]/api-settings['\"]", text
    ), "router.js missing route path /api-settings"
    assert "ApiSettingsPage" in text, (
        "router.js missing ApiSettingsPage component reference"
    )

    # 保留既有 4 页 · PR-16 pattern 复用不能倒退
    for name in EXISTING_PAGES:
        assert f"./pages/{name}.vue" in text, (
            f"router.js regressed: import for {name}.vue was removed"
        )
    for route in EXISTING_ROUTES:
        assert re.search(rf"path:\s*['\"]{route}['\"]", text), (
            f"router.js regressed: route path {route} was removed"
        )


# --- T522: createWebHistory base 保留 '/static/' ---


def test_t522_router_history_base_preserved():
    """T522 · router.js 保留 createWebHistory('/static/') base."""
    text = ROUTER_PATH.read_text(encoding="utf-8")
    assert "createWebHistory" in text, "router.js missing createWebHistory"
    assert re.search(
        r"createWebHistory\s*\(\s*['\"]/static/['\"]\s*\)", text
    ), "createWebHistory base is not '/static/'"


# --- T523: legacy api-settings.html 保留 ---


def test_t523_legacy_api_settings_html_retained():
    """T523 · legacy static/api-settings.html 保留(骨架迁移不删旧文件)."""
    assert LEGACY_HTML_PATH.is_file(), (
        f"Legacy api-settings.html was removed or not found at {LEGACY_HTML_PATH}"
    )


# --- T524: 页面含 provider 相关 UI 骨架 ---


def test_t524_api_settings_page_has_provider_skeleton():
    """T524 · ApiSettingsPage.vue 含 provider 相关 UI 骨架文案."""
    text = PAGE_PATH.read_text(encoding="utf-8")
    # 关键 UI 骨架标识 · 对应 legacy 的 provider-list / 基本信息 / 平台名称
    assert "平台列表" in text, "ApiSettingsPage.vue missing '平台列表' skeleton"
    assert "平台名称" in text, "ApiSettingsPage.vue missing '平台名称' skeleton"
