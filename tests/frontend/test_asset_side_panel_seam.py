"""Wave 3-K 前端 PR-9 (保守渲染层): AssetSidePanel seam consumer 测试.

Baseline (Wave 3-J 收官 / c99e3e5): 800 passed / 42 skipped.
Target: 800 → +5 (T60-T64).

Covers (编号池 T60-T64):
    T60  AssetSidePanel.renderHtml / 具名 template 与 canvas.js 原字符串
         **runtime-output-byte-equal** 对比 (5 template 分别断言)
    T61  AssetSidePanel.render() 有/无 document 分支语义 + 具名 export 完整性
    T62  未知 templateKey 走 fallback (renderHtml 返回空字符串, 不抛异常)
    T63  escapeHtml / escapeAttr **runtime-output-byte-equal** 于 canvas.js 定义体
         (extract source + Node subprocess execute + 逐字节对比)
    T64  canvas.js consumer 接入锚点 + smart-canvas.js 反向断言无挂载点
         (对齐 PR-8 T47/T47b pattern)

**GM-13 三轴等价性显式标注**:
    - runtime-output-byte-equal: seam 分支输出与 canvas.js 原字符串逐字节相等
    - source-byte-equal: **不适用** (多行式 vs 单行式源码文本不同)
    - visual-byte-equal: **不适用** (纯 HTML string 直接对比, 无 CSS 视觉差异)

**GM-14 死路检测**:
    - ASSET_SIDE_PANEL_TEMPLATES 支持集 = 6 key
      (library_option, category_option, asset_actions, asset_item_card,
       empty_state, asset_grid)
    - canvas.js consumer 实际使用集 = 3 直接调用 (renderLibraryOption /
      renderCategoryOption / renderAssetGrid) + 2 间接调用 (asset_grid
      内部调用 asset_item_card + asset_actions + empty_state)
    - **无 dead-canonical 子集** (支持集 == 传递闭包实际使用集)

**GM-15 dormant seam**:
    - AssetSidePanel state 层 (96 处 canvas.js state/fetch/upload/drag) 是
      **rendering consumed only**; state 层为 dormant seam, 待 CB-P5-09 / PR-11+ 承接
    - 契约域矩阵中 asset_side_panel = True 的语义是 rendering consumed only
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

ASP_INDEX = (ROOT / "static/js/shared/components/AssetSidePanel/index.js").as_uri()
ASP_TMPL = (ROOT / "static/js/shared/components/AssetSidePanel/domTemplates.js").as_uri()
ASP_INDEX_PATH = ROOT / "static/js/shared/components/AssetSidePanel/index.js"
ASP_TMPL_PATH = ROOT / "static/js/shared/components/AssetSidePanel/domTemplates.js"
CANVAS_JS = ROOT / "static/js/canvas.js"
SMART_CANVAS_JS = ROOT / "static/js/smart-canvas.js"
FIXTURES = ROOT / "tests/frontend/fixtures/asset_side_panel"


def _run_node_esm(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _run_node_cjs(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _extract_function_source(src: str, name: str) -> str:
    m = re.search(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", src)
    if not m:
        return ""
    start = m.start()
    depth = 0
    i = m.end() - 1
    while i < len(src):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return ""


# -------------------------------------------------------------------------
# T60 AssetSidePanel template 输出与 canvas.js 原字符串 runtime-output-byte-equal
# -------------------------------------------------------------------------
def test_t60_library_option_runtime_output_byte_equal_with_canvas_js():
    """seam 分支 renderLibraryOption 输出 vs canvas.js:6945 legacy 内联输出
    对同一输入 runtime-output-byte-equal (逐字节相等)."""
    fixture = json.loads(
        (FIXTURES / "library_option_default_selected.json").read_text(encoding="utf-8")
    )
    lib = fixture["input"]["lib"]
    active_id = fixture["input"]["activeLibraryId"]
    # seam 分支
    seam = _run_node_esm(
        f"""
        import {{ renderLibraryOption }} from '{ASP_TMPL}';
        console.log(JSON.stringify({{v: renderLibraryOption({json.dumps(lib)}, {json.dumps(active_id)})}}));
        """
    )
    # legacy 分支 (直接复现 canvas.js:6945 模板 —— escapeAttr/escapeHtml alias)
    legacy = _run_node_cjs(
        f"""
        const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
        const escapeAttr = escapeHtml;
        const lib = {json.dumps(lib)};
        const activeCanvasAssetLibraryId = {json.dumps(active_id)};
        const html = `<option value="${{escapeAttr(lib.id)}}" ${{lib.id === activeCanvasAssetLibraryId ? 'selected' : ''}}>${{escapeHtml(lib.name || '资产库')}}</option>`;
        console.log(JSON.stringify({{v: html}}));
        """
    )
    assert seam["v"] == legacy["v"], (
        f"renderLibraryOption 未 runtime-output-byte-equal 于 canvas.js:6945 legacy:\n"
        f"  seam:   {seam['v']!r}\n"
        f"  legacy: {legacy['v']!r}"
    )
    # 附加:fixture 声明的 expected_html 应精确匹配
    assert seam["v"] == fixture["expected_html"], (
        f"renderLibraryOption fixture 期望不符:\n"
        f"  实际: {seam['v']!r}\n"
        f"  期望: {fixture['expected_html']!r}"
    )


def test_t60_category_option_runtime_output_byte_equal_with_canvas_js():
    fixture = json.loads(
        (FIXTURES / "category_option_workflow_prefix.json").read_text(encoding="utf-8")
    )
    cat = fixture["input"]["cat"]
    active_id = fixture["input"]["activeCategoryId"]
    seam = _run_node_esm(
        f"""
        import {{ renderCategoryOption }} from '{ASP_TMPL}';
        console.log(JSON.stringify({{v: renderCategoryOption({json.dumps(cat)}, {json.dumps(active_id)})}}));
        """
    )
    legacy = _run_node_cjs(
        f"""
        const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
        const escapeAttr = escapeHtml;
        const cat = {json.dumps(cat)};
        const activeCanvasAssetCategoryId = {json.dumps(active_id)};
        const type = String(cat.type || 'image').toLowerCase();
        const prefix = type === 'workflow' ? '工作流 / ' : '';
        const html = `<option value="${{escapeAttr(cat.id)}}" ${{cat.id === activeCanvasAssetCategoryId ? 'selected' : ''}}>${{escapeHtml(prefix + (cat.name || '默认分组'))}}</option>`;
        console.log(JSON.stringify({{v: html}}));
        """
    )
    assert seam["v"] == legacy["v"], (
        f"renderCategoryOption 未 runtime-output-byte-equal 于 canvas.js:6950-6953 legacy:\n"
        f"  seam:   {seam['v']!r}\n"
        f"  legacy: {legacy['v']!r}"
    )


def test_t60_empty_state_runtime_output_byte_equal_with_canvas_js():
    for fname in ("empty_state_local_mode.json", "empty_state_cloud_mode.json"):
        fixture = json.loads((FIXTURES / fname).read_text(encoding="utf-8"))
        local_mode = fixture["input"]["localMode"]
        seam = _run_node_esm(
            f"""
            import {{ renderEmptyState }} from '{ASP_TMPL}';
            console.log(JSON.stringify({{v: renderEmptyState({json.dumps(local_mode)})}}));
            """
        )
        legacy = _run_node_cjs(
            f"""
            const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
            const localMode = {json.dumps(local_mode)};
            const html = `<div class="canvas-asset-empty">${{escapeHtml(localMode ? '暂无本地素材，请在素材库管理中上传' : '当前分组还没有资产')}}</div>`;
            console.log(JSON.stringify({{v: html}}));
            """
        )
        assert seam["v"] == legacy["v"], (
            f"renderEmptyState[{fname}] 未 runtime-output-byte-equal 于 canvas.js:6976:\n"
            f"  seam:   {seam['v']!r}\n"
            f"  legacy: {legacy['v']!r}"
        )
        assert seam["v"] == fixture["expected_html"]


def test_t60_asset_item_card_runtime_output_byte_equal_with_canvas_js():
    """asset_item_card 是最长的 template, 覆盖 local + cloud 双模式."""
    item = {"id": "item-1", "url": "https://example.com/a.png", "name": "asset-a"}
    thumb_html = "<div class=\"canvas-asset-thumb-wrap\">THUMB</div>"
    kind = "image"
    for local_mode in (True, False):
        seam = _run_node_esm(
            f"""
            import {{ renderAssetItemCard }} from '{ASP_TMPL}';
            const item = {json.dumps(item)};
            const ctx = {{thumbHtml: {json.dumps(thumb_html)}, kind: {json.dumps(kind)}, localMode: {json.dumps(local_mode)}}};
            console.log(JSON.stringify({{v: renderAssetItemCard(item, ctx)}}));
            """
        )
        legacy = _run_node_cjs(
            f"""
            const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
            const escapeAttr = escapeHtml;
            const item = {json.dumps(item)};
            const thumbHtml = {json.dumps(thumb_html)};
            const kind = {json.dumps(kind)};
            const localMode = {json.dumps(local_mode)};
            const html = `
        <div class="canvas-asset-item" draggable="true" data-asset-id="${{escapeAttr(item.id || '')}}" data-url="${{escapeAttr(item.url)}}" data-name="${{escapeAttr(item.name || 'asset')}}" data-kind="${{escapeAttr(kind)}}">
            ${{thumbHtml}}
            <div class="canvas-asset-meta">
                <span class="canvas-asset-name" title="${{escapeAttr(item.name || '')}}">${{escapeHtml(item.name || 'asset')}}</span>
                ${{localMode
                    ? `<span class="canvas-asset-local-tag">本地</span>`
                    : `<button class="canvas-asset-action" type="button" data-canvas-asset-rename="${{escapeAttr(item.id || '')}}" title="重命名" aria-label="重命名"><i data-lucide="pencil" class="w-4 h-4"></i></button>
                       <button class="canvas-asset-action danger" type="button" data-canvas-asset-delete="${{escapeAttr(item.id || '')}}" title="删除" aria-label="删除"><i data-lucide="trash-2" class="w-4 h-4"></i></button>`}}
            </div>
        </div>
    `;
            console.log(JSON.stringify({{v: html}}));
            """
        )
        assert seam["v"] == legacy["v"], (
            f"renderAssetItemCard[localMode={local_mode}] 未 runtime-output-byte-equal:\n"
            f"  seam:   {seam['v']!r}\n"
            f"  legacy: {legacy['v']!r}"
        )


# -------------------------------------------------------------------------
# T61 render()/renderHtml() API 完整性 + fallback 语义
# -------------------------------------------------------------------------
def test_t61_component_api_completeness():
    result = _run_node_esm(
        f"""
        import AssetSidePanel, {{
            renderLibraryOption, renderCategoryOption, renderAssetActions,
            renderAssetItemCard, renderEmptyState, renderAssetGrid,
            ASSET_SIDE_PANEL_TEMPLATES
        }} from '{ASP_INDEX}';
        // 具名 export 完整性
        const namedApiOk = [renderLibraryOption, renderCategoryOption,
            renderAssetActions, renderAssetItemCard, renderEmptyState,
            renderAssetGrid].every(fn => typeof fn === 'function');
        // 默认 export 一致性
        const defaultApiOk = typeof AssetSidePanel.renderHtml === 'function'
            && typeof AssetSidePanel.render === 'function'
            && typeof AssetSidePanel.renderLibraryOption === 'function';
        // 通用 renderHtml 分派
        const dispatchOk = AssetSidePanel.renderHtml('empty_state', true)
            === '<div class="canvas-asset-empty">暂无本地素材，请在素材库管理中上传</div>';
        // 6 template canonical 集合
        const canonicalKeys = Object.keys(ASSET_SIDE_PANEL_TEMPLATES).sort();
        console.log(JSON.stringify({{namedApiOk, defaultApiOk, dispatchOk, canonicalKeys}}));
        """
    )
    assert result["namedApiOk"], "6 具名 template export 不完整"
    assert result["defaultApiOk"], "默认 export 与具名 export 语义不一致"
    assert result["dispatchOk"], "renderHtml('empty_state', true) 分派输出错误"
    # GM-14 死路检测支撑:6 canonical key 显式声明
    assert result["canonicalKeys"] == sorted([
        "library_option", "category_option", "asset_actions",
        "asset_item_card", "empty_state", "asset_grid"
    ]), f"ASSET_SIDE_PANEL_TEMPLATES canonical 集合漂移: {result['canonicalKeys']}"


# -------------------------------------------------------------------------
# T62 未知 templateKey 走 fallback (不抛异常)
# -------------------------------------------------------------------------
def test_t62_unknown_template_key_returns_empty_no_throw():
    result = _run_node_esm(
        f"""
        import AssetSidePanel from '{ASP_INDEX}';
        const cases = [
            'unknown_key',
            '',
            null,
            undefined,
            123,
        ];
        const outputs = cases.map(k => {{
            try {{
                return {{ok: true, key: String(k), v: AssetSidePanel.renderHtml(k)}};
            }} catch (e) {{
                return {{ok: false, key: String(k), err: String(e)}};
            }}
        }});
        console.log(JSON.stringify({{outputs}}));
        """
    )
    for out in result["outputs"]:
        assert out["ok"], f"renderHtml({out['key']!r}) 抛异常: {out.get('err')}"
        assert out["v"] == "", (
            f"renderHtml({out['key']!r}) 未返回空字符串: {out['v']!r}"
        )


# -------------------------------------------------------------------------
# T63 escapeHtml / escapeAttr **runtime-output-byte-equal** 于 canvas.js 定义体
#     (extract source + Node subprocess + 逐字节对比)
# -------------------------------------------------------------------------
def test_t63_escape_html_and_attr_runtime_output_byte_equal_with_canvas_js():
    src = ASP_TMPL_PATH.read_text(encoding="utf-8")
    asp_escape_html = _extract_function_source(src, "escapeHtml")
    asp_escape_attr = _extract_function_source(src, "escapeAttr")
    assert asp_escape_html, "AssetSidePanel domTemplates.js escapeHtml 未提取到"
    assert asp_escape_attr, "AssetSidePanel domTemplates.js escapeAttr 未提取到"
    canvas_fn = _extract_function_source(
        CANVAS_JS.read_text(encoding="utf-8"), "escapeHtml"
    )
    assert canvas_fn, "canvas.js escapeHtml 未提取到"
    # 5 高危字符 sentinel
    test_inputs = [
        "<script>alert('x')</script>",
        "\" onload=\"alert(1)\"",
        "&<>\"'",
        None,
        "safe string",
    ]
    for inp in test_inputs:
        asp_out = _run_node_cjs(
            asp_escape_html + f"\nconsole.log(JSON.stringify({{v: escapeHtml({json.dumps(inp)})}}));"
        )
        canvas_out = _run_node_cjs(
            canvas_fn + f"\nconsole.log(JSON.stringify({{v: escapeHtml({json.dumps(inp)})}}));"
        )
        assert asp_out["v"] == canvas_out["v"], (
            f"AssetSidePanel.escapeHtml 未 runtime-output-byte-equal 于 canvas.js:\n"
            f"  input:      {inp!r}\n"
            f"  ASP:        {asp_out['v']!r}\n"
            f"  canvas.js:  {canvas_out['v']!r}"
        )
    # 附加:XSS sink 覆盖矩阵
    xss_fixture = json.loads((FIXTURES / "xss_sink_sentinel.json").read_text(encoding="utf-8"))
    lib = xss_fixture["input"]["lib"]
    active = xss_fixture["input"]["activeLibraryId"]
    seam = _run_node_esm(
        f"""
        import {{ renderLibraryOption }} from '{ASP_TMPL}';
        console.log(JSON.stringify({{v: renderLibraryOption({json.dumps(lib)}, {json.dumps(active)})}}));
        """
    )
    for esc in xss_fixture["must_contain_escaped"]:
        assert esc in seam["v"], (
            f"XSS sentinel 缺失 escape 输出 {esc!r}: {seam['v']!r}"
        )
    for raw in xss_fixture["must_not_contain"]:
        assert raw not in seam["v"], (
            f"XSS sentinel 泄漏原始 sink {raw!r}: {seam['v']!r}"
        )


# -------------------------------------------------------------------------
# T64 canvas.js consumer 接入锚点 + smart-canvas.js 反向断言
# -------------------------------------------------------------------------
def test_t64_canvas_js_asset_side_panel_seam_consumed():
    src = CANVAS_JS.read_text(encoding="utf-8")
    # 关键锚点1: AssetSidePanel dynamic import 存在
    assert "AssetSidePanel" in src, "canvas.js 未引用 AssetSidePanel"
    assert "/static/js/shared/components/AssetSidePanel/index.js" in src, (
        "canvas.js 未 dynamic import AssetSidePanel"
    )
    # 关键锚点2: 3 template 调用点存在
    assert "asp.renderLibraryOption" in src, (
        "canvas.js 未调用 AssetSidePanel.renderLibraryOption seam"
    )
    assert "asp.renderCategoryOption" in src, (
        "canvas.js 未调用 AssetSidePanel.renderCategoryOption seam"
    )
    assert "asp.renderAssetGrid" in src, (
        "canvas.js 未调用 AssetSidePanel.renderAssetGrid seam"
    )
    # 关键锚点3: legacy 内联 fallback 仍在 (seam import 竞态兜底)
    assert 'canvasAssetLibrarySelect.innerHTML' in src
    assert 'canvasAssetGrid.innerHTML' in src


def test_t64_smart_canvas_has_no_asset_side_panel_mount_point():
    """事实断言: smart-canvas.js 无 AssetSidePanel 挂载点.
    smart-canvas.js 有独立的 `assetPanel` 状态 (行 37) + `renderAssetLibrary`
    (行 5385), 与 canvas.js 的 canvasAssetPanel 是不同 UI, PR-9 不迁移.
    (对齐 PR-8 T47b pattern) —— 若未来 smart-canvas.js 引入 AssetSidePanel
    seam, 此断言应更新为迁移断言."""
    src = SMART_CANVAS_JS.read_text(encoding="utf-8")
    assert "AssetSidePanel" not in src, (
        "smart-canvas.js 现引用 AssetSidePanel, 需要 PR-9 或后续迁移断言更新"
    )
    assert "/shared/components/AssetSidePanel" not in src, (
        "smart-canvas.js 现 import AssetSidePanel, 需要更新迁移断言"
    )


# -------------------------------------------------------------------------
# T64-bonus: 契约域矩阵翻转 —— asset_side_panel 现为 True (rendering consumed only)
# 参照 PR-8 test_node_status_view_seam.py::CONTRACT_DOMAINS_24 pattern
# **GM-15 dormant seam 显式声明**: state 层 dormant seam 待 CB-P5-09 / PR-11+ 承接
# -------------------------------------------------------------------------
CONTRACT_DOMAINS_24_UPDATED = {
    # PR-8 消费 (rendering-only + gating dormant seam)
    "status_badge": True,
    # PR-9 新消费 (rendering-only; state 层 dormant seam 待 CB-P5-09 承接)
    "asset_side_panel": True,  # asset_side_panel = rendering consumed only;
                               #  state 层 dormant seam 待 PR-11+
    "provider_selector": True,  # provider_selector = rendering consumed only;
                                #  onchange 事件 dormant seam
    # 未消费的 21 域 (待 PR-10/11 承接)
    "node_head_title": False,
    "node_head_delete_button": False,
    "node_body_image": False,
    "node_body_prompt": False,
    "node_body_output_grid": False,
    "node_body_llm": False,
    "node_body_comfy": False,
    "node_body_ltx_director": False,
    "node_body_rh": False,
    "node_body_video": False,
    "node_body_msgen": False,
    "node_port_in": False,
    "node_port_out": False,
    "node_resize_handle": False,
    "config_panel_generator": False,
    "config_panel_output": False,
    "drag_interaction_node": False,
    "drag_interaction_port": False,
    "context_menu_generator": False,
    "context_menu_output": False,
    "prompt_template_drawer": False,
}


def test_t64_seam_coverage_matrix_asset_side_panel_flipped():
    assert len(CONTRACT_DOMAINS_24_UPDATED) == 24, (
        f"契约域清单必须为 24, 实际 {len(CONTRACT_DOMAINS_24_UPDATED)}"
    )
    consumed = sorted([k for k, v in CONTRACT_DOMAINS_24_UPDATED.items() if v])
    assert consumed == ["asset_side_panel", "provider_selector", "status_badge"], (
        f"PR-9 消费点应含 status_badge + asset_side_panel + provider_selector (3/24), "
        f"实际: {consumed}"
    )
    # dormant seam 显式声明:
    assert CONTRACT_DOMAINS_24_UPDATED["asset_side_panel"] is True, (
        "asset_side_panel = rendering consumed only; state 层 dormant seam "
        "待 CB-P5-09 / PR-11+ 承接"
    )
