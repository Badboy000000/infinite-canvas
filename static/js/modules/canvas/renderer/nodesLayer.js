// static/js/modules/canvas/renderer/nodesLayer.js
//
// 前端 PR-6：Canvas 节点根元素容器 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（seam 期硬约束 · 认领而非重写）：
//   - **不改节点体渲染**（`renderImageBody` / `renderPromptBody` 留给 PR-7）。
//   - 本模块只承担**节点根元素容器**契约：`.node` class + `data-id` 属性冻结。
//   - `canvas.js` / `smart-canvas.js` 保留 `renderNode()` 与 `world` 容器实现。
//
// 冻结要点（`compat-contract.md` §9）：
//   - 节点根元素 class：`.node` / `.image-node`（智能画布）不改。
//   - 节点 id 属性：`data-id` 不改（不改为 `data-node-id` / `id`）。
//   - `renderShell` 由 PR-7 统一实现，本 PR 不涉及。

/** 节点根元素 class 名（**冻结**） */
export const NODE_CLASS_NAMES = Object.freeze({
  classic: 'node',
  smart: 'image-node',
});

/** 节点 id 属性名（**冻结**） */
export const NODE_ID_ATTR = 'data-id';

const adapters = new Map();

export function registerNodesLayerAdapter(canvasKind, adapter) {
  if (!adapter || typeof adapter !== 'object') {
    throw new Error('registerNodesLayerAdapter: adapter 必须是对象');
  }
  adapters.set(canvasKind, adapter);
}

export function getNodesLayerAdapter(canvasKind) {
  return adapters.get(canvasKind) || null;
}

/**
 * 从 DOM 中按 data-id 查找节点根元素。
 * @param {string} canvasKind
 * @param {string} nodeId
 * @returns {HTMLElement|null}
 */
export function findNodeElement(canvasKind, nodeId) {
  const adapter = getNodesLayerAdapter(canvasKind);
  if (adapter?.findNodeElement) return adapter.findNodeElement(nodeId);
  if (typeof document === 'undefined') return null;
  // 兜底：全局 querySelector（供未 register 时使用）
  const cls = NODE_CLASS_NAMES[canvasKind] || 'node';
  return document.querySelector(`.${cls}[${NODE_ID_ATTR}="${cssEscape(nodeId)}"]`);
}

function cssEscape(v) {
  if (typeof v !== 'string') return '';
  if (typeof CSS !== 'undefined' && typeof CSS.escape === 'function') return CSS.escape(v);
  // 简易 fallback：仅转义常见字符
  return v.replace(/["\\]/g, '\\$&');
}

/** 返回节点容器元素（`world` 或等价） */
export function getNodesContainer(canvasKind) {
  const adapter = getNodesLayerAdapter(canvasKind);
  return adapter?.getNodesContainer?.() || null;
}

export function _resetNodesLayerAdaptersForTests() {
  adapters.clear();
}

export default {
  NODE_CLASS_NAMES,
  NODE_ID_ATTR,
  registerNodesLayerAdapter,
  getNodesLayerAdapter,
  findNodeElement,
  getNodesContainer,
};
