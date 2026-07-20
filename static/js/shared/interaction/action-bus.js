// shared/interaction/action-bus.js
//
// Top-level `data-action` event delegation. Wave 3-I / 前端 PR-7 决策 6:
// HTML 静态骨架 (工具栏 / 顶栏 / 菜单) 的 `onclick="fooBar()"` 迁至
// `data-action="fooBar"` + this bus.
//
// Contract:
// - Zero build / zero dependencies. Native ES module.
// - Handlers are registered as `(name, handler)` pairs. The handler receives
//   `(event, element)` — the click event and the element that carried the
//   `data-action` attribute.
// - A single global click listener resolves `data-action="..."` via
//   `event.target.closest('[data-action]')` and dispatches to the registered
//   handler if it exists. If no handler is registered the bus does nothing
//   and lets the click propagate normally (which allows legacy inline
//   `onclick=...` handlers on the SAME element to still fire — overlap is
//   fine because 决策 8: 老全局函数 switchUI / menuAdd / addImageNode 保留
//   可用).
// - `install(root)` attaches the delegated listener. Called at most once
//   per root. In the browser the bootstrap script calls `install(document)`.
// - Handlers can be looked up via `get(name)` and enumerated via `list()`
//   for tests.
//
// Convention: handler names use camelCase to mirror the legacy global
// function names (e.g. `data-action="addImageNode"` -> `addImageNode`).

const handlers = new Map();
const installedRoots = new WeakSet();

function register(name, handler) {
    if (!name || typeof name !== 'string') {
        throw new Error('action-bus.register: name must be a non-empty string');
    }
    if (typeof handler !== 'function') {
        throw new Error(`action-bus.register(${name}): handler must be a function`);
    }
    handlers.set(name, handler);
}

function unregister(name) {
    handlers.delete(name);
}

function get(name) {
    return handlers.get(name) || null;
}

function has(name) {
    return handlers.has(name);
}

function list() {
    return [...handlers.keys()];
}

function clear() {
    handlers.clear();
}

// dispatch is the primary hook. Given a click event, walk to the nearest
// element carrying a `data-action` attribute and dispatch to the registered
// handler if present. Returns `true` when a handler was invoked so callers
// can decide whether to preventDefault.
function dispatch(event) {
    if (!event || !event.target || typeof event.target.closest !== 'function') return false;
    const el = event.target.closest('[data-action]');
    if (!el) return false;
    const name = el.getAttribute('data-action');
    if (!name) return false;
    const handler = handlers.get(name);
    if (!handler) return false;
    try {
        handler(event, el);
    } catch (err) {
        // Contract: dispatch never throws. Errors are surfaced through the
        // console so operators can diagnose without breaking the click flow.
        if (typeof console !== 'undefined' && console.error) {
            console.error(`[action-bus] handler ${name} threw`, err);
        }
    }
    return true;
}

function install(root) {
    if (!root || typeof root.addEventListener !== 'function') return false;
    if (installedRoots.has(root)) return false;
    root.addEventListener('click', dispatch, true);
    installedRoots.add(root);
    return true;
}

// autoBindLegacyGlobals wires the given handler names to `window.<name>` so
// existing global functions (switchUI / menuAdd / addImageNode / ...) can be
// migrated in place: `<button data-action="addImageNode">` will call
// `window.addImageNode()` without an explicit register() call. This preserves
// the "老全局函数保留可用" invariant while removing the need to hand-migrate
// every button (Wave 3-I 决策 8).
function autoBindLegacyGlobals(names, opts) {
    const options = opts || {};
    const scope = options.window || (typeof window !== 'undefined' ? window : null);
    if (!scope) return [];
    const bound = [];
    (names || []).forEach((name) => {
        if (typeof scope[name] === 'function') {
            register(name, function autoBindHandler(event, el) {
                try {
                    // Optional data-action-arg support: comma-separated string
                    // args become positional parameters. Numeric strings stay
                    // strings — call sites that need coercion (e.g. index)
                    // must coerce themselves. This preserves the original
                    // inline `onclick="menuAdd('image')"` behaviour where the
                    // handler receives a single string argument.
                    const argAttr = el && typeof el.getAttribute === 'function' ? el.getAttribute('data-action-arg') : null;
                    if (argAttr != null && argAttr !== '') {
                        const parts = argAttr.split(',').map((p) => p.trim());
                        scope[name].apply(scope, parts);
                    } else {
                        scope[name](event);
                    }
                } catch (err) {
                    if (typeof console !== 'undefined' && console.error) {
                        console.error(`[action-bus] auto-bound legacy ${name} threw`, err);
                    }
                }
            });
            bound.push(name);
        }
    });
    return bound;
}

const actionBus = {
    register,
    unregister,
    get,
    has,
    list,
    clear,
    dispatch,
    install,
    autoBindLegacyGlobals,
};

export default actionBus;
export {
    register,
    unregister,
    get,
    has,
    list,
    clear,
    dispatch,
    install,
    autoBindLegacyGlobals,
};
