// static/js/modules/canvas/interactions/marquee.js
//
// 前端 PR-6：框选（marquee）seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位：
//   - `canvas.js` / `smart-canvas.js` 现有框选实现保留（`selectionState` 变量
//     承载）；本模块提供**纯函数**辅助：矩形正规化、命中集合计算。
//   - 与 `drag.js` 的 `selectionState` session kind 配合使用（互斥表）。

import { rectsIntersect } from '../renderer/hitTest.js';

/**
 * 从起止两个屏幕/世界坐标点归一化为矩形 {x, y, width, height}（右下角为正）。
 * @param {{x:number,y:number}} start
 * @param {{x:number,y:number}} end
 */
export function normalizeMarqueeRect(start, end) {
  if (!start || !end) return { x: 0, y: 0, width: 0, height: 0 };
  const x1 = Math.min(start.x, end.x);
  const y1 = Math.min(start.y, end.y);
  const x2 = Math.max(start.x, end.x);
  const y2 = Math.max(start.y, end.y);
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}

/**
 * 计算与 marquee 相交的节点 id 集合。
 * @param {{x:number,y:number,width:number,height:number}} marquee
 * @param {Array<{id:string,x:number,y:number,w?:number,h?:number,width?:number,height?:number}>} nodes
 * @returns {string[]}
 */
export function nodesIntersectingMarquee(marquee, nodes) {
  if (!marquee || !Array.isArray(nodes)) return [];
  const out = [];
  for (const node of nodes) {
    if (!node || !node.id) continue;
    const rect = {
      x: Number(node.x) || 0,
      y: Number(node.y) || 0,
      width: Number(node.w ?? node.width ?? 0),
      height: Number(node.h ?? node.height ?? 0),
    };
    if (rectsIntersect(marquee, rect)) out.push(node.id);
  }
  return out;
}

export default {
  normalizeMarqueeRect,
  nodesIntersectingMarquee,
};
