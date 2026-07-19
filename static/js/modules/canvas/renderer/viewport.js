// static/js/modules/canvas/renderer/viewport.js
//
// 前端 PR-6：Canvas 视口 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（seam 期硬约束）：
//   - **认领而非重写**：`canvas.js` / `smart-canvas.js` 各自保留 `applyViewport()`
//     / `screenToWorld()` / `safeViewportScale|safeScale()` / `board.onwheel` /
//     `shell.addEventListener('wheel')` 现有实现；本模块提供 seam 契约与工具
//     函数，两画布通过 `registerViewportAdapter(canvasKind, adapter)` 认领。
//   - **不迁移 viewport.scale 语义**：经典画布与智能画布的缩放中心 / 上下限 /
//     双击手势策略各自不同，本 seam 只提供 **契约 hook**，不合并策略。
//   - **零构建零依赖**。
//
// 冻结要点（[[docs/frontend-freeze/compat-contract.md]] §11 / §13）：
//   - `viewport.scale` 字段名不改；`0` 作为初始/未知 sentinel 值不改。
//   - 落盘 shape `{x, y, scale}` 不变（由 `canvas.js` / `smart-canvas.js` 侧
//     `canvasForStorage()` / `saveCanvas()` 保持）。
//
// 使用示例：
//     import { registerViewportAdapter, applyViewport } from '/static/js/modules/canvas/renderer/viewport.js';
//     registerViewportAdapter('classic', {
//         applyViewport: () => window.__applyViewport?.(),   // canvas.js 提供
//         screenToWorld: (x, y) => window.__screenToWorld?.(x, y),
//         safeScale: v => window.__safeViewportScale?.(v),
//     });
//     applyViewport('classic');

/** canvasKind 白名单；与 MediaEditor 保持一致 */
export const CANVAS_KINDS = Object.freeze(['classic', 'smart']);

/** viewport 落盘 shape 字段冻结（`compat-contract.md` §13） */
export const VIEWPORT_STORAGE_FIELDS = Object.freeze(['x', 'y', 'scale']);

const adapters = new Map();

/**
 * 注册 canvasKind 的 viewport adapter（由两画布 load 时调用）。
 * adapter 提供如下能力（皆可选，缺失走 no-op）：
 *   - `applyViewport()` : 把当前 viewport 应用到 DOM/transform
 *   - `screenToWorld(clientX, clientY)` : 屏幕坐标 → 世界坐标
 *   - `safeScale(value)` : 缩放值 clamp
 *   - `getViewport()` : 读取当前 viewport 对象（{x, y, scale}）
 *   - `setViewport(patch)` : 写入 viewport（不触发保存）
 */
export function registerViewportAdapter(canvasKind, adapter) {
  if (!CANVAS_KINDS.includes(canvasKind)) {
    throw new Error(`registerViewportAdapter: 未知 canvasKind: ${canvasKind}`);
  }
  if (!adapter || typeof adapter !== 'object') {
    throw new Error('registerViewportAdapter: adapter 必须是对象');
  }
  adapters.set(canvasKind, adapter);
}

export function getViewportAdapter(canvasKind) {
  return adapters.get(canvasKind) || null;
}

/** 派发到已注册 adapter 的 `applyViewport()` */
export function applyViewport(canvasKind) {
  const adapter = getViewportAdapter(canvasKind);
  return adapter?.applyViewport?.();
}

/** 派发到已注册 adapter 的 `screenToWorld()` */
export function screenToWorld(canvasKind, clientX, clientY) {
  const adapter = getViewportAdapter(canvasKind);
  return adapter?.screenToWorld?.(clientX, clientY) || null;
}

/**
 * 缩放值 clamp。默认策略：正数保留，其他返回 1。
 * **不设默认上下限**——保留两画布各自策略（经典 `board.onwheel` 无 clamp；
 * 智能 `shell.wheel` 用 `safeScale`）。上下限由 adapter 实现。
 */
export function safeScale(canvasKind, value) {
  const adapter = getViewportAdapter(canvasKind);
  if (adapter?.safeScale) return adapter.safeScale(value);
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : 1;
}

/**
 * 提取 viewport 落盘 shape（不改写原对象，仅返回一个 pick）。
 * 与 `canvasForStorage()` 现有语义等价，供 canvasEditStore 内部使用。
 */
export function pickViewportForStorage(viewport) {
  if (!viewport || typeof viewport !== 'object') return { x: 0, y: 0, scale: 1 };
  const out = {};
  VIEWPORT_STORAGE_FIELDS.forEach(k => {
    if (k in viewport) out[k] = viewport[k];
  });
  if (!('x' in out)) out.x = 0;
  if (!('y' in out)) out.y = 0;
  if (!('scale' in out) || !Number.isFinite(out.scale) || out.scale <= 0) out.scale = 1;
  return out;
}

/** 供测试/reset 使用：清空所有 adapter 注册。 */
export function _resetViewportAdaptersForTests() {
  adapters.clear();
}

export default {
  CANVAS_KINDS,
  VIEWPORT_STORAGE_FIELDS,
  registerViewportAdapter,
  getViewportAdapter,
  applyViewport,
  screenToWorld,
  safeScale,
  pickViewportForStorage,
};
