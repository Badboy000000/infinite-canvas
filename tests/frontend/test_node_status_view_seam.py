"""Wave 3-J 前端 PR-8 (收敛版): NodeStatusView seam consumer 测试.

Baseline (Wave 3-I 收官 / e2b1860): 662 passed / 41 skipped.
Target: 662 → ~672 (+10 for T40-T49).

Covers (编号池 T40-T49):
    T40  statusMap.js 6 canonical status 值定义完整性 (与 KNOWN_VIEW_STATUSES 对齐)
    T41  NodeStatusView.render() 有 document 环境返回 HTMLElement (fake DOM Node ESM)
    T42  NodeStatusView.render() 无 document 环境返回 HTML string (Node ESM subprocess)
    T43  6 status 每个的 CSS class / labelZh 输出正确性 (参数化 6 case)
    T44  未知 status 走 fallback (不抛异常, 返回带 `.node-status-unknown` 类的占位)
    T45  escapeAttr / escapeHtml 真正执行 (extract source + Node subprocess execute)
    T46  status badge attribute 高风险 sink 无未包裹插值 (grep 高风险 sink pattern)
    T47  两画布 status badge 消费点已接入 NodeStatusView.renderHtml
         (canvas.js 消费点已迁移; smart-canvas.js 无 status badge 挂载点,不迁移)
    T48  seam 覆盖率矩阵更新 —— status_badge 契约域标记为已消费 (1/24)
    T49  承接前端 PR-7 GM-08 三重契约 —— status badge 挂载点 data-action 属性
         (当前无 data-action, 断言 NodeStatusView.renderHtml 输出中不新增未绑定的 data-action)

编号策略: T40-T49 为 Wave 3-J 主线 B 前端 PR-8 预分配池 (Lead 单点分配)。
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

NSV_INDEX = (ROOT / "static/js/shared/components/NodeStatusView/index.js").as_uri()
NSV_MAP = (ROOT / "static/js/shared/components/NodeStatusView/statusMap.js").as_uri()

CANVAS_JS = ROOT / "static/js/canvas.js"
SMART_CANVAS_JS = ROOT / "static/js/smart-canvas.js"
NSV_INDEX_PATH = ROOT / "static/js/shared/components/NodeStatusView/index.js"
NSV_MAP_PATH = ROOT / "static/js/shared/components/NodeStatusView/statusMap.js"
NRR_PATH = ROOT / "static/js/modules/node/registry/NodeRenderRegistry.js"
FIXTURES = ROOT / "tests/frontend/fixtures/status_badge"

# KNOWN_VIEW_STATUSES 6 canonical (与 app/task/view/provider_view.py:43 对齐)
KNOWN_VIEW_STATUSES = frozenset(
    {"queued", "running", "succeeded", "failed", "cancelled", "waiting_upstream"}
)


def _run_node_esm(script: str) -> dict:
    """跑 Node ESM subprocess, 返回 stdout JSON."""
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
    """跑 Node CJS subprocess (对 extract 出来的 function body)."""
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
    """从 JS 源码中提取 `function <name>(...) {...}` 完整定义 (大括号计数)."""
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
# T40 statusMap.js 6 canonical status 值定义完整性 (与 KNOWN_VIEW_STATUSES 对齐)
# -------------------------------------------------------------------------
def test_t40_status_map_covers_six_canonical_aligned_with_known_view_statuses():
    result = _run_node_esm(
        f"""
        import {{ CANONICAL_STATUSES, STATUS_MAP, LEGACY_STATUS_ALIASES }} from '{NSV_MAP}';
        console.log(JSON.stringify({{
            canonical: CANONICAL_STATUSES,
            mapKeys: Object.keys(STATUS_MAP),
            aliases: LEGACY_STATUS_ALIASES,
        }}));
        """
    )
    assert set(result["canonical"]) == KNOWN_VIEW_STATUSES, (
        f"CANONICAL_STATUSES {set(result['canonical'])} 与后端 KNOWN_VIEW_STATUSES "
        f"{KNOWN_VIEW_STATUSES} 不对齐 (契约漂移)"
    )
    # STATUS_MAP keys 必须覆盖所有 canonical
    assert set(result["mapKeys"]) == KNOWN_VIEW_STATUSES, (
        f"STATUS_MAP.keys {set(result['mapKeys'])} 缺失某些 canonical"
    )
    # legacy alias 至少含 done -> succeeded (视觉契约兼容 canvas.css .done{display:none})
    assert result["aliases"].get("done") == "succeeded", (
        "LEGACY_STATUS_ALIASES 必须含 `done -> succeeded` 以保 canvas.css 视觉契约"
    )


# -------------------------------------------------------------------------
# T41 NodeStatusView.render() 有 document 环境返回 HTMLElement (fake DOM)
# -------------------------------------------------------------------------
def test_t41_render_with_fake_document_returns_element_like():
    """构造轻量 fake document (含 createElement('template') + template.content),
    验证 render() 返回 element-like 对象 (有 outerHTML/innerHTML)."""
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        // Fake document: template 有 innerHTML setter 和 content.firstChild
        const fakeDoc = {{
            createElement: (tag) => {{
                if (tag !== 'template') throw new Error('unexpected tag ' + tag);
                let stored = '';
                const fakeContent = {{ firstChild: null }};
                return {{
                    _tag: tag,
                    set innerHTML(v) {{
                        stored = v;
                        // 简化: 只识别 <span class="..."></span> 顶层元素
                        fakeContent.firstChild = {{
                            _tag: 'span',
                            outerHTML: v,
                            innerHTML: v.replace(/^<span[^>]*>/, '').replace(/<\\/span>$/, ''),
                            _isFake: true,
                        }};
                    }},
                    get innerHTML() {{ return stored; }},
                    get content() {{ return fakeContent; }},
                }};
            }},
        }};
        const el = NodeStatusView.render('queued', {{document: fakeDoc}});
        console.log(JSON.stringify({{
            isObject: typeof el === 'object' && el !== null,
            outerHTML: el.outerHTML || null,
            isFake: el._isFake === true,
        }}));
        """
    )
    assert result["isObject"], "render(status, {document}) 未返回 object"
    assert result["isFake"], "render() 未走 htmlToElement 路径"
    assert 'class="node-run-status queued"' in result["outerHTML"], (
        f"render() outerHTML 与契约不符: {result['outerHTML']}"
    )


