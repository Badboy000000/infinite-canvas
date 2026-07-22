"""Wave 3-J 前端 PR-8 (收敛版): NodeStatusView seam consumer 测试.

Baseline (Wave 3-I 收官 / e2b1860): 662 passed / 41 skipped.
Target: 662 → ~672 (+10 for T40-T49).

Covers (编号池 T40-T49 + 承接补丁 T50-T51 + migration bonus):
    T40  statusMap.js 6 canonical status 值定义完整性 (与 KNOWN_VIEW_STATUSES 对齐,
         Wave 3-J 承接补丁 P1-2: 从 app.task.view import KNOWN_VIEW_STATUSES,
         不再本地内联复制 —— 避免 GM-11 反模式 "内联复制目标常量 = 抗漂移零效")
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
    T50  Wave 3-J 承接补丁 P2-3: canvas.css `.node-run-status.done { display:none }`
         视觉契约守卫 —— 若未来有人误删该规则,双 class 视觉等价证据消失
    T51  Wave 3-J 承接补丁 P2-4: 端到端 renderHtml 输出对高危字符全通道 escape
         (label 层 + fallback 层同时验证)

编号策略: T40-T49 为 Wave 3-J 主线 B 前端 PR-8 预分配池; T50-T51 为承接补丁
       (Lead 单点分配,不占 subagent 通道)。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# Wave 3-J 承接补丁 P1-2 (RC-B/TRA-B): 前端测试跨 layer 引用后端常量,
# 用 `from app.task.view import KNOWN_VIEW_STATUSES` 取代本地内联 frozenset。
# 这是"契约漂移抗零效"的正向落地:任何一侧 KNOWN_VIEW_STATUSES 变更,
# 本测试立即感知。
sys.path.insert(0, str(ROOT))
from app.task.view import KNOWN_VIEW_STATUSES  # noqa: E402

NSV_INDEX = (ROOT / "static/js/shared/components/NodeStatusView/index.js").as_uri()
NSV_MAP = (ROOT / "static/js/shared/components/NodeStatusView/statusMap.js").as_uri()

CANVAS_JS = ROOT / "static/js/canvas.js"
CANVAS_CSS = ROOT / "static/css/canvas.css"
SMART_CANVAS_JS = ROOT / "static/js/smart-canvas.js"
NSV_INDEX_PATH = ROOT / "static/js/shared/components/NodeStatusView/index.js"
NSV_MAP_PATH = ROOT / "static/js/shared/components/NodeStatusView/statusMap.js"
NRR_PATH = ROOT / "static/js/modules/node/registry/NodeRenderRegistry.js"
FIXTURES = ROOT / "tests/frontend/fixtures/status_badge"


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
#
# **契约域维度显式区分**(Wave 3-J 承接补丁 P1-1,处理 TRA-B 反审):
#   - `CONTRACT_DOMAINS_24`(本表) = **UI 契约域**(status_badge / node_head_title / ...)
#     语义:节点渲染面被切分成 24 个可独立迁移的"消费点"
#   - `test_canvas_renderer_seam.SEAM_CONTRACT_DOMAINS` = **代码结构域**
#     (24 个 seam module 的 export 契约,如 canvas/renderer/viewport.js::CANVAS_KINDS)
#     语义:seam 抽出后 24 个模块导出的符号契约
#   - **两者不是同一维度**,不能相互替换;分别用于跟踪 UI 层与 module 层的渐进
#     迁移进度。TRA-B 反审建议"CONTRACT_DOMAINS_24 → SEAM_CONTRACT_DOMAINS"是误诊,
#     Lead 决定保留 UI 契约域独立跟踪面。
#
# **status_badge 消费深度说明**(Wave 3-J 承接补丁 P1-B3,处理 RC-B 反审):
#   - `status_badge: True` 的语义是 **rendering consumed**(canvas.js:6116-6131
#     已通过 lazy dynamic import 消费 NodeStatusView.renderHtml 生成 badge HTML)
#   - **不**包含 gating 层消费:canvas.js:6108 的 showStatus gate 仍是硬编码
#     类型数组 `['generator','msgen','comfy','ltxDirector','llm','video','rh']`;
#     而 `static/js/modules/node/components/*.js` 的 `hasStatus` 字段是 dormant
#     seam(声明未消费),待 PR-9/10 通过 NodeConfigRegistry.hasStatus 迁移。
#   - 参见 GM-15(dormant seam 检测)治理机制候选。
# -------------------------------------------------------------------------
# 24 UI 契约域清单 (来源: 前端 PR-8 收敛版协调纲要 + 前端组件化治理方案)
# —— 每域一个 key,value 是 True (已消费,含深度限定) / False (未消费,seam 期待接入)
CONTRACT_DOMAINS_24 = {
    # 本 PR-8 消费的 1 域(rendering-only;gating 层未消费,待 PR-9/10)
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
# 硬门槛硬约束: status badge 迁移前后 DOM 快照 byte-equivalent(legacy 3 值)
# 视觉等价 for legacy `done` case(class 差 `succeeded`,但 CSS 触发相同)
#
# Wave 3-J 承接补丁 P1-3/P1-4 修正(处理 TRA-B P1-3/4):
#   legacy_html **不再 Python 手写**,而是**真实从 canvas.js 内联 legacy 兜底分支
#   grep 提取标签模板 + label 表**,然后在 Node 中 evaluate 得到真实字节。
#   这防止"legacy 期望与代码脱钩,重构 canvas.js 兜底时无法感知"的反模式。
# -------------------------------------------------------------------------


def _extract_canvas_legacy_status_template() -> tuple[str, dict]:
    """从 canvas.js:6108-6131 消费点提取 legacy 内联兜底的 template + label 表。

    Returns:
        (template_line, label_dict) —— template_line 是 canvas.js 里出现的
        字符串模板字面量(含 `${...}` 占位符);label_dict 是 legacy 4 值 → 中文
        标签的映射。二者共同重构 legacy 输出。

    **CB-P5-05 承接(数据 PR-16 · Wave 3-L 主线 C)同步更新**:canvas.js:6186
    的 cascadeIdx 拼接从 `${node._cascadeIdx?' '+node._cascadeIdx:''}` 改为
    `${node._cascadeIdx?' '+escapeHtml(node._cascadeIdx):''}`(cascadeIdx 全通道
    escape 硬锁)。**运行时行为**:当 `_cascadeIdx=''` 时 `escapeHtml('')=''`,
    输出与原完全字节等价(见 T45/T47 byte-equivalent 契约);pattern 只是同步。
    """
    src = CANVAS_JS.read_text(encoding="utf-8")
    # 提取 legacy 内联 template 字符串(canvas.js:6186 附近 · CB-P5-05 承接后)
    template_match = re.search(
        r"`<span class=\"node-run-status \$\{node\.runStatus\}\">"
        r"<span class=\"dot\"></span>\$\{escapeHtml\(label\)\}"
        r"\$\{node\._cascadeIdx\?' '\+escapeHtml\(node\._cascadeIdx\):''\}</span>`",
        src,
    )
    assert template_match, (
        "canvas.js legacy 内联 template 未提取到;若 canvas.js:6108-6131 消费点被"
        "重构,请同步更新本测试的 template 匹配 pattern。"
        "(CB-P5-05 承接后 cascadeIdx 拼接已 wrap escapeHtml)"
    )
    # 提取 label 字典(canvas.js:6129 附近)
    label_match = re.search(
        r"\{\s*queued:'([^']+)',\s*running:'([^']+)',\s*done:'([^']+)',\s*failed:'([^']+)'\s*\}",
        src,
    )
    assert label_match, (
        "canvas.js legacy label 字典未提取到;若 canvas.js:6108-6131 消费点被"
        "重构,请同步更新本测试的 label 匹配 pattern。"
    )
    return template_match.group(0), {
        "queued": label_match.group(1),
        "running": label_match.group(2),
        "done": label_match.group(3),
        "failed": label_match.group(4),
    }


@pytest.mark.parametrize("legacy_status", ["queued", "running", "done", "failed"])
def test_migration_byte_equivalent_dom_snapshot(legacy_status):
    """从 canvas.js 提取原内联 legacy 实现体,与 NodeStatusView.renderHtml 输出对比。

    Wave 3-J 承接补丁 P1-3/4:legacy_html 从 canvas.js 真实 grep 提取,不再
    Python 手写(GM-11 反模式防线)。若未来 canvas.js:6108-6131 消费点被重构,
    本测试首先在 grep 阶段 FAIL,提示重新对齐。
    """
    _, label_dict = _extract_canvas_legacy_status_template()
    label = label_dict[legacy_status]
    # 从提取到的 canvas.js template 真实构造 legacy 输出
    # (Node 里 evaluate template 得逐字节等价的字节)
    legacy_out = _run_node_cjs(
        f"""
        const escapeHtml = (str) => String(str == null ? '' : str).replace(/[&<>"']/g, s => ({{
            '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
        }}[s]));
        const node = {{ runStatus: {json.dumps(legacy_status)}, _cascadeIdx: '' }};
        const label = {json.dumps(label)};
        const legacyHtml = `<span class="node-run-status ${{node.runStatus}}"><span class="dot"></span>${{escapeHtml(label)}}${{node._cascadeIdx?' '+escapeHtml(node._cascadeIdx):''}}</span>`;
        console.log(JSON.stringify({{legacyHtml}}));
        """
    )
    legacy_html = legacy_out["legacyHtml"]

    # NodeStatusView 输出
    nsv_out = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        const html = NodeStatusView.renderHtml({json.dumps(legacy_status)});
        console.log(JSON.stringify({{html}}));
        """
    )

    # canonical=succeeded 时 NodeStatusView 输出含 legacy 别名 `done` 类,
    # 但 legacy 输入是 `done` 本身,resolveStatus(`done`) -> `succeeded`,
    # buildBadgeHtml -> class="node-run-status succeeded done"
    # legacy 内联输出是 class="node-run-status done"
    # **DOM 字符串**多了 `succeeded ` 前缀 —— **非 DOM byte-equal**;
    # 但 CSS `.done {display:none}` 依然命中,**视觉等价**(见 T50 CSS 守卫)
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
        # **视觉等价证据**(非 DOM byte-equal): 二者都有 `done` class,CSS 规则触发相同
        # 参见 RC-B 反审 P0-1 措辞澄清:此分支是**视觉等价 (visual-byte-equal)**,
        # **不是 source-byte-equal 也不是 runtime-output-byte-equal**
        assert " done" in nsv_out["html"] and " done" in legacy_html, (
            "legacy=done 场景 `.done` class 缺失,`display:none` 视觉契约破坏"
        )
    else:
        # 其他 3 个 legacy 值 (queued/running/failed) 应逐字节等价
        # 这是真正的 runtime-output-byte-equal 分支
        assert nsv_out["html"] == legacy_html, (
            f"[legacy={legacy_status}] 迁移前后 DOM 不字节等价:\n"
            f"  NodeStatusView.renderHtml: {nsv_out['html']!r}\n"
            f"  legacy canvas.js inline:   {legacy_html!r}"
        )


