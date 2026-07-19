// static/js/modules/canvas/renderer/connections.js
//
// 前端 PR-6：Canvas 连线渲染 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（seam 期硬约束 · 认领而非重写）：
//   - `canvas.js` / `smart-canvas.js` 保留 `renderConnections()` /
//     `renderLinks()` / SVG 图层构造现有实现；本模块提供两 SVG 图层
//     分层契约与访问器。
//   - **两 SVG 图层分层** 是本 PR 引入的抽象：稳定连线 SVG（stable）
//     与拖拽临时连线 SVG（dragging）逻辑上区分，图层实体可以是同一
//     `<svg>` 元素中的两个 `<g>` group（保活期），或未来 M7 拆分为
//     两个独立 `<svg>` 元素。
//   - **落盘 shape 冻结**（`compat-contract.md` §9 / §13）：
//       经典画布连线：`{id, from, to}`
//       智能画布连线：`{from, to, kind}`
//     两画布的 `saveCanvas()` 落盘时保持原 shape 不动。
//
// 使用示例：
//     import { registerConnectionsAdapter, renderConnections, LAYER_KINDS } from
//         '/static/js/modules/canvas/renderer/connections.js';
//     registerConnectionsAdapter('classic', {
//         renderConnections: () => window.__renderLinks?.(),
//         getStableLayer: () => document.getElementById('links'),
//         getDraggingLayer: () => document.getElementById('links'),
//     });

/** 分层图层 kind（**冻结**）——stable：稳定连线；dragging：拖拽期临时连线 */
export const LAYER_KINDS = Object.freeze(['stable', 'dragging']);

/**
 * 经典画布连线 shape 字段（**冻结**——`compat-contract.md` §13）
 */
export const CLASSIC_CONNECTION_FIELDS = Object.freeze(['id', 'from', 'to']);

/**
 * 智能画布连线 shape 字段（**冻结**——`compat-contract.md` §13）
 */
export const SMART_CONNECTION_FIELDS = Object.freeze(['from', 'to', 'kind']);

const adapters = new Map();

export function registerConnectionsAdapter(canvasKind, adapter) {
  if (!canvasKind || typeof canvasKind !== 'string') {
    throw new Error('registerConnectionsAdapter: canvasKind 必填');
  }
  if (!adapter || typeof adapter !== 'object') {
    throw new Error('registerConnectionsAdapter: adapter 必须是对象');
  }
  adapters.set(canvasKind, adapter);
}

export function getConnectionsAdapter(canvasKind) {
  return adapters.get(canvasKind) || null;
}

/**
 * 派发到 adapter 的 `renderConnections()`（对齐两画布现有 `renderLinks` /
 * `renderConnections` 全局函数）。
 */
export function renderConnections(canvasKind) {
  const adapter = getConnectionsAdapter(canvasKind);
  return adapter?.renderConnections?.() ?? null;
}

/** 返回 stable 图层节点（供拖拽或未来 M7 拆图层使用） */
export function getStableLayer(canvasKind) {
  const adapter = getConnectionsAdapter(canvasKind);
  return adapter?.getStableLayer?.() || null;
}

/** 返回 dragging 图层节点（tempLink 期临时线画在这里） */
export function getDraggingLayer(canvasKind) {
  const adapter = getConnectionsAdapter(canvasKind);
  return adapter?.getDraggingLayer?.() || null;
}

/**
 * 落盘 shape 校验（不改写数据；仅返回布尔）：
 *   - `classic` 期望 `{id, from, to}`（`id` 可选，`from`/`to` 必填）
 *   - `smart` 期望 `{from, to, kind}`（`kind` 可选，`from`/`to` 必填）
 * 用于 CI 抗回归测试。
 */
export function validateConnectionShape(canvasKind, connection) {
  if (!connection || typeof connection !== 'object') return false;
  if (canvasKind === 'classic') {
    return typeof connection.from === 'string' && typeof connection.to === 'string';
  }
  if (canvasKind === 'smart') {
    return typeof connection.from === 'string' && typeof connection.to === 'string';
  }
  return false;
}

export function _resetConnectionsAdaptersForTests() {
  adapters.clear();
}

export default {
  LAYER_KINDS,
  CLASSIC_CONNECTION_FIELDS,
  SMART_CONNECTION_FIELDS,
  registerConnectionsAdapter,
  getConnectionsAdapter,
  renderConnections,
  getStableLayer,
  getDraggingLayer,
  validateConnectionShape,
};
