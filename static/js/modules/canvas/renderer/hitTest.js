// static/js/modules/canvas/renderer/hitTest.js
//
// 前端 PR-6：Canvas 命中测试 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（seam 期硬约束 · 认领而非重写）：
//   - `canvas.js` 现有 `hitEditTextItem` / `gridCustomLineHit` / 节点鼠标事件
//     附着 handler 保留；本模块提供 seam 契约与轻量命中判定辅助。
//   - `smart-canvas.js` 现有 `nodeRect` / 事件 delegation 保留。
//   - 未来（M7）把节点 / 端口 / 连线 / 空白区域命中判定统一到本模块。
//
// 命中类型（**冻结枚举**）：
//   - `node`     : 节点体
//   - `port`     : 端口锚点
//   - `link`     : 连线（SVG 折线）
//   - `blank`    : 画布空白区域
//   - `handle`   : resize handle / 交互 handle
//   - `unknown`  : 未分类

/** 命中类型枚举（**冻结**） */
export const HIT_TARGETS = Object.freeze(['node', 'port', 'link', 'blank', 'handle', 'unknown']);

const adapters = new Map();

export function registerHitTestAdapter(canvasKind, adapter) {
  if (!adapter || typeof adapter !== 'object') {
    throw new Error('registerHitTestAdapter: adapter 必须是对象');
  }
  adapters.set(canvasKind, adapter);
}

export function getHitTestAdapter(canvasKind) {
  return adapters.get(canvasKind) || null;
}

/**
 * 从 Event.target 反推命中类型。走 DOM closest 语义（zero-cost）。
 * @param {'classic'|'smart'} canvasKind
 * @param {Event} event
 * @returns {{ target: string, element: Element|null, nodeId: string|null }}
 */
export function classifyHit(canvasKind, event) {
  const el = event?.target instanceof Element ? event.target : null;
  if (!el) return { target: 'unknown', element: null, nodeId: null };
  const adapter = getHitTestAdapter(canvasKind);
  if (adapter?.classifyHit) return adapter.classifyHit(event);
  // 默认策略
  const portEl = el.closest?.('.node-port,[data-port]');
  if (portEl) {
    const nodeEl = portEl.closest?.('.node,.image-node');
    return { target: 'port', element: portEl, nodeId: nodeEl?.dataset?.id || null };
  }
  const handleEl = el.closest?.('.resize-handle,[data-handle]');
  if (handleEl) {
    return { target: 'handle', element: handleEl, nodeId: handleEl.closest?.('.node,.image-node')?.dataset?.id || null };
  }
  const linkEl = el.closest?.('svg .link,svg [data-conn-index],svg .connection');
  if (linkEl) {
    return { target: 'link', element: linkEl, nodeId: null };
  }
  const nodeEl = el.closest?.('.node,.image-node');
  if (nodeEl) {
    return { target: 'node', element: nodeEl, nodeId: nodeEl.dataset?.id || null };
  }
  return { target: 'blank', element: el, nodeId: null };
}

/** 判定命中是否为 blank（供框选/平移逻辑短路使用） */
export function isBlankHit(canvasKind, event) {
  return classifyHit(canvasKind, event).target === 'blank';
}

/** 矩形相交判定（供 marquee 使用；纯函数） */
export function rectsIntersect(a, b) {
  if (!a || !b) return false;
  return !(a.x + a.width < b.x || b.x + b.width < a.x
         || a.y + a.height < b.y || b.y + b.height < a.y);
}

/** 点在矩形内判定 */
export function pointInRect(point, rect) {
  if (!point || !rect) return false;
  return point.x >= rect.x && point.x <= rect.x + rect.width
      && point.y >= rect.y && point.y <= rect.y + rect.height;
}

export function _resetHitTestAdaptersForTests() {
  adapters.clear();
}

export default {
  HIT_TARGETS,
  registerHitTestAdapter,
  getHitTestAdapter,
  classifyHit,
  isBlankHit,
  rectsIntersect,
  pointInRect,
};
