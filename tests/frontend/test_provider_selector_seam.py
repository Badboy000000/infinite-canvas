"""Wave 3-K 前端 PR-9 (保守渲染层): ProviderSelector seam consumer 测试.

Baseline (Wave 3-J 收官 / c99e3e5): 800 passed / 42 skipped.
Target: 800 → +5 (T65-T69).

Covers (编号池 T65-T69):
    T65  ProviderSelector 3 变体 (chat/image/video) API 完整性 + escape 定义体验证
    T66  chat/image/video 三变体 renderHtml 输出与 canvas.js 原字符串
         **runtime-output-byte-equal** (3 变体 × 各 fixture case)
    T67  image 变体特有:providers 空时输出 disabled 占位 option (canvas.js:684 语义)
    T68  canvas.js 3 处消费点接入锚点 + smart-canvas.js chatProviderOptions
         **暂未迁移** 反向断言(与 canvas.js 迁移状态区分)
    T69  XSS sink 反注入 + provider name fallback to id + null-safe

**GM-13 三轴等价性显式标注**:
    - runtime-output-byte-equal: 3 变体 seam 输出 vs canvas.js 原字符串逐字节相等
    - source-byte-equal: **不适用**
    - visual-byte-equal: **不适用**

**GM-14 死路检测**:
    - PROVIDER_SELECTOR_VARIANTS 支持集 = 3 (chat/image/video)
    - canvas.js consumer 实际使用集 = 3 (chatProviderOptions/providerOptions/videoProviderOptions)
    - smart-canvas.js 也用 chat 变体 (行 2362)
    - **无 dead-canonical 子集**

**GM-15 dormant seam**:
    - onchange 事件绑定 + providers 数据源函数 (chatApiProviders/imageApiProviders/
      videoApiProviders) 仍在 canvas.js/smart-canvas.js
    - state 层为 dormant seam, 待 PR-11+ 承接
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PS_INDEX = (ROOT / "static/js/shared/components/ProviderSelector/index.js").as_uri()
PS_OPTS = (ROOT / "static/js/shared/components/ProviderSelector/providerOptions.js").as_uri()
PS_INDEX_PATH = ROOT / "static/js/shared/components/ProviderSelector/index.js"
PS_OPTS_PATH = ROOT / "static/js/shared/components/ProviderSelector/providerOptions.js"
CANVAS_JS = ROOT / "static/js/canvas.js"
SMART_CANVAS_JS = ROOT / "static/js/smart-canvas.js"
FIXTURES = ROOT / "tests/frontend/fixtures/provider_selector"


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
# T65 ProviderSelector API 完整性 + 3 变体 canonical 集合
# -------------------------------------------------------------------------
def test_t65_component_api_and_variants():
    result = _run_node_esm(
        f"""
        import ProviderSelector, {{
            renderOption, renderOptionList, renderEmptyOption,
            PROVIDER_SELECTOR_VARIANTS
        }} from '{PS_INDEX}';
        // 具名 export 完整性
        const namedApiOk = [renderOption, renderOptionList, renderEmptyOption]
            .every(fn => typeof fn === 'function');
        // 默认 export
        const defaultApiOk = typeof ProviderSelector.renderHtml === 'function'
            && typeof ProviderSelector.render === 'function';
        // 3 变体 canonical
        const variantKeys = Object.keys(PROVIDER_SELECTOR_VARIANTS).sort();
        // 每变体的 consumer_sites 都必须非空 (GM-14 死路检测支撑)
        const consumerSites = {{}};
        Object.entries(PROVIDER_SELECTOR_VARIANTS).forEach(([k, v]) => {{
            consumerSites[k] = v.consumer_sites || [];
        }});
        // image 变体独有 has_empty_placeholder
        const imageHasEmpty = PROVIDER_SELECTOR_VARIANTS.image.has_empty_placeholder === true;
        console.log(JSON.stringify({{
            namedApiOk, defaultApiOk, variantKeys, consumerSites, imageHasEmpty
        }}));
        """
    )
    assert result["namedApiOk"], "3 具名 export 不完整"
    assert result["defaultApiOk"], "默认 export 缺失"
    assert result["variantKeys"] == ["chat", "image", "video"], (
        f"PROVIDER_SELECTOR_VARIANTS canonical 集合漂移: {result['variantKeys']}"
    )
    # GM-14 死路检测:每变体都有 ≥1 consumer_site
    for variant, sites in result["consumerSites"].items():
        assert len(sites) >= 1, (
            f"变体 {variant} consumer_sites 为空,可能是 dead canonical: {sites}"
        )
    assert result["imageHasEmpty"], "image 变体必须声明 has_empty_placeholder=true"


# -------------------------------------------------------------------------
# T66 3 变体 runtime-output-byte-equal 于 canvas.js 原字符串
# -------------------------------------------------------------------------
@pytest.mark.parametrize("fixture_name", [
    "chat_two_providers.json",
    "video_three_providers.json",
    "name_fallback_to_id.json",
])
def test_t66_variant_runtime_output_byte_equal_with_canvas_js(fixture_name):
    fixture = json.loads((FIXTURES / fixture_name).read_text(encoding="utf-8"))
    variant = fixture["variant"]
    providers = fixture["providers"]
    selected = fixture["selectedId"]
    # seam 分支
    seam = _run_node_esm(
        f"""
        import ProviderSelector from '{PS_INDEX}';
        console.log(JSON.stringify({{v: ProviderSelector.renderHtml(
            {json.dumps(variant)}, {json.dumps(providers)}, {json.dumps(selected)}
        )}}));
        """
    )
    # legacy 分支 (从 canvas.js 提取的 template 复现)
    # canvas.js:671/685/710 三处 body 完全一致的 <option> 模板
    legacy = _run_node_cjs(
        f"""
        const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[s]));
        const providers = {json.dumps(providers)};
        const selected = {json.dumps(selected)};
        const html = providers.map(provider => `<option value="${{escapeHtml(provider.id)}}" ${{provider.id === selected ? 'selected' : ''}}>${{escapeHtml(provider.name || provider.id)}}</option>`).join('');
        console.log(JSON.stringify({{v: html}}));
        """
    )
    assert seam["v"] == legacy["v"], (
        f"[{fixture_name}] ProviderSelector.renderHtml({variant!r}) 未 "
        f"runtime-output-byte-equal 于 canvas.js legacy:\n"
        f"  seam:   {seam['v']!r}\n"
        f"  legacy: {legacy['v']!r}"
    )
    if "expected_html" in fixture:
        assert seam["v"] == fixture["expected_html"], (
            f"[{fixture_name}] fixture 期望不符:\n"
            f"  实际: {seam['v']!r}\n"
            f"  期望: {fixture['expected_html']!r}"
        )


# -------------------------------------------------------------------------
# T67 image 变体空 providers 特殊处理 (canvas.js:684 语义)
# -------------------------------------------------------------------------
def test_t67_image_variant_empty_providers_uses_disabled_placeholder():
    fixture = json.loads((FIXTURES / "image_empty_placeholder.json").read_text(encoding="utf-8"))
    seam = _run_node_esm(
        f"""
        import ProviderSelector from '{PS_INDEX}';
        console.log(JSON.stringify({{v: ProviderSelector.renderHtml(
            'image', {json.dumps(fixture['providers'])}, {json.dumps(fixture['selectedId'])},
            {{emptyLabel: {json.dumps(fixture['emptyLabel'])}}}
        )}}));
        """
    )
    # legacy canvas.js:684:
    #   if(!providers.length) return `<option value="" disabled selected>${tr(...)} || '暂无 API 平台'}</option>`;
    legacy = _run_node_cjs(
        f"""
        const providers = {json.dumps(fixture['providers'])};
        const emptyLabel = {json.dumps(fixture['emptyLabel'])};
        let html;
        if(!providers.length) html = `<option value="" disabled selected>${{emptyLabel}}</option>`;
        else html = 'NON_EMPTY';
        console.log(JSON.stringify({{v: html}}));
        """
    )
    assert seam["v"] == legacy["v"], (
        f"image 变体空 providers 输出未 runtime-output-byte-equal:\n"
        f"  seam:   {seam['v']!r}\n"
        f"  legacy: {legacy['v']!r}"
    )
    assert seam["v"] == fixture["expected_html"]
    # 关键锚点:占位符必须含 disabled + selected + empty value
    for token in fixture["expected_contains"]:
        assert token in seam["v"], (
            f"image 变体 placeholder 缺 token {token!r}: {seam['v']!r}"
        )

    # 附加:chat/video 变体在 providers 空时**不**输出 placeholder (对齐 canvas.js:669/708 语义)
    for variant in ("chat", "video"):
        empty_seam = _run_node_esm(
            f"""
            import ProviderSelector from '{PS_INDEX}';
            console.log(JSON.stringify({{v: ProviderSelector.renderHtml(
                {json.dumps(variant)}, [], ''
            )}}));
            """
        )
        assert empty_seam["v"] == "", (
            f"{variant} 变体在 providers 空时应返回 '', 不含 placeholder: {empty_seam['v']!r}"
        )


# -------------------------------------------------------------------------
# T68 canvas.js 3 处消费点接入锚点 + smart-canvas.js 状态断言
# -------------------------------------------------------------------------
def test_t68_canvas_js_three_consumer_sites_seam_consumed():
    src = CANVAS_JS.read_text(encoding="utf-8")
    # 关键锚点1: ProviderSelector dynamic import 存在
    assert "ProviderSelector" in src, "canvas.js 未引用 ProviderSelector"
    assert "/static/js/shared/components/ProviderSelector/index.js" in src, (
        "canvas.js 未 dynamic import ProviderSelector"
    )
    # 关键锚点2: 3 处调用点 (chat/image/video 变体分派)
    chat_seam = re.search(r"ps\.renderHtml\('chat',", src)
    image_seam = re.search(r"ps\.renderHtml\('image',", src)
    video_seam = re.search(r"ps\.renderHtml\('video',", src)
    assert chat_seam, "canvas.js 未调用 ps.renderHtml('chat', ...)"
    assert image_seam, "canvas.js 未调用 ps.renderHtml('image', ...)"
    assert video_seam, "canvas.js 未调用 ps.renderHtml('video', ...)"
    # 关键锚点3: legacy 内联兜底仍在 (seam import 竞态兜底)
    legacy_pattern = re.compile(
        r'`<option value="\$\{escapeHtml\(provider\.id\)\}" '
        r'\$\{provider\.id === selected \? \'selected\' : \'\'\}>'
        r'\$\{escapeHtml\(provider\.name \|\| provider\.id\)\}</option>`'
    )
    legacy_hits = legacy_pattern.findall(src)
    assert len(legacy_hits) >= 3, (
        f"canvas.js legacy 内联 fallback 应保留 3 处 (chatProviderOptions / "
        f"providerOptions / videoProviderOptions), 实际: {len(legacy_hits)}"
    )


def test_t68_smart_canvas_chat_provider_options_not_yet_migrated():
    """事实断言: smart-canvas.js:2362 chatProviderOptions **暂未** 迁移到
    ProviderSelector seam. PR-9 保守渲染层只迁移 canvas.js 3 处;smart-canvas.js
    的 chatProviderOptions body 与 canvas.js 相同, 但独立函数 —— 迁移策略与
    canvas.js 主入口区分, 待 CB-P5-09 或 PR-11+ 独立承接.

    此断言记录当前状态, 若未来 smart-canvas.js 被 PR-11 迁移, 此断言应更新
    为 seam consumer 断言 (对齐 canvas.js T68 pattern).
    """
    src = SMART_CANVAS_JS.read_text(encoding="utf-8")
    assert "ProviderSelector" not in src, (
        "smart-canvas.js 现引用 ProviderSelector; 请更新迁移断言 "
        "(smart-canvas.js:2362 chatProviderOptions 已迁移 → 应用 seam consumer 断言)"
    )
    # smart-canvas.js:2362 chatProviderOptions 定义仍在 legacy 模式
    assert "function chatProviderOptions" in src, (
        "smart-canvas.js chatProviderOptions 定义丢失, PR-9 断言前提破坏"
    )


# -------------------------------------------------------------------------
# T69 XSS sink 反注入 + provider name fallback + null-safe
# -------------------------------------------------------------------------
def test_t69_xss_sink_and_edge_cases():
    # (a) XSS sentinel 覆盖矩阵
    xss = json.loads((FIXTURES / "xss_sink_provider_name.json").read_text(encoding="utf-8"))
    seam = _run_node_esm(
        f"""
        import ProviderSelector from '{PS_INDEX}';
        console.log(JSON.stringify({{v: ProviderSelector.renderHtml(
            {json.dumps(xss['variant'])}, {json.dumps(xss['providers'])},
            {json.dumps(xss['selectedId'])}
        )}}));
        """
    )
    for esc in xss["must_contain_escaped"]:
        assert esc in seam["v"], (
            f"XSS sentinel 缺失 escape 输出 {esc!r}: {seam['v']!r}"
        )
    for raw in xss["must_not_contain"]:
        assert raw not in seam["v"], (
            f"XSS sentinel 泄漏原始 sink {raw!r}: {seam['v']!r}"
        )

    # (b) escapeHtml runtime-output-byte-equal 于 canvas.js
    src = PS_OPTS_PATH.read_text(encoding="utf-8")
    ps_escape_html = _extract_function_source(src, "escapeHtml")
    assert ps_escape_html, "ProviderSelector providerOptions.js escapeHtml 未提取到"
    canvas_fn = _extract_function_source(
        CANVAS_JS.read_text(encoding="utf-8"), "escapeHtml"
    )
    for inp in ["<script>", "\" & '", "safe", None, ""]:
        ps_out = _run_node_cjs(
            ps_escape_html + f"\nconsole.log(JSON.stringify({{v: escapeHtml({json.dumps(inp)})}}));"
        )
        canvas_out = _run_node_cjs(
            canvas_fn + f"\nconsole.log(JSON.stringify({{v: escapeHtml({json.dumps(inp)})}}));"
        )
        assert ps_out["v"] == canvas_out["v"], (
            f"ProviderSelector.escapeHtml 未 runtime-output-byte-equal 于 canvas.js:\n"
            f"  input:      {inp!r}\n"
            f"  ProviderSelector: {ps_out['v']!r}\n"
            f"  canvas.js:  {canvas_out['v']!r}"
        )

    # (c) provider name 缺失时 fallback to id
    fallback = json.loads((FIXTURES / "name_fallback_to_id.json").read_text(encoding="utf-8"))
    seam2 = _run_node_esm(
        f"""
        import ProviderSelector from '{PS_INDEX}';
        console.log(JSON.stringify({{v: ProviderSelector.renderHtml(
            {json.dumps(fallback['variant'])}, {json.dumps(fallback['providers'])},
            {json.dumps(fallback['selectedId'])}
        )}}));
        """
    )
    assert seam2["v"] == fallback["expected_html"], (
        f"provider name 缺失 fallback 未生效:\n"
        f"  实际: {seam2['v']!r}\n"
        f"  期望: {fallback['expected_html']!r}"
    )

    # (d) event handler attribute 抗回归 (renderHtml 输出中不新增 on* handler)
    handler_re = re.compile(r'\son\w+\s*=\s*"[^"]*"')
    for candidate in [seam["v"], seam2["v"]]:
        assert not handler_re.search(candidate), (
            f"ProviderSelector.renderHtml 输出含 event handler attribute: {candidate!r}"
        )
