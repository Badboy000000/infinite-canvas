// static/js/modules/canvas/interactions/pointer.js
//
// 前端 PR-6：Pointer 事件路由 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位：
//   - **合并 mouse / touch 输入**：seam 期本模块**不重写** `touch-mouse.js`
//     桥接层（现状：`static/js/touch-mouse.js` 在 body 加载最早，负责把
//     单指 touch → mouse、双指捏合 → wheel）；本模块提供 pointer 事件
//     path 分类与派发契约。
//   - **不引入 `pointercancel` 一次性重构**（任务书硬约束）：`touch-mouse.js`
//     保留可用；本模块不接管其 skip 规则，只对 mouse 事件走 pointer 路由。
//
// 输入 kind（**冻结**）：
export const POINTER_INPUT_KINDS = Object.freeze(['mouse', 'touch', 'pen']);

const adapters = new Map();

export function registerPointerAdapter(canvasKind, adapter) {
  if (!adapter || typeof adapter !== 'object') {
    throw new Error('registerPointerAdapter: adapter 必须是对象');
  }
  adapters.set(canvasKind, adapter);
}

export function getPointerAdapter(canvasKind) {
  return adapters.get(canvasKind) || null;
}

/** 从事件推断输入 kind（供 shouldSkip 与 hit 分类使用） */
export function inputKindFromEvent(event) {
  if (!event) return 'mouse';
  // PointerEvent
  if (typeof event.pointerType === 'string') {
    if (event.pointerType === 'touch') return 'touch';
    if (event.pointerType === 'pen') return 'pen';
    return 'mouse';
  }
  // TouchEvent
  if (typeof event.touches !== 'undefined') return 'touch';
  return 'mouse';
}

export function _resetPointerAdaptersForTests() {
  adapters.clear();
}

export default {
  POINTER_INPUT_KINDS,
  registerPointerAdapter,
  getPointerAdapter,
  inputKindFromEvent,
};
