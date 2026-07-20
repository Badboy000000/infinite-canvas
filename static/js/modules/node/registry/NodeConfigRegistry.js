// modules/node/registry/NodeConfigRegistry.js
//
// Registry (seam-only) for per-`type` **static** configuration used by the
// renderer / interaction layer: default size, display title lookup, port
// eligibility, whether the status badge should appear, and legacy aliases.
//
// Design contract (see 40 实施计划/前端组件化治理实施计划与PR清单#PR-7):
// - Zero build / zero dependencies. Native ES module.
// - Registration is purely additive; unregistered types resolve via `null`
//   so the caller (legacy `renderNode`) can fall through to its existing
//   branch or the placeholder fallback owned by `NodeRenderRegistry`.
// - `smart-container -> smart-image` legacy alias lives here so both canvases
//   can look up the effective type name in one place.
//
// This module intentionally does NOT touch DOM. It is a plain map + a few
// helpers, exported as a default object for symmetry with `NodeRenderRegistry`.

const registry = new Map();
const aliases = new Map();

function normalizeAlias(type) {
    if (type == null) return type;
    const canonical = aliases.get(type);
    return canonical == null ? type : canonical;
}

function register(type, config) {
    if (type == null || type === '') {
        throw new Error('NodeConfigRegistry.register: type must be a non-empty string');
    }
    if (config == null || typeof config !== 'object') {
        throw new Error(`NodeConfigRegistry.register(${type}): config must be an object`);
    }
    registry.set(type, Object.freeze({ ...config, type }));
}

function registerLegacyAlias(legacy, canonical) {
    if (!legacy || !canonical) {
        throw new Error('NodeConfigRegistry.registerLegacyAlias: legacy and canonical required');
    }
    aliases.set(legacy, canonical);
}

function get(type) {
    const canonical = normalizeAlias(type);
    return registry.get(canonical) || null;
}

function has(type) {
    const canonical = normalizeAlias(type);
    return registry.has(canonical);
}

function list() {
    return [...registry.keys()];
}

function listAliases() {
    return [...aliases.entries()].map(([legacy, canonical]) => ({ legacy, canonical }));
}

function clear() {
    registry.clear();
    aliases.clear();
}

// Built-in legacy alias per Wave 3-I / 前端 PR-7 决策 7:
// `smart-container` was renamed to `smart-image` upstream. Renderer maps at
// this layer so the backend NodeType is not touched.
registerLegacyAlias('smart-container', 'smart-image');

const NodeConfigRegistry = {
    register,
    registerLegacyAlias,
    get,
    has,
    list,
    listAliases,
    normalizeAlias,
    clear,
};

export default NodeConfigRegistry;
export { register, registerLegacyAlias, get, has, list, listAliases, normalizeAlias, clear };
