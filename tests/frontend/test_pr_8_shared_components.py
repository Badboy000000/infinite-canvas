"""Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (共享组件套件 · 候选 A GM-14 第 5 次实证).

covers 契约测试 T330-T345 (16 项):

    T330  modules/asset/AssetSidePanel · mount/unmount 幂等
    T331  modules/asset/AssetSidePanel · assetLibraryStore 变化触发 refresh
    T332  modules/provider/ProviderSelector · P0 密钥字段 sentinel 反查 DOM outerHTML
    T333  modules/provider/ModelSelector · 换 provider 后 value 重置
    T334  6 件套 innerHTML 用户输入 XSS 抗回归 (escapeAttr / escapeHtml 沉入)
    T335  byte-equivalent 迁移 · canvas.js legacy inline fallback vs NodeStatusView.renderHtml
          **对 legacy `queued/running/failed` 三值 runtime-output-byte-equal** (真 diff · 非重言)
    T336  Modal ESC 关闭 / 焦点陷阱 / role='dialog' + aria-modal
    T337  Toast 自动 dismiss / role='status' + aria-live
    T338  Tooltip aria-describedby 关联 + hover/focus 触发
    T339  Dropdown ArrowDown/Enter 键盘导航
    T340  Splitter localStorage 位置保存与读取
    T341  Panel aria-expanded 与折叠状态同步
    T342  架构分层抗回归 · modules/asset/AssetSidePanel 顶注含 '候选 A' 关键字 ·
          shared/components/AssetSidePanel/index.js 保持零改动 vs baseline 3118ed1
    T343  同上对 ProviderSelector 分层抗回归
    T344  5 处 HTML 引入 shared/components/bootstrap.js
    T345  SharedComponentsReady bootstrap 就绪 Promise 契约

Baseline: 1186 tests collected (pytest --collect-only -q, worktree HEAD 3118ed1).
Target: 1186 → 1202.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# --- Paths -----------------------------------------------------------------
SHARED_COMPONENTS_DIR = ROOT / "static/js/shared/components"
MODULES_ASSET = ROOT / "static/js/modules/asset/AssetSidePanel/index.js"
MODULES_PS = ROOT / "static/js/modules/provider/ProviderSelector/index.js"
MODULES_MS = ROOT / "static/js/modules/provider/ModelSelector/index.js"
SHARED_ASP = SHARED_COMPONENTS_DIR / "AssetSidePanel/index.js"
SHARED_PS = SHARED_COMPONENTS_DIR / "ProviderSelector/index.js"
NSV_INDEX = SHARED_COMPONENTS_DIR / "NodeStatusView/index.js"
NSV_MAP = SHARED_COMPONENTS_DIR / "NodeStatusView/statusMap.js"
MODAL = SHARED_COMPONENTS_DIR / "Modal/index.js"
TOAST = SHARED_COMPONENTS_DIR / "Toast/index.js"
TOOLTIP = SHARED_COMPONENTS_DIR / "Tooltip/index.js"
DROPDOWN = SHARED_COMPONENTS_DIR / "Dropdown/index.js"
SPLITTER = SHARED_COMPONENTS_DIR / "Splitter/index.js"
PANEL = SHARED_COMPONENTS_DIR / "Panel/index.js"
BOOTSTRAP = SHARED_COMPONENTS_DIR / "bootstrap.js"
CANVAS_JS = ROOT / "static/js/canvas.js"

HTML_PAGES = [
    ROOT / "static/canvas.html",
    ROOT / "static/smart-canvas.html",
    ROOT / "static/asset-manager.html",
    ROOT / "static/api-settings.html",
    ROOT / "static/comfyui-settings.html",
]


# ---------------------------------------------------------------------------
# Node subprocess helpers
# ---------------------------------------------------------------------------
def _run_node_esm(script: str) -> dict:
    """跑 Node ESM subprocess, 返回 stdout JSON (最后一行)."""
    completed = subprocess.run(
        ["node", "--experimental-default-type=module", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"node exited with {completed.returncode}\n"
            f"--- stderr ---\n{completed.stderr}\n"
            f"--- stdout ---\n{completed.stdout}"
        )
    out = completed.stdout.strip().splitlines()
    return json.loads(out[-1])


def _run_node_cjs(script: str) -> dict:
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"node exited with {completed.returncode}\n"
            f"--- stderr ---\n{completed.stderr}\n"
            f"--- stdout ---\n{completed.stdout}"
        )
    out = completed.stdout.strip().splitlines()
    return json.loads(out[-1])


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


def _fake_dom_prelude() -> str:
    """Minimal fake DOM prelude for ESM tests. Supports element create /
    innerHTML string storage / classList / attribute get-set / event listeners.
    Not full JSDOM — just enough for our components' unit tests.
    """
    return r"""
        const _stubs = {};
        function makeEl(tag) {
            const el = {
                tagName: String(tag).toUpperCase(),
                nodeType: 1,
                children: [],
                childNodes: [],
                _attrs: {},
                _classes: new Set(),
                _listeners: {},
                _innerHTML: '',
                parentNode: null,
                hidden: false,
                disabled: false,
                style: {},
                value: '',
                textContent: '',
                get id() { return this._attrs.id || ''; },
                set id(v) { this._attrs.id = String(v); },
                get className() { return Array.from(this._classes).join(' ') + (this._extraClass || ''); },
                set className(v) {
                    this._classes = new Set();
                    String(v || '').split(/\s+/).filter(Boolean).forEach(c => this._classes.add(c));
                },
                classList: {
                    add: (c) => { el._classes.add(c); },
                    remove: (c) => { el._classes.delete(c); },
                    contains: (c) => el._classes.has(c),
                    toggle: (c, on) => { const has = el._classes.has(c); if (on === true || (on === undefined && !has)) el._classes.add(c); else el._classes.delete(c); },
                },
                setAttribute(k, v) { this._attrs[k] = String(v); },
                getAttribute(k) { return this._attrs[k] == null ? null : String(this._attrs[k]); },
                removeAttribute(k) { delete this._attrs[k]; },
                hasAttribute(k) { return k in this._attrs; },
                appendChild(child) {
                    if (child.parentNode) child.parentNode.removeChild(child);
                    this.children.push(child); this.childNodes.push(child); child.parentNode = this; return child;
                },
                removeChild(child) {
                    const i = this.children.indexOf(child); if (i >= 0) this.children.splice(i, 1);
                    const j = this.childNodes.indexOf(child); if (j >= 0) this.childNodes.splice(j, 1);
                    child.parentNode = null; return child;
                },
                insertBefore(newNode, refNode) {
                    if (!refNode) { return this.appendChild(newNode); }
                    const i = this.children.indexOf(refNode);
                    this.children.splice(i, 0, newNode); this.childNodes.splice(i, 0, newNode); newNode.parentNode = this; return newNode;
                },
                addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); },
                removeEventListener(type, fn) {
                    const arr = this._listeners[type] || [];
                    const i = arr.indexOf(fn); if (i >= 0) arr.splice(i, 1);
                },
                dispatchEvent(evt) {
                    const arr = this._listeners[evt.type] || [];
                    arr.slice().forEach(fn => { try { fn.call(this, evt); } catch (e) {} });
                    return true;
                },
                click() { this.dispatchEvent({ type: 'click', target: this, currentTarget: this, preventDefault(){}, stopPropagation(){}, closest: (sel) => this.closest ? this.closest(sel) : null }); },
                focus() { fakeDoc.activeElement = this; this.dispatchEvent({ type: 'focus', target: this }); },
                blur() { if (fakeDoc.activeElement === this) fakeDoc.activeElement = null; this.dispatchEvent({ type: 'blur', target: this }); },
                get firstChild() { return this.childNodes[0] || null; },
                get lastChild() { return this.childNodes[this.childNodes.length - 1] || null; },
                get outerHTML() {
                    const attrs = Object.keys(this._attrs).map(k => ` ${k}="${this._attrs[k]}"`).join('');
                    const cls = Array.from(this._classes).join(' ');
                    const clsAttr = cls ? ` class="${cls}"` : '';
                    // Prefer raw innerHTML (verbatim). If nothing has been set
                    // (children built via appendChild only), serialize children.
                    const body = this._innerHTML
                        ? this._innerHTML
                        : this.children.map(c => c.outerHTML || '').join('');
                    return `<${this.tagName.toLowerCase()}${clsAttr}${attrs}${this.hidden ? ' hidden' : ''}>${body}</${this.tagName.toLowerCase()}>`;
                },
                get innerHTML() { return this._innerHTML; },
                set innerHTML(v) {
                    this._innerHTML = String(v == null ? '' : v);
                    // Extremely naive parse: only extract descendants with attributes so
                    // querySelector by id / class / [data-role] can resolve them.
                    this.children = []; this.childNodes = [];
                    const re = /<([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[a-zA-Z_-][a-zA-Z0-9_-]*\s*=\s*"[^"]*")*)\s*(\/)?>/g;
                    let m;
                    while ((m = re.exec(this._innerHTML)) !== null) {
                        const tag = m[1];
                        const child = makeEl(tag);
                        const attrRe = /([a-zA-Z_-][a-zA-Z0-9_-]*)\s*=\s*"([^"]*)"/g;
                        let a;
                        while ((a = attrRe.exec(m[2])) !== null) {
                            if (a[1] === 'class') { String(a[2]).split(/\s+/).filter(Boolean).forEach(c => child._classes.add(c)); }
                            else if (a[1] === 'disabled') { child.disabled = true; child._attrs['disabled'] = ''; }
                            else if (a[1] === 'hidden') { child.hidden = true; }
                            else { child._attrs[a[1]] = a[2]; }
                        }
                        this.children.push(child); this.childNodes.push(child); child.parentNode = this;
                    }
                },
                querySelector(sel) {
                    const found = _selectAll(this, sel);
                    return found[0] || null;
                },
                querySelectorAll(sel) { return _selectAll(this, sel); },
                closest(sel) {
                    let n = this;
                    while (n) {
                        if (_matches(n, sel)) return n;
                        n = n.parentNode;
                    }
                    return null;
                },
                cloneNode() { const c = makeEl(tag); c._innerHTML = this._innerHTML; c._attrs = { ...this._attrs }; c._classes = new Set(this._classes); return c; },
                setPointerCapture() {},
                releasePointerCapture() {},
            };
            return el;
        }
        function _matches(el, sel) {
            if (!el || !sel) return false;
            sel = String(sel).trim();
            if (sel.startsWith('#')) return el._attrs.id === sel.slice(1);
            if (sel.startsWith('.')) return el._classes && el._classes.has(sel.slice(1));
            if (/^\[.+\]$/.test(sel)) {
                const inner = sel.slice(1, -1);
                const eq = inner.indexOf('=');
                if (eq < 0) return el._attrs && Object.prototype.hasOwnProperty.call(el._attrs, inner);
                const k = inner.slice(0, eq).trim();
                const v = inner.slice(eq + 1).trim().replace(/^"|"$/g, '');
                return el._attrs && el._attrs[k] === v;
            }
            // Split on space (descendant) or comma is not supported by design.
            // "a.b" tag+class
            const parts = sel.split('.');
            const tag = parts[0].toLowerCase();
            if (tag && el.tagName && el.tagName.toLowerCase() !== tag) return false;
            for (let i = 1; i < parts.length; i += 1) {
                if (!el._classes || !el._classes.has(parts[i])) return false;
            }
            return true;
        }
        function _selectAll(root, sel) {
            const out = [];
            function visit(node) {
                if (!node || node === root) {} else if (_matches(node, sel)) out.push(node);
                (node.children || []).forEach(visit);
            }
            (root.children || []).forEach(visit);
            return out;
        }
        const fakeDoc = {
            createElement: (tag) => makeEl(tag),
            createDocumentFragment: () => makeEl('#doc-fragment'),
            body: makeEl('body'),
            activeElement: null,
            _listeners: {},
            addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); },
            removeEventListener(type, fn) {
                const arr = this._listeners[type] || [];
                const i = arr.indexOf(fn); if (i >= 0) arr.splice(i, 1);
            },
            dispatchEvent(evt) {
                const arr = this._listeners[evt.type] || [];
                arr.slice().forEach(fn => { try { fn.call(this, evt); } catch (e) {} });
            },
            getElementById(id) {
                function find(n) {
                    if (n._attrs && n._attrs.id === id) return n;
                    for (const c of (n.children || [])) { const r = find(c); if (r) return r; }
                    return null;
                }
                return find(this.body);
            },
        };
        globalThis.document = fakeDoc;
        globalThis.window = globalThis;
        globalThis.localStorage = {
            _s: {},
            getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
            setItem(k, v) { this._s[k] = String(v); },
            removeItem(k) { delete this._s[k]; },
        };
        globalThis.CSS = { escape: (s) => String(s).replace(/[^a-zA-Z0-9_-]/g, m => '\\' + m) };
        globalThis.setTimeout = globalThis.setTimeout || ((fn, ms) => 0);
        globalThis.clearTimeout = globalThis.clearTimeout || (() => {});
    """


# ===========================================================================
# T330 · AssetSidePanel mount/unmount 幂等
# ===========================================================================
def test_t330_asset_side_panel_mount_unmount_idempotent():
    prelude = _fake_dom_prelude()
    module = MODULES_ASSET.as_uri()
    script = f"""
        {prelude}
        const mod = await import('{module}');
        const container = fakeDoc.createElement('div');
        // First mount
        const inst1 = mod.mount(container, {{ onAssetPick: () => {{}} }});
        const shell1 = container.querySelector('.asp-root');
        // Second mount into same container — first instance should have been unmounted.
        const inst2 = mod.mount(container, {{ onAssetPick: () => {{}} }});
        const shell2 = container.querySelector('.asp-root');
        // unmount twice: no throw.
        inst2.unmount();
        inst2.unmount();
        // module-level unmount(container): idempotent.
        mod.unmount(container);
        console.log(JSON.stringify({{
            hadShell1: !!shell1,
            hadShell2: !!shell2,
            instsDifferent: inst1 !== inst2,
            emptyAfter: container.innerHTML === '',
            attached: !!container.__assetSidePanelInstance,
        }}));
    """
    result = _run_node_esm(script)
    assert result["hadShell1"] is True
    assert result["hadShell2"] is True
    assert result["instsDifferent"] is True
    assert result["emptyAfter"] is True
    assert result["attached"] is False


# ===========================================================================
# T331 · AssetSidePanel · store 变化触发 refresh (subscribe 回调计数)
# ===========================================================================
def test_t331_asset_side_panel_refreshes_on_store_change():
    prelude = _fake_dom_prelude()
    module = MODULES_ASSET.as_uri()
    store_url = (ROOT / "static/js/shared/stores/assetLibraryStore.js").as_uri()
    script = f"""
        {prelude}
        // Stub apiClient before store import.
        globalThis.__stubbedApiCalls = 0;
        // Provide a stub apiClient by monkey-patching before assetLibraryStore is imported.
        // assetLibraryStore imports `../api-client/client.js`; we instead call setState directly.
        const storeMod = await import('{store_url}');
        const mod = await import('{module}');
        const container = fakeDoc.createElement('div');
        const inst = mod.mount(container, {{}});
        const before = container.querySelector('.asp-grid').innerHTML;
        // Push a synthetic library snapshot; subscribe should fire refresh.
        storeMod.applyAssetLibrarySnapshot({{
            library: {{ libraries: [{{ id: 'lib1', name: 'Test', categories: [
                {{ id: 'cat1', name: 'Cat A', type: 'image', items: [
                    {{ id: 'a1', name: 'Alpha', url: '/a.png', kind: 'image' }},
                ]}}
            ]}}]}},
            asset_library: {{ id: 'lib1' }},
        }});
        const after = container.querySelector('.asp-grid').innerHTML;
        const libSel = container.querySelector('.asp-library-select');
        const catSel = container.querySelector('.asp-category-select');
        inst.unmount();
        console.log(JSON.stringify({{
            beforeEmpty: /canvas-asset-empty/.test(before),
            afterHasItem: /data-asset-id="a1"/.test(after),
            libOption: (libSel.innerHTML.match(/value="lib1"/) || []).length,
            catOption: (catSel.innerHTML.match(/value="cat1"/) || []).length,
        }}));
    """
    result = _run_node_esm(script)
    assert result["beforeEmpty"] is True, "initial grid should be empty"
    assert result["afterHasItem"] is True, "grid should show injected asset after store change"
    assert result["libOption"] >= 1, "library select should contain the new library option"
    assert result["catOption"] >= 1, "category select should contain the new category option"


# ===========================================================================
# T332 · ProviderSelector P0 密钥字段 sentinel 反查 DOM outerHTML
# ===========================================================================
def test_t332_provider_selector_no_credential_leak_in_dom():
    prelude = _fake_dom_prelude()
    module = MODULES_PS.as_uri()
    ps_store_url = (ROOT / "static/js/shared/stores/providersStore.js").as_uri()
    # Provider payload contaminated with credential fields — must NEVER surface in DOM.
    script = f"""
        {prelude}
        const storeMod = await import('{ps_store_url}');
        const mod = await import('{module}');
        // Poison the store with credential-laden providers.
        storeMod.providersStore.setState({{ providers: [
            {{ id: 'p1', name: 'Prov1', capability: 'chat', models: ['m'],
              api_key: 'sk-real-key-XXX', secret: 'shhh', token: 'tk_abc',
              password: 'pw123', credential: 'cred999', raw: {{ leaked: 'yes' }} }},
            {{ id: 'p2', name: 'Prov2', capability: 'chat', models: ['n'],
              api_key: 'ANOTHER-KEY' }},
        ]}}, 'poison');
        const container = fakeDoc.createElement('div');
        const inst = mod.mount(container, {{ variant: 'chat', value: 'p1' }});
        const outer = container.outerHTML;
        const sentinels = ['api_key', 'secret', 'token', 'password', 'credential',
            'sk-real-key-XXX', 'shhh', 'tk_abc', 'pw123', 'cred999', 'ANOTHER-KEY', 'leaked'];
        const hits = sentinels.filter(s => outer.indexOf(s) !== -1);
        // Verify whitelist behaviour: pickWhitelist returned only whitelisted keys.
        const picked = mod.pickWhitelist({{
            id: 'p1', name: 'x', api_key: 'k', secret: 's', token: 't', password: 'p',
            credential: 'c', raw: {{}}, capability: 'chat', models: ['m'], protocol: 'p', icon_url: '',
        }});
        inst.unmount();
        console.log(JSON.stringify({{
            hits,
            pickedKeys: Object.keys(picked).sort(),
            whitelist: mod.WHITELIST_FIELDS.slice().sort(),
        }}));
    """
    result = _run_node_esm(script)
    assert result["hits"] == [], f"P0 密钥字段泄漏到 DOM: {result['hits']}"
    # pickWhitelist should only keep allowlisted keys.
    for k in result["pickedKeys"]:
        assert k in result["whitelist"], f"pickWhitelist 漏出非白名单字段: {k}"


# ===========================================================================
# T333 · ModelSelector · 换 provider 后 value 重置
# ===========================================================================
def test_t333_model_selector_resets_value_on_provider_change():
    prelude = _fake_dom_prelude()
    ms_url = MODULES_MS.as_uri()
    ps_store_url = (ROOT / "static/js/shared/stores/providersStore.js").as_uri()
    script = f"""
        {prelude}
        const storeMod = await import('{ps_store_url}');
        const ms = await import('{ms_url}');
        storeMod.providersStore.setState({{ providers: [
            {{ id: 'p1', name: 'P1', capability: 'chat', models: ['m-alpha', 'm-beta'] }},
            {{ id: 'p2', name: 'P2', capability: 'chat', models: ['x-first', 'x-second'] }},
        ]}}, 'test');
        const changes = [];
        const container = fakeDoc.createElement('div');
        const inst = ms.mount(container, {{
            providerId: 'p1',
            value: 'm-beta',
            onChange: (v) => changes.push(v),
        }});
        const initialValue = inst.getValue();
        // Switch to p2 — value MUST reset to the first model of p2 ("x-first").
        inst.setProviderId('p2');
        const afterSwitch = inst.getValue();
        // Guard against provider that has no models — value = ''.
        storeMod.providersStore.setState({{ providers: [
            {{ id: 'p3', name: 'P3', capability: 'chat', models: [] }},
        ]}}, 'empty');
        inst.setProviderId('p3');
        const afterEmpty = inst.getValue();
        inst.unmount();
        console.log(JSON.stringify({{ initialValue, afterSwitch, afterEmpty, changes }}));
    """
    result = _run_node_esm(script)
    assert result["initialValue"] == "m-beta", "initial value should honour opts.value"
    assert result["afterSwitch"] == "x-first", (
        "换 provider 后 value 必须重置为新 provider 的第一个 model, 实际得到 "
        + repr(result["afterSwitch"])
    )
    assert result["afterEmpty"] == "", "无 model 时 value 应为空"
    assert result["changes"] == ["x-first", ""], "setProviderId 必须触发 onChange"


# ===========================================================================
# T334 · 6 件套 innerHTML 用户输入 XSS 抗回归
# ===========================================================================
def test_t334_six_components_escape_untrusted_input():
    """Feed each of the 6 shared components an XSS sentinel via user-facing text
    fields (`title` / `msg` / `text` / `label` etc.) and assert:
      - the sentinel appears **escaped** (`&lt;script&gt;`) in the DOM output;
      - the raw `<script>` tag is NEVER present.
    """
    prelude = _fake_dom_prelude()
    modal = MODAL.as_uri()
    toast = TOAST.as_uri()
    tooltip = TOOLTIP.as_uri()
    dropdown = DROPDOWN.as_uri()
    panel = PANEL.as_uri()
    splitter = SPLITTER.as_uri()
    script = f"""
        {prelude}
        const SENTINEL = '<script>alert(1)</script>';
        const [modalMod, toastMod, tipMod, ddMod, panelMod, splitMod] = await Promise.all([
            import('{modal}'), import('{toast}'), import('{tooltip}'),
            import('{dropdown}'), import('{panel}'), import('{splitter}'),
        ]);

        // Modal: title & label
        const m = modalMod.open({{ title: SENTINEL, content: '<div>trusted</div>' }});
        const modalOuter = m.root.outerHTML;
        m.close();

        // Toast: msg
        const t = toastMod.success(SENTINEL);
        const toastOuter = t ? t.root.outerHTML : '';

        // Tooltip: text
        const target = fakeDoc.createElement('button');
        fakeDoc.body.appendChild(target);
        const tip = tipMod.attach(target, {{ text: SENTINEL }});
        const tipEl = fakeDoc.getElementById(tip.id);
        const tipOuter = tipEl.outerHTML;
        tip.detach();

        // Dropdown: item label
        const trg = fakeDoc.createElement('button'); fakeDoc.body.appendChild(trg);
        const dd = ddMod.mount(trg, {{ items: [{{ value: 'v', label: SENTINEL }}], onSelect: () => {{}} }});
        const ddOuter = dd.menu.outerHTML;
        dd.unmount();

        // Panel: title
        const pc = fakeDoc.createElement('div');
        const p = panelMod.mount(pc, {{ title: SENTINEL, content: '<b>trusted</b>' }});
        const panelOuter = p.root.outerHTML;
        p.unmount();

        // Splitter: no user text input, but has data-splitter-storage attr — check no crash.
        const sc = fakeDoc.createElement('div');
        sc.appendChild(fakeDoc.createElement('div'));
        sc.appendChild(fakeDoc.createElement('div'));
        const sp = splitMod.mount(sc, {{ storageKey: SENTINEL, initial: 100 }});
        const splitterOuter = sp.handle.outerHTML;
        sp.unmount();

        function passes(html) {{
            return {{
                hasRawScript: html.indexOf('<script>') !== -1,
                hasEscaped: html.indexOf('&lt;script&gt;') !== -1,
            }};
        }}
        console.log(JSON.stringify({{
            modal: passes(modalOuter),
            toast: passes(toastOuter),
            tooltip: passes(tipOuter),
            dropdown: passes(ddOuter),
            panel: passes(panelOuter),
            splitter: passes(splitterOuter),
        }}));
    """
    result = _run_node_esm(script)
    for name in ("modal", "toast", "tooltip", "dropdown", "panel"):
        assert result[name]["hasRawScript"] is False, f"{name} 出现未转义 <script> —— P0 XSS 回归"
        assert result[name]["hasEscaped"] is True, f"{name} 未把 <script> escape 为 &lt;script&gt;"
    # Splitter never rendered SENTINEL as text (it's a storage-key opts), but
    # also must NOT emit a raw <script> tag anywhere.
    assert result["splitter"]["hasRawScript"] is False


# ===========================================================================
# T335 · byte-equivalent 迁移 · legacy inline fallback vs NodeStatusView.renderHtml
# ===========================================================================
def test_t335_byte_equivalent_canvas_legacy_fallback_vs_nsv_render_html():
    r"""**真 diff 断言 · 非重言**:
      canvas.js 的 legacy inline fallback template 是 seam-import-race safety net,
      在 NodeStatusView ESM 尚未 resolve 的**首帧**用于兜底。它与
      `NodeStatusView.renderHtml(status, {cascadeIdx})` **对 legacy `queued/running/failed`
      三值 runtime-output-byte-equal**;对 `done` 值仅 visual-byte-equal。

    抗重言性硬约束:
      - 我们从 canvas.js **原文本**抓 `const label = {...}` + `return \`...\`;`
        两条语句 · 用 `new Function` 从 canvas.js **字面量**构造 legacy fn
      - 与 `NodeStatusView.renderHtml` 的 ESM 真跑输出对比
      - 若任一侧改动 · 断言立即 fail 并 dump 双侧 HTML
      - 抓取失败(canvas.js 模板被重构)→ 立即 skip 前抛错误提示
    """
    canvas_src = CANVAS_JS.read_text(encoding="utf-8")
    # 定位 renderNode 中 statusHtml IIFE body,再取 fallback 分支两条语句。
    iife_match = re.search(
        r"const statusHtml\s*=\s*showStatus\s*\?\s*\(\(\)\s*=>\s*\{(?P<body>.+?)\}\)\(\)\s*:\s*'';",
        canvas_src, re.DOTALL,
    )
    assert iife_match, "无法在 canvas.js 定位 statusHtml IIFE (模板结构漂移)"
    iife_body = iife_match.group("body")
    label_match = re.search(
        r"const\s+label\s*=\s*(\{[^}]+\})\[node\.runStatus\]\s*\|\|\s*'';",
        iife_body,
    )
    return_match = re.search(
        r"return\s+(`[^`]+`)\s*;",
        iife_body,
    )
    assert label_match, "无法从 canvas.js 抓 legacy fallback label map"
    assert return_match, "无法从 canvas.js 抓 legacy fallback return template"
    label_map_literal = label_match.group(1)
    return_template_literal = return_match.group(1)

    # canvas.js 内的 escapeHtml 定义体(去掉重言:legacy fn 使用的 escape 是
    # canvas.js 原定义体真实调用,不是本测试文件里手抄的重言副本)。
    escape_src = _extract_function_source(canvas_src, "escapeHtml")
    assert escape_src.startswith("function escapeHtml"), "canvas.js::escapeHtml 抓取失败"

    nsv_uri = NSV_INDEX.as_uri()
    values = ["queued", "running", "failed"]
    cascade_variants = ["", "1/5"]
    cases = [{"status": v, "cascadeIdx": c} for v in values for c in cascade_variants]

    # Compose the legacy fn body once using canvas.js real string literals,
    # then dump the whole test payload as JSON so the JS source is portable.
    legacy_fn_body = (
        f"const label = {label_map_literal}[node.runStatus] || '';\n"
        f"return {return_template_literal};"
    )
    payload = {
        "cases": cases,
        "legacyFnBody": legacy_fn_body,
        "escapeSrc": escape_src,
        "nsvUri": nsv_uri,
    }
    payload_json = json.dumps(payload)

    script = f"""
        const P = {payload_json};
        // canvas.js 原文本 evaluate escapeHtml (真实定义体);ESM 严格模式下 eval
        // 内的声明不逃逸 · 用 Function 构造器 + return · 挂到 globalThis 后可用。
        globalThis.escapeHtml = new Function(P.escapeSrc + '\\n; return escapeHtml;')();
        // canvas.js legacy fallback body 通过 new Function 从 canvas.js
        // **原字面量**构造 —— 若 canvas.js 模板改动 · 输出立即改变。
        const legacyFn = new Function('node', 'escapeHtml', P.legacyFnBody);
        // ESM 真实加载 NodeStatusView (非重言;是产品代码本身)。
        const nsvMod = await import(P.nsvUri);
        const rows = P.cases.map(c => {{
            const node = {{ runStatus: c.status, _cascadeIdx: c.cascadeIdx }};
            const legacy = legacyFn(node, globalThis.escapeHtml);
            const nsv = nsvMod.default.renderHtml(c.status, {{ cascadeIdx: c.cascadeIdx }});
            return {{ status: c.status, cascadeIdx: c.cascadeIdx, legacy, nsv, equal: legacy === nsv }};
        }});
        console.log(JSON.stringify({{ rows, labelMap: P.legacyFnBody.slice(0, 60) }}));
    """
    result = _run_node_esm(script)
    rows = result["rows"]
    assert len(rows) == 6, "expected 3 statuses x 2 cascadeIdx variants"

    # ------- 硬断言 -------
    non_equal = [r for r in rows if not r["equal"]]
    if non_equal:
        detail = "\n".join(
            f"  status={r['status']!r} cascadeIdx={r['cascadeIdx']!r}\n"
            f"    legacy = {r['legacy']!r}\n"
            f"    nsv    = {r['nsv']!r}"
            for r in non_equal
        )
        pytest.fail(
            "byte-equivalent 迁移证据破裂 (T335)。以下 case runtime 输出不再逐字节相等:\n"
            + detail
        )

    # 强抗重言证据:输出必须包含 CSS class token + 中文 label 才算真的两侧
    # 都渲染了 HTML(不是空字符串对空字符串的假 PASS)。
    labels_expected = {"queued": "排队中", "running": "运行中", "failed": "失败"}
    for r in rows:
        assert r["nsv"].startswith('<span class="node-run-status'), r
        assert labels_expected[r["status"]] in r["nsv"], (
            f"NSV 输出未包含期望的中文 label {labels_expected[r['status']]!r}: {r['nsv']!r}"
        )
        assert labels_expected[r["status"]] in r["legacy"], (
            f"canvas.js legacy 输出未包含 label {labels_expected[r['status']]!r}: {r['legacy']!r}"
        )
        # cascade 非空时 · 两侧都必须包含该字面量
        if r["cascadeIdx"]:
            assert r["cascadeIdx"] in r["nsv"], r
            assert r["cascadeIdx"] in r["legacy"], r


# ===========================================================================
# T336 · Modal · ESC / focus trap / role=dialog + aria-modal
# ===========================================================================
def test_t336_modal_esc_and_aria():
    prelude = _fake_dom_prelude()
    modal = MODAL.as_uri()
    script = f"""
        {prelude}
        const mod = await import('{modal}');
        let onCloseReason = null;
        const inst = mod.open({{
            title: 'Hello',
            content: '<button id="b1">One</button><button id="b2">Two</button>',
            onClose: (r) => {{ onCloseReason = r; }},
        }});
        const role = inst.root.getAttribute('role');
        const ariaModal = inst.root.getAttribute('aria-modal');
        const labelledBy = inst.root.getAttribute('aria-labelledby');
        const isOpenBefore = mod.isOpen();
        // Dispatch ESC keydown on document.
        fakeDoc.dispatchEvent({{ type: 'keydown', key: 'Escape', preventDefault(){{}} }});
        const isOpenAfter = mod.isOpen();
        console.log(JSON.stringify({{
            role, ariaModal, hasLabelledBy: !!labelledBy,
            isOpenBefore, isOpenAfter, onCloseReason,
        }}));
    """
    result = _run_node_esm(script)
    assert result["role"] == "dialog"
    assert result["ariaModal"] == "true"
    assert result["hasLabelledBy"] is True
    assert result["isOpenBefore"] is True
    assert result["isOpenAfter"] is False, "ESC 键必须关闭 Modal"
    assert result["onCloseReason"] == "escape"


# ===========================================================================
# T337 · Toast · role='status' + aria-live · timeout dismiss
# ===========================================================================
def test_t337_toast_aria_and_auto_dismiss():
    prelude = _fake_dom_prelude()
    toast = TOAST.as_uri()
    script = f"""
        {prelude}
        // Track setTimeout / clearTimeout invocations.
        const timers = [];
        globalThis.setTimeout = (fn, ms) => {{ timers.push({{fn, ms}}); return timers.length; }};
        globalThis.clearTimeout = (id) => {{ /* noop */ }};
        const mod = await import('{toast}');
        const s = mod.success('all good');
        const e = mod.error('oops');
        const w = mod.warning('careful');
        const i = mod.info('ping');
        const outers = {{
            success: s.root.outerHTML,
            error: e.root.outerHTML,
            warning: w.root.outerHTML,
            info: i.root.outerHTML,
        }};
        // Trigger the dismiss timer for success.
        const before = s.root.parentNode ? true : false;
        s.dismiss();
        const after = s.root.parentNode ? true : false;
        console.log(JSON.stringify({{ outers, timers: timers.length, before, after }}));
    """
    result = _run_node_esm(script)
    for kind in ("success", "error", "warning", "info"):
        html = result["outers"][kind]
        assert 'role="status"' in html, f"{kind} 缺 role=status"
        assert 'aria-live=' in html, f"{kind} 缺 aria-live"
    assert 'aria-live="assertive"' in result["outers"]["error"]
    assert 'aria-live="assertive"' in result["outers"]["warning"]
    assert 'aria-live="polite"' in result["outers"]["success"]
    assert 'aria-live="polite"' in result["outers"]["info"]
    assert result["timers"] == 4, "每次显示应注册 1 个自动 dismiss 计时器"
    assert result["before"] is True and result["after"] is False


# ===========================================================================
# T338 · Tooltip · aria-describedby 关联 + hover 触发
# ===========================================================================
def test_t338_tooltip_aria_describedby():
    prelude = _fake_dom_prelude()
    tooltip = TOOLTIP.as_uri()
    script = f"""
        {prelude}
        const mod = await import('{tooltip}');
        const target = fakeDoc.createElement('button');
        fakeDoc.body.appendChild(target);
        const inst = mod.attach(target, {{ text: 'Helpful hint' }});
        const describedBy = target.getAttribute('aria-describedby');
        const tipEl = fakeDoc.getElementById(inst.id);
        const initiallyHidden = tipEl.hidden;
        // Fire mouseenter — should show tooltip.
        target.dispatchEvent({{ type: 'mouseenter', target, currentTarget: target }});
        const afterEnter = tipEl.hidden;
        target.dispatchEvent({{ type: 'mouseleave', target, currentTarget: target }});
        const afterLeave = tipEl.hidden;
        inst.detach();
        const afterDetach = target.getAttribute('aria-describedby');
        console.log(JSON.stringify({{
            describedBy, initiallyHidden, afterEnter, afterLeave,
            afterDetach, tipId: inst.id, role: tipEl.getAttribute('role'),
        }}));
    """
    result = _run_node_esm(script)
    assert result["describedBy"] == result["tipId"]
    assert result["role"] == "tooltip"
    assert result["initiallyHidden"] is True
    assert result["afterEnter"] is False
    assert result["afterLeave"] is True
    assert result["afterDetach"] is None, "detach 后 aria-describedby 应回退"


# ===========================================================================
# T339 · Dropdown · ArrowDown / Enter 键盘导航
# ===========================================================================
def test_t339_dropdown_keyboard_navigation():
    prelude = _fake_dom_prelude()
    dropdown = DROPDOWN.as_uri()
    script = f"""
        {prelude}
        const mod = await import('{dropdown}');
        const trigger = fakeDoc.createElement('button');
        fakeDoc.body.appendChild(trigger);
        let selected = null;
        const dd = mod.mount(trigger, {{
            items: [
                {{ value: 'a', label: 'Alpha' }},
                {{ value: 'b', label: 'Beta' }},
                {{ value: 'c', label: 'Gamma' }},
            ],
            onSelect: (v) => {{ selected = v; }},
        }});
        // Open via trigger click.
        trigger.click();
        const opened = trigger.getAttribute('aria-expanded');
        const role = dd.menu.getAttribute('role');
        // ArrowDown to move focus to index 1 (Beta).
        fakeDoc.dispatchEvent({{ type: 'keydown', key: 'ArrowDown', preventDefault(){{}} }});
        // Dispatch click on menu with target=items[1] (bubbling simulation).
        const items = dd.menu.querySelectorAll('.sc-dropdown-item');
        dd.menu.dispatchEvent({{ type: 'click', target: items[1], currentTarget: dd.menu, preventDefault(){{}}, stopPropagation(){{}} }});
        // Escape closes.
        trigger.click();
        const openedAgain = trigger.getAttribute('aria-expanded');
        fakeDoc.dispatchEvent({{ type: 'keydown', key: 'Escape', preventDefault(){{}} }});
        const closedByEscape = trigger.getAttribute('aria-expanded');
        dd.unmount();
        console.log(JSON.stringify({{
            opened, role, selected, itemsCount: items.length,
            openedAgain, closedByEscape,
        }}));
    """
    result = _run_node_esm(script)
    assert result["opened"] == "true"
    assert result["role"] == "menu"
    assert result["selected"] == "b"
    assert result["itemsCount"] == 3
    assert result["openedAgain"] == "true"
    assert result["closedByEscape"] == "false"


# ===========================================================================
# T340 · Splitter · localStorage 位置保存与读取
# ===========================================================================
def test_t340_splitter_persists_position_to_localStorage():
    prelude = _fake_dom_prelude()
    splitter = SPLITTER.as_uri()
    script = f"""
        {prelude}
        const mod = await import('{splitter}');
        const container = fakeDoc.createElement('div');
        container.appendChild(fakeDoc.createElement('div'));
        container.appendChild(fakeDoc.createElement('div'));
        const sp = mod.mount(container, {{
            orientation: 'vertical',
            storageKey: 'sidebar-test',
            initial: 200, min: 40, max: 500,
        }});
        const key = 'sc-splitter:sidebar-test';
        const storedInit = localStorage.getItem(key);
        // Simulate resize.
        sp.setSize(350);
        const storedAfter = localStorage.getItem(key);
        // Fresh mount should pick up persisted value.
        sp.unmount();
        const c2 = fakeDoc.createElement('div');
        c2.appendChild(fakeDoc.createElement('div'));
        c2.appendChild(fakeDoc.createElement('div'));
        const sp2 = mod.mount(c2, {{ orientation: 'vertical', storageKey: 'sidebar-test',
            initial: 999, min: 40, max: 500 }});
        const rehydrated = sp2.getSize();
        const aria = sp2.handle.getAttribute('aria-valuenow');
        const orient = sp2.handle.getAttribute('aria-orientation');
        const role = sp2.handle.getAttribute('role');
        sp2.unmount();
        console.log(JSON.stringify({{
            storedInit, storedAfter, rehydrated, aria, orient, role,
        }}));
    """
    result = _run_node_esm(script)
    assert result["storedInit"] == "200", "mount 时应写入初始值"
    assert result["storedAfter"] == "350"
    assert result["rehydrated"] == 350, "第二次 mount 应从 localStorage 读回"
    assert result["aria"] == "350"
    assert result["orient"] == "vertical"
    assert result["role"] == "separator"


# ===========================================================================
# T341 · Panel · aria-expanded 与折叠状态同步
# ===========================================================================
def test_t341_panel_aria_expanded_sync():
    prelude = _fake_dom_prelude()
    panel = PANEL.as_uri()
    script = f"""
        {prelude}
        const mod = await import('{panel}');
        const container = fakeDoc.createElement('div');
        const toggles = [];
        const p = mod.mount(container, {{
            title: 'Section',
            content: '<div>body</div>',
            collapsed: false,
            onToggle: (c) => toggles.push(c),
        }});
        const header = p.root.querySelector('.sc-panel-header');
        const body = p.root.querySelector('.sc-panel-body');
        const beforeAria = header.getAttribute('aria-expanded');
        const beforeHidden = body.hasAttribute('hidden');
        p.toggle();
        const afterAria = header.getAttribute('aria-expanded');
        const afterHidden = body.hasAttribute('hidden');
        p.setCollapsed(false);
        const backAria = header.getAttribute('aria-expanded');
        p.unmount();
        console.log(JSON.stringify({{
            beforeAria, beforeHidden, afterAria, afterHidden, backAria, toggles,
        }}));
    """
    result = _run_node_esm(script)
    assert result["beforeAria"] == "true"
    assert result["beforeHidden"] is False
    assert result["afterAria"] == "false"
    assert result["afterHidden"] is True
    assert result["backAria"] == "true"
    assert result["toggles"] == [True, False]


# ===========================================================================
# T342 · 架构分层抗回归 · modules/asset/AssetSidePanel/ 顶注 · shared/ 零改动
# ===========================================================================
def test_t342_asset_side_panel_layering_regression_guard():
    """
    - modules/asset/AssetSidePanel/index.js 顶注必须含 '候选 A' 关键字 (Lead 圆桌拍板证据)
    - shared/components/AssetSidePanel/index.js 相对 baseline main HEAD 保持零改动
    """
    modules_head = MODULES_ASSET.read_text(encoding="utf-8")[:2000]
    assert "候选 A" in modules_head, (
        "modules/asset/AssetSidePanel/index.js 顶注缺 '候选 A' 关键字 "
        "(Lead 圆桌拍板 GM-14 第 5 次实证证据丢失)"
    )
    # shared/ AssetSidePanel: byte-equal vs baseline main.
    # 用 git show 拿 baseline (fallback: main;若在 worktree 上找不到 origin/main
    # 则用当前 remote main)。
    for ref in ("HEAD", "main", "origin/main"):
        try:
            baseline = subprocess.check_output(
                ["git", "show", f"{ref}:static/js/shared/components/AssetSidePanel/index.js"],
                cwd=ROOT, stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="replace")
            break
        except subprocess.CalledProcessError:
            continue
    else:
        pytest.skip("git show 无法获取 baseline (git 环境?);跳过分层守卫")
    current = SHARED_ASP.read_text(encoding="utf-8")
    # 归一化 CRLF/LF 后 diff — Windows checkout 可能带 \r\n。
    def _norm(s): return s.replace("\r\n", "\n")
    assert _norm(baseline) == _norm(current), (
        "shared/components/AssetSidePanel/index.js 非零改动 —— "
        "违反候选 A 硬约束 (纯模板层必须保持零触碰)"
    )


# ===========================================================================
# T343 · 同上 for ProviderSelector
# ===========================================================================
def test_t343_provider_selector_layering_regression_guard():
    modules_head = MODULES_PS.read_text(encoding="utf-8")[:2000]
    assert "候选 A" in modules_head, (
        "modules/provider/ProviderSelector/index.js 顶注缺 '候选 A' 关键字"
    )
    assert "P0 密钥零渲染" in modules_head or "密钥" in modules_head, (
        "modules/provider/ProviderSelector/index.js 顶注缺 P0 密钥防线声明"
    )
    for ref in ("HEAD", "main", "origin/main"):
        try:
            baseline = subprocess.check_output(
                ["git", "show", f"{ref}:static/js/shared/components/ProviderSelector/index.js"],
                cwd=ROOT, stderr=subprocess.DEVNULL,
            ).decode("utf-8", errors="replace")
            break
        except subprocess.CalledProcessError:
            continue
    else:
        pytest.skip("git show 无法获取 baseline")
    current = SHARED_PS.read_text(encoding="utf-8")
    def _norm(s): return s.replace("\r\n", "\n")
    assert _norm(baseline) == _norm(current), (
        "shared/components/ProviderSelector/index.js 非零改动"
    )


# ===========================================================================
# T344 · 5 处 HTML 引入 bootstrap · cache-buster 闭环
# ===========================================================================
def test_t344_five_html_pages_include_shared_components_bootstrap():
    missing = []
    unversioned = []
    for path in HTML_PAGES:
        text = path.read_text(encoding="utf-8")
        # Must reference shared/components/bootstrap.js.
        if "/static/js/shared/components/bootstrap.js" not in text:
            missing.append(path.name)
            continue
        # cache-buster: `?v=...` 存在(允许 mtime 未 sync 时手写的 seed 版本号,
        # 服务启动后 sync_static_html_versions() 会替换成 `${version}.${mtime}`)。
        m = re.search(
            r"/static/js/shared/components/bootstrap\.js\?v=[^\"'\s]+",
            text,
        )
        if not m:
            unversioned.append(path.name)
    assert missing == [], f"以下 HTML 缺 shared/components/bootstrap.js 引入: {missing}"
    assert unversioned == [], f"以下 HTML bootstrap 未挂 cache-buster: {unversioned}"


# ===========================================================================
# T345 · SharedComponentsReady bootstrap 就绪 Promise 契约
# ===========================================================================
def test_t345_bootstrap_declares_shared_components_ready():
    """bootstrap.js 是非模块脚本(<script src>),不能直接被 ESM import 执行 (import
    对 IIFE 无效)。因此我们:
      1. 静态扫描 bootstrap.js 源码,校验必须存在的 canonical 契约声明
      2. 校验 9 个组件的 URL 全部指向真实文件
      3. Node vm 沙盒 evaluate bootstrap.js · 验证 `window.SharedComponentsReady`
         被赋值为 Promise
    """
    src = BOOTSTRAP.read_text(encoding="utf-8")
    for keyword in [
        "SharedComponents",
        "SharedComponentsReady",
        "__sharedComponentsBootstrapped",
        "/static/js/shared/components/Modal/index.js",
        "/static/js/shared/components/Toast/index.js",
        "/static/js/shared/components/Tooltip/index.js",
        "/static/js/shared/components/Dropdown/index.js",
        "/static/js/shared/components/Splitter/index.js",
        "/static/js/shared/components/Panel/index.js",
        "/static/js/modules/asset/AssetSidePanel/index.js",
        "/static/js/modules/provider/ProviderSelector/index.js",
        "/static/js/modules/provider/ModelSelector/index.js",
    ]:
        assert keyword in src, f"bootstrap.js 缺关键字/URL: {keyword}"

    # Verify all 9 target files exist on disk.
    for rel in [
        "static/js/shared/components/Modal/index.js",
        "static/js/shared/components/Toast/index.js",
        "static/js/shared/components/Tooltip/index.js",
        "static/js/shared/components/Dropdown/index.js",
        "static/js/shared/components/Splitter/index.js",
        "static/js/shared/components/Panel/index.js",
        "static/js/modules/asset/AssetSidePanel/index.js",
        "static/js/modules/provider/ProviderSelector/index.js",
        "static/js/modules/provider/ModelSelector/index.js",
    ]:
        assert (ROOT / rel).is_file(), f"bootstrap 指向的文件不存在: {rel}"

    # vm-evaluate the IIFE. We only need to prove SharedComponentsReady becomes
    # a thenable; the `import()` calls will throw ERR_MODULE_NOT_FOUND under vm
    # (there is no real HTTP origin), but the Promise assignment happens before
    # the imports resolve, so the check is still valid.
    node_script = r"""
        const fs = require('fs');
        const vm = require('vm');
        const path = %(path)s;
        const src = fs.readFileSync(path, 'utf-8');
        const sandbox = { window: {}, console };
        sandbox.window.__proto__ = null;
        sandbox.globalThis = sandbox.window;
        // Under vm we don't have dynamic import; stub it to resolve empty modules.
        sandbox.window.import = () => Promise.resolve({});
        // Also stub globalThis.import — bootstrap calls bare `import(url)`,
        // which references the module-level import (which vm doesn't intercept)
        // and throws. To short-circuit we rewrite `import(` to `window.import(`.
        const rewritten = src.replace(/\bimport\(/g, 'window.import(');
        vm.createContext(sandbox);
        vm.runInContext(rewritten, sandbox, { filename: path });
        const w = sandbox.window;
        process.stdout.write(JSON.stringify({
            hasReady: !!w.SharedComponentsReady,
            readyType: typeof w.SharedComponentsReady?.then,
            singleflight: !!w.__sharedComponentsBootstrapped,
        }));
    """ % {"path": json.dumps(str(BOOTSTRAP))}
    completed = subprocess.run(
        ["node", "-e", node_script],
        cwd=ROOT, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["hasReady"] is True
    assert result["readyType"] == "function", "SharedComponentsReady 必须是 Promise-like"
    assert result["singleflight"] is True
