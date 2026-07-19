// static/js/modules/canvas/interactions/hotkey.js
//
// 前端 PR-6：热键路由 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（seam 期）：
//   - **认领而非重写**：`canvas.js` / `smart-canvas.js` 现有 `keydown` /
//     `keyup` 处理保留；本模块提供**登记表**，未来 PR-7/PR-8 迁移时统一
//     入口。
//   - 焦点安全：输入框内 hotkey 屏蔽由 `focus.js` 承担；本模块调用
//     `shouldSuppressHotkey(event)` 前置判定。
//
// 冻结要点：
//   - 现有全局函数（`switchUI` / `menuAdd` / `addImageNode` 等）保留可用。

/** 热键描述子（key + modifiers）——冻结 shape */
export const HOTKEY_MODIFIERS = Object.freeze(['ctrl', 'alt', 'shift', 'meta']);

function createHotkeyRegistry() {
  /** @type {Map<string, Function>} */
  const bindings = new Map();

  function normalizeCombo(descriptor) {
    if (typeof descriptor === 'string') return descriptor.toLowerCase();
    if (!descriptor || typeof descriptor !== 'object') return '';
    const mods = [];
    HOTKEY_MODIFIERS.forEach(m => { if (descriptor[m]) mods.push(m); });
    mods.sort();
    const key = String(descriptor.key || '').toLowerCase();
    return [...mods, key].filter(Boolean).join('+');
  }

  function register(descriptor, handler) {
    const combo = normalizeCombo(descriptor);
    if (!combo) throw new Error('register: descriptor 无效');
    if (typeof handler !== 'function') throw new TypeError('register: handler 必须是函数');
    bindings.set(combo, handler);
    return () => bindings.delete(combo);
  }

  function comboFromEvent(event) {
    if (!event) return '';
    const mods = [];
    if (event.ctrlKey) mods.push('ctrl');
    if (event.altKey) mods.push('alt');
    if (event.shiftKey) mods.push('shift');
    if (event.metaKey) mods.push('meta');
    mods.sort();
    const key = String(event.key || '').toLowerCase();
    return [...mods, key].filter(Boolean).join('+');
  }

  function dispatch(event) {
    const combo = comboFromEvent(event);
    const handler = bindings.get(combo);
    if (handler) {
      try { return handler(event); }
      catch (err) {
        if (globalThis.console) console.error('[hotkey] handler failed:', err);
        return undefined;
      }
    }
    return undefined;
  }

  function _resetForTests() {
    bindings.clear();
  }

  return Object.freeze({
    register,
    dispatch,
    normalizeCombo,
    comboFromEvent,
    _resetForTests,
    size: () => bindings.size,
  });
}

export const hotkey = createHotkeyRegistry();

export default hotkey;
