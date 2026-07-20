// modules/node/registry/NodeRenderRegistry.js
//
// Registry (seam-only) for per-`type` rendering. A registration entry is a
// plain object with:
//   - `type`:  the canonical node type string (must match NodeConfigRegistry)
//   - `renderBody(node)`:  optional — returns a body DOM/HTML string.
//   - `renderShell(node, opts)`:  optional — returns the shell markup (title
//                                bar + status badge slot + port anchors)
//                                for canvases that opt-in.
//   - `describe()`:  optional — returns metadata used by tests / diagnostics.
//
// Contract:
// - Zero build / zero dependencies. Native ES module.
// - Registration is additive. `tryRender(node)` returns `null` when the
//   node type is unknown; the caller (legacy `renderNode`) then falls
//   through to its existing branch or to the placeholder fallback below.
// - `renderFallback(node)` renders the "unknown type" placeholder DOM. It
//   MUST NOT throw and MUST NOT return empty (blank white 屏 is the failure
//   mode we explicitly guard against per Wave 3-I 决策 5).
// - Legacy alias resolution is delegated to NodeConfigRegistry.
//
// This module intentionally does NOT touch the DOM directly except within
// `renderFallback` which produces a self-contained placeholder element.

import NodeConfigRegistry from './NodeConfigRegistry.js';

const registry = new Map();

function register(entry) {
    if (!entry || typeof entry !== 'object') {
        throw new Error('NodeRenderRegistry.register: entry must be an object');
    }
    const type = entry.type;
    if (!type || typeof type !== 'string') {
        throw new Error('NodeRenderRegistry.register: entry.type required');
    }
    registry.set(type, Object.freeze({ ...entry }));
}

function get(type) {
    const canonical = NodeConfigRegistry.normalizeAlias(type);
    return registry.get(canonical) || null;
}

function has(type) {
    const canonical = NodeConfigRegistry.normalizeAlias(type);
    return registry.has(canonical);
}

function list() {
    return [...registry.keys()];
}

function clear() {
    registry.clear();
}

// escapeAttr / escapeHtml equivalents kept private to the fallback so we
// never rely on globals from canvas.js / smart-canvas.js. Semantics MUST be
// byte-equivalent to the canvas escape helpers (Wave 3-I 决策 4 硬约束 5).
function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[s]));
}

// Fallback placeholder DOM for unknown types. Produces a `.node` skeleton
// with the frozen `data-id` attribute plus a grey label so operators can
// see what went wrong instead of hitting a blank canvas.
//
// Contract:
// - Returns an HTMLElement (or a serialisable HTML string via `.outerHTML`).
// - Class list always contains `.node` and `.node-unknown` for CSS hooks.
// - Never throws.
function renderFallback(node, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    const rawType = node && node.type != null ? String(node.type) : '';
    const label = rawType ? `未知类型: ${rawType}` : '未知类型: <未定义>';
    const id = node && node.id != null ? String(node.id) : '';
    const shellClass = options.shellClass || 'node';
    if (!doc) {
        // Environment without `document` (e.g. Node ESM tests): return a
        // serialisable HTML string. `<div class="node node-unknown" ...>`.
        return `<div class="${shellClass} node-unknown" data-id="${escapeHtml(id)}" data-node-type="${escapeHtml(rawType)}" style="background:#f5f5f5;color:#666;border:1px dashed #ccc;padding:8px;">${escapeHtml(label)}</div>`;
    }
    const el = doc.createElement('div');
    el.className = `${shellClass} node-unknown`;
    el.dataset.id = id;
    el.dataset.nodeType = rawType;
    el.style.background = '#f5f5f5';
    el.style.color = '#666';
    el.style.border = '1px dashed #ccc';
    el.style.padding = '8px';
    el.textContent = label;
    return el;
}

// tryRender returns the registered entry OR null. It does NOT invoke the
// entry — the caller (legacy `renderNode`) owns the DOM assembly so we
// can `body.appendChild(entry.renderBody(node))` byte-equivalent with the
// existing branch (Wave 3-I 决策 2: 认领而非重写).
function tryRender(node) {
    if (!node) return null;
    return get(node.type);
}

const NodeRenderRegistry = {
    register,
    get,
    has,
    list,
    clear,
    tryRender,
    renderFallback,
};

export default NodeRenderRegistry;
export { register, get, has, list, clear, tryRender, renderFallback };