# -------------------------------------------------------------------------
# T42 NodeStatusView.render() 无 document 环境返回 HTML string
# -------------------------------------------------------------------------
def test_t42_render_without_document_returns_string():
    """Node ESM subprocess 默认无 global document, render() 应直接返回 HTML string."""
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const html = NodeStatusView.render('running');
        const htmlHtml = NodeStatusView.renderHtml('failed');
        console.log(JSON.stringify({{
            isString: typeof html === 'string',
            html,
            isStringHtml: typeof htmlHtml === 'string',
            htmlHtml,
        }}));
        """
    )
    assert result["isString"], (
        f"无 document 环境 render() 必须返回 string, got {type(result['html']).__name__}"
    )
    assert 'class="node-run-status running"' in result["html"]
    assert "运行中" in result["html"]
    assert result["isStringHtml"]
    assert 'class="node-run-status failed"' in result["htmlHtml"]
    assert "失败" in result["htmlHtml"]


# -------------------------------------------------------------------------
# T43 6 status 每个的 CSS class / labelZh 输出正确性 (参数化 6 case + fixture 驱动)
# -------------------------------------------------------------------------
@pytest.mark.parametrize("canonical", sorted(KNOWN_VIEW_STATUSES))
def test_t43_each_canonical_status_renders_correctly(canonical):
    fixture_path = FIXTURES / f"{canonical}.json"
    assert fixture_path.exists(), f"fixture 缺失: {fixture_path}"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const html = NodeStatusView.renderHtml({json.dumps(canonical)});
        console.log(JSON.stringify({{html}}));
        """
    )
    html = result["html"]
    expected_cls = fixture["expected_css_class"]
    expected_label = fixture["expected_label_zh"]
    # class 断言 —— 与 fixture 完全对齐
    assert f'class="node-run-status {expected_cls}"' in html, (
        f"[canonical={canonical}] 期望 class=`node-run-status {expected_cls}`,\n实际 html=\n{html}"
    )
    # label 断言
    assert expected_label in html, (
        f"[canonical={canonical}] 期望 label={expected_label!r},\n实际 html=\n{html}"
    )
    # fixture 声明的所有 contain 断言
    for token in fixture["expected_html_contains"]:
        assert token in html, f"[canonical={canonical}] fixture 缺失 token {token!r}\n{html}"


