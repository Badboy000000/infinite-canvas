// static/js/modules/canvas/interactions/wheel-zoom.js
//
// 前端 PR-6：滚轮缩放 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（seam 期硬约束）：
//   - **保留两画布各自的缩放上下限与中心策略**（任务书硬约束）：
//     经典画布：`board.onwheel`  factor = `e.deltaY > 0 ? 0.92 : 1.08`，无 clamp
//                （`canvas.js:14599-14611`）。
//     智能画布：`shell.wheel`    factor = `Math.exp(-e.deltaY * 0.001)`，
//                经过 `safeScale` clamp（`smart-canvas.js:16154-16167`）。
//   - 本模块**不合并策略**；只提供工具函数与登记表，供两画布内部消费。
//
// 冻结要点（`compat-contract.md` §11 邻接 + 现状事实）：
//   - 双击手势不迁移（各自不同）。
//   - `viewport.scale = viewport.scale * factor` 计算顺序保持不变。

/** 缩放策略描述——**冻结事实源**（不作为业务参数，仅供文档/测试） */
export const ZOOM_STRATEGIES = Object.freeze({
  classic: Object.freeze({
    factorFn: 'deltaY > 0 ? 0.92 : 1.08',
    clamp: 'none',
    center: 'board.getBoundingClientRect',
    source: 'canvas.js:14599-14611',
  }),
  smart: Object.freeze({
    factorFn: 'Math.exp(-deltaY * 0.001)',
    clamp: 'safeScale (positive-only)',
    center: 'shell.getBoundingClientRect',
    source: 'smart-canvas.js:16154-16167',
  }),
});

/**
 * 经典画布缩放 factor（纯函数，无副作用；供测试与迁移期兜底）。
 * @param {number} deltaY
 * @returns {number}
 */
export function classicZoomFactor(deltaY) {
  return deltaY > 0 ? 0.92 : 1.08;
}

/**
 * 智能画布缩放 factor（纯函数）。
 * @param {number} deltaY
 * @returns {number}
 */
export function smartZoomFactor(deltaY) {
  return Math.exp(-Number(deltaY) * 0.001);
}

/**
 * 计算滚轮缩放后新 viewport（供 canvasEditStore 或测试消费）。
 * 保留两画布各自策略；`safeScaleFn` 由 adapter 提供。
 *
 * @param {'classic'|'smart'} canvasKind
 * @param {{x:number,y:number,scale:number}} viewport
 * @param {{clientX:number,clientY:number,deltaY:number,rectLeft?:number,rectTop?:number}} event
 * @param {(v:number)=>number} [safeScaleFn]
 * @returns {{x:number,y:number,scale:number}}
 */
export function computeZoomedViewport(canvasKind, viewport, event, safeScaleFn) {
  if (!viewport || !event) return viewport;
  const rectLeft = event.rectLeft || 0;
  const rectTop = event.rectTop || 0;
  const sx = event.clientX - rectLeft;
  const sy = event.clientY - rectTop;
  const before = {
    x: (sx - viewport.x) / viewport.scale,
    y: (sy - viewport.y) / viewport.scale,
  };
  let factor;
  if (canvasKind === 'classic') factor = classicZoomFactor(event.deltaY);
  else if (canvasKind === 'smart') factor = smartZoomFactor(event.deltaY);
  else factor = 1;
  let nextScale = viewport.scale * factor;
  if (typeof safeScaleFn === 'function') nextScale = safeScaleFn(nextScale);
  return {
    x: sx - before.x * nextScale,
    y: sy - before.y * nextScale,
    scale: nextScale,
  };
}

export default {
  ZOOM_STRATEGIES,
  classicZoomFactor,
  smartZoomFactor,
  computeZoomedViewport,
};
