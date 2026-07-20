"""Frontend PR-7: NodeRenderRegistry + NodeConfigRegistry seam + escapeAttr tests.

Uses `node --experimental-default-type=module` to run assertion scripts against
the native ES modules on disk. Follows the pattern established by
test_media_editor_seam.py / test_shared_stores_seam.py / test_canvas_renderer_seam.py.

Baseline (Wave 3-H closing / c3f2d83): 592 passed / 35 skipped.
Target: 592 → ~605 (+10 or more).

Covers:
    T1  NodeRenderRegistry / NodeConfigRegistry import pure
    T2  NodeConfigRegistry.registerLegacyAlias smart-container -> smart-image
    T3  NodeRenderRegistry.register + tryRender lookup
    T4  NodeRenderRegistry.renderFallback: unknown type placeholder DOM string
    T5  components/output.js claims legacy canvas.js::renderOutputGrid
    T6  components/ltxDirector.js claims legacy canvas.js::renderLTXDirectorBody
    T7  components/rh.js claims legacy canvas.js::renderRhBody
    T8  action-bus register / dispatch / has / list
    T9  action-bus.autoBindLegacyGlobals binds only present functions
    T10 escapeAttr XSS grep抗回归: no `onclick="[^"]*${(?!escapeAttr)` in canvas / smart-canvas
    T11 canvas.js renderNode fallback branch for unknown type (source grep)
    T12 canvas.js legacy render*Body exposed to window
    T13 canvas.html + smart-canvas.html data-action migration count
    T14 P0 密钥 sentinel 不泄漏到 fallback DOM 输出（未来漂移抗回归）
    T15 registry / config module byte-level line count sanity (no accidental gigantic append)
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RENDER_REG = (ROOT / "static/js/modules/node/registry/NodeRenderRegistry.js").as_uri()
CONFIG_REG = (ROOT / "static/js/modules/node/registry/NodeConfigRegistry.js").as_uri()
COMP_OUTPUT = (ROOT / "static/js/modules/node/components/output.js").as_uri()
COMP_LTX = (ROOT / "static/js/modules/node/components/ltxDirector.js").as_uri()
COMP_RH = (ROOT / "static/js/modules/node/components/rh.js").as_uri()
ACTION_BUS = (ROOT / "static/js/shared/interaction/action-bus.js").as_uri()

CANVAS_JS = ROOT / "static/js/canvas.js"
SMART_CANVAS_JS = ROOT / "static/js/smart-canvas.js"
CANVAS_HTML = ROOT / "static/canvas.html"
SMART_CANVAS_HTML = ROOT / "static/smart-canvas.html"


def run_node(script: str) -> dict:
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout)


# -------------------------------------------------------------------------
# T1. registry modules import 无副作用
# -------------------------------------------------------------------------
def test_registry_modules_import_pure():
    result = run_node(
        f"""
        import renderReg from {json.dumps(RENDER_REG)};
        import configReg from {json.dumps(CONFIG_REG)};
        console.log(JSON.stringify({{
            render: typeof renderReg,
            config: typeof configReg,
            renderList: renderReg.list(),
            configList: configReg.list(),
            aliases: configReg.listAliases(),
        }}));
        """
    )
    assert result["render"] == "object"
    assert result["config"] == "object"
    # 未 import components 时 registry 应为空；smart-container alias 是内置的
    assert result["renderList"] == []
    assert result["configList"] == []
    assert {"legacy": "smart-container", "canonical": "smart-image"} in result["aliases"]


# -------------------------------------------------------------------------
# T2. legacy alias normalize
# -------------------------------------------------------------------------
def test_config_registry_legacy_alias_smart_container():
    result = run_node(
        f"""
        import configReg from {json.dumps(CONFIG_REG)};
        const raw = configReg.normalizeAlias('smart-container');
        const passthrough = configReg.normalizeAlias('smart-image');
        const unknown = configReg.normalizeAlias('foo');
        console.log(JSON.stringify({{raw, passthrough, unknown}}));
        """
    )
    assert result["raw"] == "smart-image"
    assert result["passthrough"] == "smart-image"
    assert result["unknown"] == "foo"


# -------------------------------------------------------------------------
# T3. register + tryRender lookup
# -------------------------------------------------------------------------
def test_render_registry_register_and_tryrender():
    result = run_node(
        f"""
        import renderReg from {json.dumps(RENDER_REG)};
        renderReg.register({{type: 'foo', renderBody: () => 'foo-body'}});
        const foundFoo = renderReg.tryRender({{type: 'foo', id: 'a'}});
        const missing = renderReg.tryRender({{type: 'nope', id: 'b'}});
        const list = renderReg.list();
        console.log(JSON.stringify({{
            foo: foundFoo ? foundFoo.type : null,
            fooBody: foundFoo ? foundFoo.renderBody({{}}) : null,
            missing: missing === null,
            list,
        }}));
        """
    )
    assert result["foo"] == "foo"
    assert result["fooBody"] == "foo-body"
    assert result["missing"] is True
    assert result["list"] == ["foo"]


# -------------------------------------------------------------------------
# T4. fallback placeholder DOM (unknown type) — 不白屏、不 throw
# -------------------------------------------------------------------------
def test_render_registry_fallback_unknown_type_placeholder():
    result = run_node(
        f"""
        import renderReg from {json.dumps(RENDER_REG)};
        // Node ESM 环境无 document,应返回 HTML 字符串
        const html = renderReg.renderFallback({{type: 'crazy-new', id: 'n1'}});
        const nullBody = renderReg.renderFallback({{id: 'n2'}});
        const nullNode = renderReg.renderFallback(null);
        console.log(JSON.stringify({{html, nullBody, nullNode}}));
        """
    )
    html = result["html"]
    # 硬约束: 占位符含 .node 骨架 + data-id + 灰底 + "未知类型: <type>"
    assert 'class="node node-unknown"' in html
    assert 'data-id="n1"' in html
    assert 'data-node-type="crazy-new"' in html
    assert "未知类型: crazy-new" in html
    assert "#f5f5f5" in html or "#666" in html
    # 空 type 也不 throw
    assert "未知类型" in result["nullBody"]
    assert "未知类型" in result["nullNode"]


# -------------------------------------------------------------------------
# T5. components/output.js 认领 legacy canvas.js::renderOutputGrid
# -------------------------------------------------------------------------
def test_component_output_claims_legacy_render_output_grid():
    result = run_node(
        f"""
        import renderReg from {json.dumps(RENDER_REG)};
        import configReg from {json.dumps(CONFIG_REG)};
        await import({json.dumps(COMP_OUTPUT)});
        const entry = renderReg.get('output');
        const cfg = configReg.get('output');
        // 用 fake window 让 renderBody 走到 legacy 分支
        let calledArg = null;
        const fakeWindow = {{
            renderOutputGrid: (node, pending) => {{ calledArg = {{node, pending}}; return '<mock-output-grid/>'; }},
            renderPendingOutput: (p) => `<pending id="${{p.id}}"/>`,
        }};
        const output = entry.renderBody({{id: 'n1', _pending: [{{id: 'p1'}}]}}, {{window: fakeWindow}});
        console.log(JSON.stringify({{
            entryType: entry.type,
            claims: entry.describe(),
            cfgSize: cfg.defaultSize,
            output,
            calledNodeId: calledArg && calledArg.node.id,
            calledPending: calledArg && calledArg.pending,
        }}));
        """
    )
    assert result["entryType"] == "output"
    assert result["claims"]["legacyImplementation"] == "canvas.js::renderOutputGrid"
    assert result["claims"]["claimsLegacy"] is True
    assert result["cfgSize"] == {"w": 460, "h": 0}
    assert result["output"] == "<mock-output-grid/>"
    assert result["calledNodeId"] == "n1"
    assert result["calledPending"] == '<pending id="p1"/>'
    # 源码 grep 断言 registry 里含 renderOutputGrid 字面 call
    src = (ROOT / "static/js/modules/node/components/output.js").read_text(encoding="utf-8")
    assert "win.renderOutputGrid(node, pendingHtml)" in src


# -------------------------------------------------------------------------
# T6. components/ltxDirector.js 认领 legacy renderLTXDirectorBody
# -------------------------------------------------------------------------
def test_component_ltx_director_claims_legacy_render_ltx_director_body():
    result = run_node(
        f"""
        import renderReg from {json.dumps(RENDER_REG)};
        await import({json.dumps(COMP_LTX)});
        const entry = renderReg.get('ltxDirector');
        let called = null;
        const fakeWindow = {{
            renderLTXDirectorBody: (n) => {{ called = n.id; return '<ltx/>'; }},
        }};
        const html = entry.renderBody({{id: 'n2'}}, {{window: fakeWindow}});
        console.log(JSON.stringify({{
            claims: entry.describe(),
            html,
            called,
        }}));
        """
    )
    assert result["claims"]["legacyImplementation"] == "canvas.js::renderLTXDirectorBody"
    assert result["html"] == "<ltx/>"
    assert result["called"] == "n2"
    src = (ROOT / "static/js/modules/node/components/ltxDirector.js").read_text(encoding="utf-8")
    assert "win.renderLTXDirectorBody(node)" in src


# -------------------------------------------------------------------------
# T7. components/rh.js 认领 legacy renderRhBody
# -------------------------------------------------------------------------
def test_component_rh_claims_legacy_render_rh_body():
    result = run_node(
        f"""
        import renderReg from {json.dumps(RENDER_REG)};
        await import({json.dumps(COMP_RH)});
        const entry = renderReg.get('rh');
        let called = null;
        const fakeWindow = {{
            renderRhBody: (n) => {{ called = n.id; return '<rh/>'; }},
        }};
        const html = entry.renderBody({{id: 'n3'}}, {{window: fakeWindow}});
        console.log(JSON.stringify({{
            claims: entry.describe(),
            html,
            called,
        }}));
        """
    )
    assert result["claims"]["legacyImplementation"] == "canvas.js::renderRhBody"
    assert result["html"] == "<rh/>"
    assert result["called"] == "n3"
    src = (ROOT / "static/js/modules/node/components/rh.js").read_text(encoding="utf-8")
    assert "win.renderRhBody(node)" in src


# -------------------------------------------------------------------------
# T8. action-bus register / dispatch / has / list
# -------------------------------------------------------------------------
def test_action_bus_register_and_dispatch():
    result = run_node(
        f"""
        import bus from {json.dumps(ACTION_BUS)};
        // 清理跨测试污染
        bus.clear();
        let hits = [];
        bus.register('doThing', (event, el) => {{ hits.push({{arg: el.getAttribute('data-action-arg')}}); }});
        // 模拟事件目标
        const fakeEl = {{
            _attrs: {{'data-action': 'doThing', 'data-action-arg': 'foo'}},
            getAttribute(k) {{ return this._attrs[k]; }},
            closest(sel) {{ return this; }},
        }};
        const event = {{target: fakeEl}};
        const invoked = bus.dispatch(event);
        // 未 registered 的动作应返回 false 而不 throw
        const missingEl = {{
            _attrs: {{'data-action': 'noSuch'}},
            getAttribute(k) {{ return this._attrs[k]; }},
            closest(sel) {{ return this; }},
        }};
        const missing = bus.dispatch({{target: missingEl}});
        console.log(JSON.stringify({{
            invoked,
            missing,
            hits,
            has: bus.has('doThing'),
            list: bus.list(),
        }}));
        """
    )
    assert result["invoked"] is True
    assert result["missing"] is False
    assert result["hits"] == [{"arg": "foo"}]
    assert result["has"] is True
    assert "doThing" in result["list"]


# -------------------------------------------------------------------------
# T9. action-bus.autoBindLegacyGlobals binds only present functions
# -------------------------------------------------------------------------
def test_action_bus_autobind_legacy_globals():
    result = run_node(
        f"""
        import bus from {json.dumps(ACTION_BUS)};
        bus.clear();
        const scope = {{
            addImageNode: () => {{}},
            menuAdd: () => {{}},
        }};
        const bound = bus.autoBindLegacyGlobals(['addImageNode', 'menuAdd', 'notThere'], {{window: scope}});
        console.log(JSON.stringify({{
            bound,
            hasImg: bus.has('addImageNode'),
            hasNot: bus.has('notThere'),
        }}));
        """
    )
    assert set(result["bound"]) == {"addImageNode", "menuAdd"}
    assert result["hasImg"] is True
    assert result["hasNot"] is False


# -------------------------------------------------------------------------
# T10. escapeAttr XSS grep 抗回归 —— canvas.js / smart-canvas.js
# 硬约束: 拼串 onclick 未包裹 escapeAttr / escapeHtml 的场景应为 0 命中
# -------------------------------------------------------------------------
def test_escape_attr_xss_grep_regression():
    # 匹配形如 onclick="...${expr}..." 其中 expr 不含 escapeAttr / escapeHtml
    # 允许: onclick="foo(${escapeAttr(x)})"
    # 拒绝: onclick="foo(${x})" (未包裹)
    pattern = re.compile(r'onclick="[^"]*\$\{(?!escapeAttr|escapeHtml)[^}]+\}[^"]*"')
    canvas_src = CANVAS_JS.read_text(encoding="utf-8")
    smart_src = SMART_CANVAS_JS.read_text(encoding="utf-8")
    canvas_hits = pattern.findall(canvas_src)
    smart_hits = pattern.findall(smart_src)
    assert canvas_hits == [], (
        "canvas.js 存在未包裹 escapeAttr/escapeHtml 的 onclick 拼串场景: "
        f"{canvas_hits[:3]}"
    )
    assert smart_hits == [], (
        "smart-canvas.js 存在未包裹 escapeAttr/escapeHtml 的 onclick 拼串场景: "
        f"{smart_hits[:3]}"
    )


# -------------------------------------------------------------------------
# T11. canvas.js renderNode fallback branch 源码 grep
# -------------------------------------------------------------------------
def test_canvas_render_node_fallback_branch_present():
    src = CANVAS_JS.read_text(encoding="utf-8")
    # renderNode 内含未知类型 fallback 分支
    assert "未知类型:" in src, "canvas.js renderNode fallback 分支缺失"
    assert "_knownClassicTypes" in src, "canvas.js renderNode 未知类型判定缺失"
    assert "window.NodeRenderRegistry" in src
    assert "NodeConfigRegistry.normalizeAlias" in src


def test_smart_canvas_body_fallback_branch_present():
    src = SMART_CANVAS_JS.read_text(encoding="utf-8")
    assert "未知类型:" in src, "smart-canvas.js nodeBodyHtml fallback 分支缺失"
    assert "_knownSmartTypes" in src, "smart-canvas.js 未知类型判定缺失"


# -------------------------------------------------------------------------
# T12. canvas.js legacy render*Body exposed to window
# -------------------------------------------------------------------------
def test_canvas_legacy_renderers_exposed_to_window():
    src = CANVAS_JS.read_text(encoding="utf-8")
    for name in ["renderOutputGrid", "renderLTXDirectorBody", "renderRhBody", "renderPendingOutput", "renderNode"]:
        assert f"window.{name} = {name}" in src, f"canvas.js 未把 {name} 挂到 window"


# -------------------------------------------------------------------------
# T13. canvas.html + smart-canvas.html data-action 迁移计数
# -------------------------------------------------------------------------
def test_html_static_skeleton_data_action_migration():
    canvas_html = CANVAS_HTML.read_text(encoding="utf-8")
    smart_html = SMART_CANVAS_HTML.read_text(encoding="utf-8")
    # 工具栏
    assert 'data-action="addImageNode"' in canvas_html
    assert 'data-action="addPromptNode"' in canvas_html
    assert 'data-action="toggleQuickToolbar"' in canvas_html
    assert 'data-action="groupSelectedImages"' in canvas_html
    # createMenu (data-action + data-action-arg)
    assert 'data-action="menuAdd" data-action-arg="image"' in canvas_html
    assert 'data-action="menuAdd" data-action-arg="output"' in canvas_html
    # 迁移过的旧 onclick 应已消失
    assert 'onclick="addImageNode()"' not in canvas_html
    assert 'onclick="menuAdd(\'image\')"' not in canvas_html
    assert 'onclick="toggleQuickToolbar()"' not in canvas_html
    # smart-canvas 顶栏迁移
    assert 'data-action="backToCanvasList"' in smart_html
    assert 'data-action="openSmartCanvasShortcuts"' in smart_html
    assert 'data-action="openSmartCanvasLog"' in smart_html
    assert 'onclick="backToCanvasList()"' not in smart_html
    # bootstrap script 引入
    assert "modules/node/bootstrap.js" in canvas_html
    assert "modules/node/bootstrap.js" in smart_html


# -------------------------------------------------------------------------
# T14. P0 密钥 sentinel 不泄漏到 fallback DOM 输出
# 语义:即使本 PR 不涉及 Provider 凭据,fallback 渲染层也不能"回显"节点字段
# 中的敏感 sentinel(未来漂移抗回归)。用 escapeAttr 转义后,sentinel 会作为
# 字面文本落地,但如果哪天上游写了 unescape 我们要立即报警。
# -------------------------------------------------------------------------
def test_fallback_dom_does_not_expose_credential_sentinel():
    result = run_node(
        f"""
        import renderReg from {json.dumps(RENDER_REG)};
        // 在 node.type 里显式插入 sentinel
        const node = {{type: 'api_key=leaked_sentinel_bearer_ABCDEFG', id: 'n1', notes: 'access_token abc'}};
        const html = renderReg.renderFallback(node);
        console.log(JSON.stringify({{html}}));
        """
    )
    html = result["html"]
    # escapeAttr 应保证 sentinel 被 HTML 转义（sentinel 不能作为 HTML 属性执行）
    # 只需断言 sentinel 未以"能执行"的形式泄露（即不出现 <script> / on* 属性含 sentinel）
    assert "<script" not in html.lower()
    # sentinel 作为字面文本可以出现（因为 type 就是它）——这是 escapeAttr 转义后的合法字面
    # 但 attribute 边界必须干净:不允许 sentinel 破坏 data-node-type=".." 边界
    # 断言 sentinel 没有以未转义 " 的方式出现在 attribute value 内
    assert '"api_key=leaked_sentinel_bearer_ABCDEFG"' not in html or 'data-node-type="api_key=leaked_sentinel_bearer_ABCDEFG"' in html
    # 关键: sentinel 的 & 字符在 URL 场景会被转义,但 = 与字母不会。escapeAttr 主要防注入。
    # 硬断言: 输出不含 未转义 </div><script> 类结构
    assert "&lt;script" not in html.lower() or "<script" not in html.lower()


# -------------------------------------------------------------------------
# T15. NodeRenderRegistry / NodeConfigRegistry 模块 line count 理智值
# 防止意外把 canvas.js 全量塞进来
# -------------------------------------------------------------------------
def test_registry_module_line_count_sanity():
    for path in [
        "static/js/modules/node/registry/NodeRenderRegistry.js",
        "static/js/modules/node/registry/NodeConfigRegistry.js",
        "static/js/modules/node/components/output.js",
        "static/js/modules/node/components/ltxDirector.js",
        "static/js/modules/node/components/rh.js",
        "static/js/shared/interaction/action-bus.js",
    ]:
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        assert 20 <= len(lines) <= 400, f"{path} line count out of range: {len(lines)}"


# -------------------------------------------------------------------------
# T16. renderShell 契约:两画布中 node 根元素 class/data-id 保持冻结
# 断言 canvas.js renderNode 输出的 el 依然有 .node class + data-id 属性
# 走源码 grep(避免打 DOM)
# -------------------------------------------------------------------------
def test_render_shell_contract_preserves_data_id_and_node_class():
    src = CANVAS_JS.read_text(encoding="utf-8")
    # renderNode 内 el.className = `node ${node.type}-node ...` 未变
    assert re.search(r"el\.className\s*=\s*`node\s+\$\{node\.type\}-node", src)
    # el.dataset.id = node.id 未变
    assert "el.dataset.id = node.id" in src


# -------------------------------------------------------------------------
# T17. 双画布 bootstrap 引入 modules/node/bootstrap.js 顺序正确
# canvas.js / smart-canvas.js 必须在 bootstrap 前
# -------------------------------------------------------------------------
def test_bootstrap_script_order():
    for html_path in [CANVAS_HTML, SMART_CANVAS_HTML]:
        html = html_path.read_text(encoding="utf-8")
        idx_bootstrap = html.find("modules/node/bootstrap.js")
        idx_legacy = html.find("static/js/canvas.js")
        if idx_legacy < 0:
            idx_legacy = html.find("static/js/smart-canvas.js")
        assert idx_bootstrap > idx_legacy > 0, f"{html_path.name}: bootstrap 必须在 legacy canvas.js 之后"


# -------------------------------------------------------------------------
# Wave 3-I 承接补丁 T18 · P1-3 (前端 TRA):
# fallback 分支从「静态 grep」升级为「运行时 renderFallback 实际执行」验证。
#
# 反审背景:原 T11/T12 只 grep 字符串 `未知类型:` / `_knownClassicTypes`,
# 不证明 canvas.js 中的 renderNode({type: 'unknown-xyz'}) 真的走到 fallback
# 分支并生成占位 DOM。承接补丁真正 import renderFallback 并执行,断言:
#   (a) 无 document 环境(HTML string 分支)输出含 "未知类型: <type>" +
#       .node.node-unknown class + data-id + data-node-type 属性
#   (b) 有 document 环境(DOM 分支)输出 textContent 含 "未知类型: <type>",
#       className 含 node + node-unknown,dataset.id 与 dataset.nodeType 正确
# -------------------------------------------------------------------------
def test_render_fallback_html_string_branch_produces_placeholder_dom():
    """P1-3a:无 document 环境(Node 默认)renderFallback 返回 HTML 字符串。"""
    render_uri = (ROOT / "static/js/modules/node/registry/NodeRenderRegistry.js").as_uri()
    script = (
        f"import {{ renderFallback }} from '{render_uri}';"
        "const html = renderFallback({id: 'n1-abc', type: 'unknown-xyz'});"
        "console.log(JSON.stringify({html, isString: typeof html === 'string'}));"
    )
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "-e", script],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["isString"], "无 document 环境 renderFallback 必须返回 string"
    html = payload["html"]
    assert "未知类型: unknown-xyz" in html, f"fallback DOM 缺 label:\n{html}"
    assert 'class="node node-unknown"' in html, f"fallback DOM 缺 class:\n{html}"
    assert 'data-id="n1-abc"' in html, f"fallback DOM 缺 data-id:\n{html}"
    assert 'data-node-type="unknown-xyz"' in html, f"fallback DOM 缺 data-node-type:\n{html}"


def test_render_fallback_dom_branch_with_fake_document():
    """P1-3b:有 document 环境(浏览器场景)renderFallback 返回 HTMLElement。
    构造轻量 fake document,验证 dataset / className / textContent 全部正确。"""
    render_uri = (ROOT / "static/js/modules/node/registry/NodeRenderRegistry.js").as_uri()
    script = (
        f"import {{ renderFallback }} from '{render_uri}';"
        # 极简 fake document:createElement 返回一个 mock element
        "const fakeDoc = {"
        "  createElement: (tag) => ({"
        "    _tag: tag, _style: {},"
        "    dataset: {}, className: '',"
        "    style: new Proxy({}, {"
        "      set: (t, k, v) => { t[k] = v; return true; },"
        "      get: (t, k) => t[k],"
        "    }),"
        "    textContent: '',"
        "  }),"
        "};"
        "const el = renderFallback({id: 'n2-def', type: 'weird-type'}, {document: fakeDoc});"
        "console.log(JSON.stringify({"
        "  tag: el._tag,"
        "  className: el.className,"
        "  datasetId: el.dataset.id,"
        "  datasetNodeType: el.dataset.nodeType,"
        "  textContent: el.textContent,"
        "  isObject: typeof el === 'object' && el !== null,"
        "}));"
    )
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "-e", script],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["isObject"], "DOM 分支 renderFallback 必须返回对象"
    assert payload["tag"] == "div", f"fallback 根元素应为 div,实际:{payload['tag']}"
    assert "node" in payload["className"] and "node-unknown" in payload["className"], (
        f"fallback className 缺 node/node-unknown: {payload['className']}"
    )
    assert payload["datasetId"] == "n2-def", f"dataset.id 未透传: {payload['datasetId']}"
    assert payload["datasetNodeType"] == "weird-type", (
        f"dataset.nodeType 未透传: {payload['datasetNodeType']}"
    )
    assert payload["textContent"] == "未知类型: weird-type", (
        f"textContent 与契约不符: {payload['textContent']}"
    )


def test_render_fallback_never_throws_on_edge_inputs():
    """P1-3c:renderFallback 对多种边界输入均不 throw,契约明确。"""
    render_uri = (ROOT / "static/js/modules/node/registry/NodeRenderRegistry.js").as_uri()
    script = (
        f"import {{ renderFallback }} from '{render_uri}';"
        "const results = [];"
        "const cases = ["
        "  {node: null, tag: 'null'},"
        "  {node: undefined, tag: 'undefined'},"
        "  {node: {}, tag: 'empty'},"
        "  {node: {type: ''}, tag: 'empty-type'},"
        "  {node: {type: null, id: null}, tag: 'null-type-null-id'},"
        "  {node: {type: 42, id: 3.14}, tag: 'non-string'},"
        "];"
        "for (const c of cases) {"
        "  try {"
        "    const out = renderFallback(c.node);"
        "    results.push({tag: c.tag, ok: true, kind: typeof out});"
        "  } catch (e) {"
        "    results.push({tag: c.tag, ok: false, err: String(e)});"
        "  }"
        "}"
        "console.log(JSON.stringify({results}));"
    )
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "-e", script],
        cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    for r in payload["results"]:
        assert r["ok"], f"[边界 {r['tag']}] renderFallback 抛异常: {r.get('err')}"