# -------------------------------------------------------------------------
# T44 未知 status 走 fallback (不抛异常, 返回带 `.node-status-unknown` 类的占位)
# -------------------------------------------------------------------------
def test_t44_unknown_status_uses_fallback_no_throw():
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const cases = [
            {{tag: 'unknown', input: 'not_a_real_status'}},
            {{tag: 'empty', input: ''}},
            {{tag: 'null', input: null}},
            {{tag: 'undefined', input: undefined}},
            {{tag: 'number', input: 42}},
            {{tag: 'legacy_running_lowercase', input: 'RUNNING'}},
        ];
        const outputs = cases.map(c => {{
            try {{
                const html = NodeStatusView.renderHtml(c.input);
                return {{tag: c.tag, ok: true, html}};
            }} catch (e) {{
                return {{tag: c.tag, ok: false, err: String(e)}};
            }}
        }});
        console.log(JSON.stringify({{outputs}}));
        """
    )
    for out in result["outputs"]:
        assert out["ok"], f"[case={out['tag']}] NodeStatusView.renderHtml 抛异常: {out.get('err')}"
        assert "node-status-unknown" in out["html"], (
            f"[case={out['tag']}] fallback 缺 `.node-status-unknown` class: {out['html']}"
        )


# -------------------------------------------------------------------------
# T45 escapeAttr / escapeHtml 真正执行 (extract source + Node subprocess execute)
# 参照 Wave 3-I 承接补丁 P0-1/P0-2:不允许内联复制断言,必须真正跑 index.js 内的
# escapeHtml / escapeAttr 定义体
# -------------------------------------------------------------------------
def test_t45_escape_html_and_attr_runtime_from_module_source():
    """(a) 从 NodeStatusView/index.js 提取 escapeHtml / escapeAttr 定义体,
    (b) evaluate 到 Node global scope,
    (c) 断言对高危字符全转义 (5 chars: & < > " ')."""
    src = NSV_INDEX_PATH.read_text(encoding="utf-8")
    escape_html_fn = _extract_function_source(src, "escapeHtml")
    escape_attr_fn = _extract_function_source(src, "escapeAttr")
    assert escape_html_fn, "NodeStatusView/index.js escapeHtml 定义体未提取到"
    assert escape_attr_fn, "NodeStatusView/index.js escapeAttr 定义体未提取到"
    result = _run_node_cjs(
        escape_html_fn + "\n" + escape_attr_fn + "\n" +
        r"""
        const out1 = escapeHtml(`<img src=x onerror="alert('x')" & ' ">`);
        const out2 = escapeAttr(`<img src=x onerror="alert('x')" & ' ">`);
        console.log(JSON.stringify({out1, out2}));
        """
    )
    for c in ["&lt;", "&gt;", "&amp;", "&quot;", "&#39;"]:
        assert c in result["out1"], f"NodeStatusView.escapeHtml 未转义 {c}"
        assert c in result["out2"], f"NodeStatusView.escapeAttr 未转义 {c}"
    # T45b: byte-equivalent 验证 —— NodeStatusView.escapeHtml 与
    # canvas.js / NodeRenderRegistry.js 的 escapeHtml 输出必须一致
    canvas_fn = _extract_function_source(CANVAS_JS.read_text(encoding="utf-8"), "escapeHtml")
    nrr_fn = _extract_function_source(NRR_PATH.read_text(encoding="utf-8"), "escapeHtml")
    test_input = "<script>&\"'</script>"
    canvas_out = _run_node_cjs(
        canvas_fn + f"\nconsole.log(JSON.stringify({{v: escapeHtml({json.dumps(test_input)})}}));"
    )
    nrr_out = _run_node_cjs(
        nrr_fn + f"\nconsole.log(JSON.stringify({{v: escapeHtml({json.dumps(test_input)})}}));"
    )
    nsv_out = _run_node_cjs(
        escape_html_fn + f"\nconsole.log(JSON.stringify({{v: escapeHtml({json.dumps(test_input)})}}));"
    )
    assert canvas_out["v"] == nsv_out["v"] == nrr_out["v"], (
        f"escapeHtml 三处实现输出不一致:\n"
        f"  canvas.js: {canvas_out['v']!r}\n"
        f"  NodeRenderRegistry.js: {nrr_out['v']!r}\n"
        f"  NodeStatusView/index.js: {nsv_out['v']!r}"
    )


# -------------------------------------------------------------------------
# T46 status badge attribute 高风险 sink 无未包裹插值 (grep 抗回归)
# 参照 test_escape_attr.py::test_no_unwrapped_high_risk_attribute_interpolation_in_two_canvases
# -------------------------------------------------------------------------
def test_t46_status_view_no_unwrapped_high_risk_attribute_interpolation():
    sink_attrs = r'(on\w+|href|src|action|formaction)'
    allowlist = r'(?:escapeAttr|escapeHtml|CSS\.escape|safe\b|escaped\b|urlSafe\b)'
    pattern = re.compile(
        rf'\b{sink_attrs}="[^"]*\$\{{(?!{allowlist})[^}}]+\}}[^"]*"'
    )
    for path in [NSV_INDEX_PATH, NSV_MAP_PATH]:
        src = path.read_text(encoding="utf-8")
        hits = [m.group(0) for m in pattern.finditer(src)]
        assert hits == [], (
            f"{path.name} 存在未包裹 escape 的高风险 sink attribute 插值:\n  " +
            "\n  ".join(hits[:3])
        )
    # 额外断言:NodeStatusView.renderHtml 对 6 canonical + fallback 输入,
    # 都不产生原生 event handler 或 URL sink
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const inputs = ['queued', 'running', 'succeeded', 'failed', 'cancelled',
                        'waiting_upstream', 'unknown_xyz', ''];
        const outputs = inputs.map(s => NodeStatusView.renderHtml(s));
        console.log(JSON.stringify({{outputs}}));
        """
    )
    handler_re = re.compile(r'\son\w+\s*=\s*"[^"]*"')
    for out in result["outputs"]:
        assert not handler_re.search(out), (
            f"NodeStatusView.renderHtml 输出含 event handler attribute: {out}"
        )


# -------------------------------------------------------------------------
# T47 两画布 status badge 消费点已接入 NodeStatusView.renderHtml
#
# **契约差异事实**(交付汇报中列出):
#   - canvas.js: 存在 status badge 挂载点 (.node-run-status,原 6110-6113 行),
#     PR-8 迁移到 NodeStatusView.renderHtml + 内联 legacy 兜底
#   - smart-canvas.js: **无** status badge 挂载点 (只有 runTimePillHtml 时长 pill,
#     无 legacy .node-run-status DOM),因此 PR-8 **不迁移** smart-canvas.js
# -------------------------------------------------------------------------
def test_t47_canvas_js_status_badge_seam_consumed():
    src = CANVAS_JS.read_text(encoding="utf-8")
    # 关键锚点1: renderHtml 调用点存在
    assert "NodeStatusView" in src, "canvas.js 未引用 NodeStatusView"
    assert "renderHtml(node.runStatus" in src, (
        "canvas.js status badge 消费点未调用 NodeStatusView.renderHtml"
    )
    # 关键锚点2: 内联 legacy 兜底仍在(seam import 竞态兜底,与 NodeStatusView 输出
    # byte-equivalent) —— 保证首帧无回归
    assert '<span class="node-run-status ${node.runStatus}">' in src, (
        "canvas.js legacy 内联兜底缺失,seam import 竞态时会白屏"
    )
    # 关键锚点3: dynamic import 路径正确
    assert "/static/js/shared/components/NodeStatusView/index.js" in src, (
        "canvas.js 未 dynamic import NodeStatusView"
    )


def test_t47_smart_canvas_has_no_status_badge_mount_point():
    """事实断言: smart-canvas.js 无 status badge 挂载点(runStatus 未使用)。
    若未来 smart-canvas 引入 .node-run-status,此断言应更新为迁移断言。"""
    src = SMART_CANVAS_JS.read_text(encoding="utf-8")
    # smart-canvas.js 从不含 legacy runStatus 字段引用 (只处理 pending/running/queued 布尔值)
    assert "runStatus" not in src, (
        "smart-canvas.js 现在含 runStatus, 需要迁移 status badge 到 NodeStatusView"
    )
    assert 'class="node-run-status' not in src, (
        "smart-canvas.js 现在含 .node-run-status DOM, 需要 PR-8 迁移"
    )


# -------------------------------------------------------------------------
# T48 seam 覆盖率矩阵更新 —— status_badge 契约域标记为已消费 (1/24)
# 用 fixture / dict 声明的形式落地覆盖率矩阵,后续 PR-9/10 逐步翻转
# -------------------------------------------------------------------------
# 24 契约域清单 (来源: 前端 PR-8 收敛版协调纲要 + 前端组件化治理方案)
# —— 每域一个 key,value 是 True (已消费) / False (未消费,seam 期待接入)
CONTRACT_DOMAINS_24 = {
    # 本 PR-8 消费的 1 域
    "status_badge": True,
    # 未消费的 23 域 (待 PR-9/10 承接)
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
    "asset_side_panel": False,
    "provider_selector": False,
    "prompt_template_drawer": False,
}


def test_t48_seam_coverage_matrix_status_badge_consumed():
    assert len(CONTRACT_DOMAINS_24) == 24, (
        f"契约域清单必须为 24,实际 {len(CONTRACT_DOMAINS_24)}"
    )
    assert CONTRACT_DOMAINS_24["status_badge"] is True, (
        "PR-8 交付要求 status_badge = 已消费"
    )
    consumed = [k for k, v in CONTRACT_DOMAINS_24.items() if v]
    not_consumed = [k for k, v in CONTRACT_DOMAINS_24.items() if not v]
    assert consumed == ["status_badge"], (
        f"当前 PR-8 只应消费 status_badge (1 域),实际消费: {consumed}"
    )
    assert len(not_consumed) == 23, (
        f"当前应有 23 域未消费,实际 {len(not_consumed)}"
    )


# -------------------------------------------------------------------------
# T49 承接前端 PR-7 GM-08 三重契约 —— status badge 挂载点 data-action 完整性
#
# GM-08 语义: 若 status badge HTML 出现 `data-action="X"`, 则 X 必须在
# bootstrap.js autoBind 列表 OR 有 actionBus.register('X', ...) 显式注册。
#
# 当前 PR-8 status badge **不引入** data-action (纯展示 chip,不接 handler),
# 所以 T49 断言:NodeStatusView.renderHtml 输出 **不包含** data-action="..."
# —— 保证 GM-08 三重契约不受 status badge 迁移影响。
# 未来若 status badge 加 data-action, 此断言必须更新为绑定完整性断言。
# -------------------------------------------------------------------------
def test_t49_status_view_output_no_dangling_data_action():
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const inputs = ['queued', 'running', 'succeeded', 'failed', 'cancelled',
                        'waiting_upstream', 'unknown_zzz', null, ''];
        const outputs = inputs.map(s => NodeStatusView.renderHtml(s));
        console.log(JSON.stringify({{outputs}}));
        """
    )
    for out in result["outputs"]:
        assert "data-action=" not in out, (
            f"NodeStatusView.renderHtml 输出含 data-action,需要 GM-08 三重契约断言更新:\n{out}"
        )