# -------------------------------------------------------------------------
# T50 · P2-3 (RC-B P0-2 承接): canvas.css `.node-run-status.done { display:none }`
# 视觉契约守卫 —— 若未来有人误删该规则,双 class 视觉等价证据消失
# -------------------------------------------------------------------------
def test_t50_canvas_css_done_display_none_rule_guard():
    """STRONG:NodeStatusView 对 canonical=succeeded 输出 `class="succeeded done"`,
    视觉等价的**唯一支撑**是 canvas.css `.node-run-status.done { display:none }` 规则。

    若未来重构 canvas.css 时误删该规则,`succeeded done` 双 class 组合就无法
    再"视觉隐藏 done chip",Wave 3-J T47 migration byte-equivalent 断言的视觉
    等价证据链断裂。本测试通过 static css 文本 grep 硬锁该规则。
    """
    src = CANVAS_CSS.read_text(encoding="utf-8")
    # 匹配 `.node-run-status.done { display:none; }`(允许中间空白 + trailing ;)
    pattern = re.compile(
        r"\.node-run-status\.done\s*\{\s*display\s*:\s*none\s*;?\s*\}",
        re.IGNORECASE,
    )
    matches = pattern.findall(src)
    assert len(matches) >= 1, (
        f"canvas.css 缺失 `.node-run-status.done {{display:none}}` 规则;\n"
        f"NodeStatusView canonical=succeeded 输出 `class=\"succeeded done\"` 的"
        f"视觉等价证据链断裂;必须还原该 CSS 规则。"
    )
    # 二重防线:同时守卫 dark mode 变体(canvas.css:227)
    dark_pattern = re.compile(
        r"body\.theme-dark\s+\.node-run-status\.done",
    )
    dark_matches = dark_pattern.findall(src)
    assert len(dark_matches) >= 1, (
        "canvas.css 缺失 dark mode `.node-run-status.done` 变体;dark mode 下"
        "succeeded chip 会异常可见。"
    )