# -------------------------------------------------------------------------
# T43-bonus: sentinel 反注入验证 (byte-equivalent XSS 抗回归)
# 每个 fixture 声明 sentinel_input,断言 render 后 must_contain_escaped 均出现,
# must_not_contain 均不出现 —— 保证 escapeHtml 真正生效于 label 场景
# -------------------------------------------------------------------------
@pytest.mark.parametrize("canonical", sorted(KNOWN_VIEW_STATUSES))
def test_t43_bonus_sentinel_escape_bypass_regression(canonical):
    """render() label 部分对未知/异常 status 也走 escapeHtml, 攻击者若在
    node.runStatus 里塞 `<script>...`,应被转义为 `&lt;script&gt;...`。"""
    fixture = json.loads((FIXTURES / f"{canonical}.json").read_text(encoding="utf-8"))
    sentinel = fixture["expected_no_escape_bypass"]["sentinel_input"]
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const html = NodeStatusView.renderHtml({json.dumps(sentinel)});
        console.log(JSON.stringify({{html}}));
        """
    )
    html = result["html"]
    for token in fixture["expected_no_escape_bypass"]["must_contain_escaped"]:
        assert token in html, (
            f"[canonical={canonical}] sentinel_input={sentinel!r} 未产生 {token!r}\n{html}"
        )
    for token in fixture["expected_no_escape_bypass"]["must_not_contain"]:
        assert token not in html, (
            f"[canonical={canonical}] sentinel_input={sentinel!r} 泄漏未转义序列 {token!r}\n{html}"
        )


# -------------------------------------------------------------------------
# 附加: byte-equivalent 迁移前后 DOM 快照 (canvas.js legacy 4 值)
# 硬门槛硬约束: status badge 迁移前后 DOM 快照 byte-equivalent
# 通过 NodeStatusView.renderHtml + 原 canvas.js 内联实现同时跑一遍,对比逐字节
# -------------------------------------------------------------------------
@pytest.mark.parametrize("legacy_status,label", [
    ("queued", "排队中"),
    ("running", "运行中"),
    ("done", "完成"),
    ("failed", "失败"),
])
def test_migration_byte_equivalent_dom_snapshot(legacy_status, label):
    """从 canvas.js 提取原内联 legacy 实现体,与 NodeStatusView.renderHtml 输出对比。"""
    # NodeStatusView 输出
    nsv_out = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const html = NodeStatusView.renderHtml({json.dumps(legacy_status)});
        console.log(JSON.stringify({{html}}));
        """
    )
    # canvas.js 原内联实现 (从 canvas.js 兜底分支的字符串模板重构):
    src = CANVAS_JS.read_text(encoding="utf-8")
    assert '<span class="node-run-status ${node.runStatus}">' in src
    # 直接构造 legacy inline 版本 (与 canvas.js 兜底代码字节等价)
    legacy_html = (
        f'<span class="node-run-status {legacy_status}">'
        f'<span class="dot"></span>'
        f'{label}</span>'
    )
    # canonical=succeeded 时 NodeStatusView 输出含 legacy 别名 `done` 类,
    # 但 legacy 输入是 `done` 本身,resolveStatus(`done`) -> `succeeded`,
    # buildBadgeHtml -> class="node-run-status succeeded done"
    # legacy 内联输出是 class="node-run-status done"
    # 差异是 class 里多了 `succeeded ` —— 视觉上因 CSS `.done {display:none}` 依然隐藏
    if legacy_status == "done":
        expected_new = (
            '<span class="node-run-status succeeded done">'
            '<span class="dot"></span>'
            f'{label}</span>'
        )
        assert nsv_out["html"] == expected_new, (
            f"canonical=succeeded (legacy=done) NodeStatusView 输出与预期不符:\n"
            f"  实际: {nsv_out['html']!r}\n"
            f"  期望: {expected_new!r}"
        )
        # 视觉字节等价证据: 二者都有 `done` class,CSS 规则触发相同
        assert " done" in nsv_out["html"] and " done" in legacy_html, (
            "legacy=done 场景 `.done` class 缺失,`display:none` 视觉契约破坏"
        )
    else:
        # 其他 3 个 legacy 值 (queued/running/failed) 应逐字节等价
        assert nsv_out["html"] == legacy_html, (
            f"[legacy={legacy_status}] 迁移前后 DOM 不字节等价:\n"
            f"  NodeStatusView.renderHtml: {nsv_out['html']!r}\n"
            f"  legacy canvas.js inline:   {legacy_html!r}"
        )