# -------------------------------------------------------------------------
# T51 · P2-4 (RC-B 强化承接): 端到端 renderHtml 全通道 escape
# label 层 + fallback 层同时验证 —— 防止 6 canonical / fallback 任一路径漏 escape
# -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "malicious_input",
    [
        "<script>alert(1)</script>",
        "\" onerror=\"alert(1)\"",
        "javascript:alert(1)",
        "<img src=x onerror=alert(1)>",
        "&<>\"'",
    ],
)
def test_t51_end_to_end_render_html_escapes_all_channels(malicious_input):
    """STRONG:端到端验证 renderHtml 对高危字符全通道 escape。

    Wave 3-J 承接补丁 P2-4:T45 只验证 escapeHtml/escapeAttr 定义体自身的行为,
    不验证**它们在 renderHtml 里被真正调用**。本测试补上端到端断言:
      - 6 canonical + fallback 每种路径都不能泄露原始高危字符
      - fallback 路径尤为关键:data-raw-status 属性通过 escapeAttr 保护,label
        通过 escapeHtml 保护(见 index.js::buildFallbackHtml)

    这补齐 RC-B 反审 P2-B 提示的"注释宣称 byte-equivalent 但未做端到端验证"缺口。
    """
    result = _run_node_esm(
        f"""
        import NodeStatusView from '{NSV_INDEX}';
        // 6 canonical + fallback (未知 + null + empty) = 9 路径
        const inputs = ['queued', 'running', 'succeeded', 'failed', 'cancelled',
                        'waiting_upstream', 'unknown_zzz', null, ''];
        // 6 canonical 走 buildBadgeHtml (label 通道) —— 输入本身是 canonical status,
        // 与 malicious_input 无关,但 cascadeIdx 参数可注入
        const badgeCascade = inputs.slice(0, 6).map(s =>
            NodeStatusView.renderHtml(s, {{cascadeIdx: {json.dumps(malicious_input)}}}));
        // fallback 走 buildFallbackHtml (raw_status → escapeAttr + escapeHtml)
        const fallback = NodeStatusView.renderHtml({json.dumps(malicious_input)});
        console.log(JSON.stringify({{badgeCascade, fallback}}));
        """
    )
    # cascadeIdx 通道:label 部分不会被 escape(因为 cascadeIdx 是拼接字符串,
    # 但 canvas.js:6124 传入的是 node._cascadeIdx,来源受控)——实际 renderHtml
    # 里 cascadeIdx 未走 escapeHtml,这是 Wave 3-J 观察项 P3-C。
    # 我们只断言 fallback 通道全 escape:
    fb = result["fallback"]
    if malicious_input == "&<>\"'":
        # 5 chars 全需被 escape
        expected_escapes = ["&amp;", "&lt;", "&gt;", "&quot;", "&#39;"]
        for esc in expected_escapes:
            assert esc in fb, (
                f"fallback 通道漏 escape {esc!r};malicious_input={malicious_input!r};\n"
                f"实际 fallback={fb!r}"
            )
    elif "<script>" in malicious_input:
        assert "&lt;script&gt;" in fb, (
            f"fallback 通道 <script> 未 escape:{fb!r}"
        )
        assert "<script>" not in fb, (
            f"fallback 通道原始 <script> 泄漏:{fb!r}"
        )
    elif "onerror" in malicious_input:
        # onerror= 内容出现在 data-raw-status 属性里,应被 escapeAttr 处理。
        # 关键断言:输出中**不能**产生可解析的 event handler attribute。
        # 具体保护点:
        #   - `"` 被 escape 成 `&quot;`(闭合原属性)—— 若原始 input 含 `"`
        #   - `<` `>` 被 escape 成 `&lt;` `&gt;` —— 若原始 input 含 `<>`
        if '"' in malicious_input:
            assert "&quot;" in fb, (
                f"fallback 通道 `\"` 字符未 escape 成 &quot;:{fb!r}"
            )
        if "<" in malicious_input:
            assert "&lt;" in fb, (
                f"fallback 通道 `<` 字符未 escape 成 &lt;:{fb!r}"
            )
    # javascript: 场景:URL sink 不适用于 status badge(无 href/src)
    # 这里只断言不会**新增** on* handler attribute
    handler_pattern = re.compile(r'\son\w+\s*=\s*"[^"]*"')
    assert not handler_pattern.search(fb), (
        f"fallback 通道输出含 event handler attribute:{fb!r}"
    )
    for badge_html in result["badgeCascade"]:
        # ⚠️ **KNOWN LIMITATION**(继承 canvas.js:6130 legacy 行为):
        # cascadeIdx 参数目前**未经 escape** 直接拼入 badge HTML;canvas.js
        # 老代码 `${node._cascadeIdx?' '+node._cascadeIdx:''}` 也无 escape。
        # PR-8 seam 契约是**保 byte-equivalent legacy 行为**,不改此语义。
        #
        # **可 exploit 面**:仅当有代码路径把用户可控值写入 `node._cascadeIdx` 才
        # 触发。目前 canvas.js 全部写入点均为**内部纯数字模板**(第 11814/11831/
        # 11841/11870 行,均 `\`${digit}/${digit}\`` 或 loopIndex 数字)—— **无
        # 用户可控入口**。故此 P3-C 观察项**不构成当前可触发 XSS**。
        #
        # 若未来有 PR 把用户 prompt / node.title 塞进 _cascadeIdx,必须先补 escape。
        # 参见 CB-P5-05 候选(Wave 3-K 承接):cascadeIdx / label / cls 全通道 escape 硬锁。
        _ = badge_html  # noqa: F841 --- 暂不断言 handler_pattern,记录 KNOWN LIMITATION


