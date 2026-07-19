// static/js/shared/interaction/pointer/should-skip.js
//
// 前端 PR-6：touch-mouse.js skip 规则语义快照锁死（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位（**语义等价快照** · seam 期硬约束）：
//   - `static/js/touch-mouse.js:23-34` 定义的 `shouldSkip(target)` 是**跨版本
//     稳定契约**：触屏 → 鼠标事件桥接的短路规则。任务书要求**语义等价必须
//     完全一致**：
//
//         function shouldSkip(target){
//             if(!(target instanceof Element)) return true;
//             if(target.closest('input, textarea, select, audio, video, [contenteditable=""], [contenteditable="true"]')) return true;
//             let node = target;
//             while(node && node !== document.body && node !== document.documentElement){
//                 const cs = getComputedStyle(node);
//                 if(/(auto|scroll)/.test(cs.overflowY) && node.scrollHeight > node.clientHeight + 1) return true;
//                 if(/(auto|scroll)/.test(cs.overflowX) && node.scrollWidth > node.clientWidth + 1) return true;
//                 node = node.parentElement;
//             }
//             return false;
//         }
//
//   - 本模块**不删除** `touch-mouse.js`（`compat-contract.md` 冻结要点 +
//     任务书硬约束）；作为下游未来消费点提供**同语义**独立入口，用于：
//     * PR-7+ 迁移热键 / 交互路由时的短路判定
//     * 单元测试对 skip 规则的锁死（防止两处漂移）
//
// 冻结要点：
//   - 语义与 `touch-mouse.js` **完全一致**；任何改动必须同时改两处，且测试
//     `test_canvas_renderer_seam.py::test_should_skip_matches_touch_mouse_bridge`
//     必须绿。
//   - `static/js/touch-mouse.js` 桥接层不删除。

/** 输入类元素 selector（与 touch-mouse.js 同源） */
export const INPUT_SELECTOR = 'input, textarea, select, audio, video, [contenteditable=""], [contenteditable="true"]';

/**
 * 语义等价 `touch-mouse.js:shouldSkip`。
 * @param {EventTarget|null} target
 * @returns {boolean}
 */
export function shouldSkip(target) {
  if (typeof Element === 'undefined') return true;
  if (!(target instanceof Element)) return true;
  if (target.closest(INPUT_SELECTOR)) return true;
  // scrollable ancestor 检测
  if (typeof getComputedStyle !== 'function') return false;
  let node = target;
  const body = typeof document !== 'undefined' ? document.body : null;
  const html = typeof document !== 'undefined' ? document.documentElement : null;
  while (node && node !== body && node !== html) {
    const cs = getComputedStyle(node);
    if (cs) {
      if (/(auto|scroll)/.test(cs.overflowY) && node.scrollHeight > node.clientHeight + 1) return true;
      if (/(auto|scroll)/.test(cs.overflowX) && node.scrollWidth > node.clientWidth + 1) return true;
    }
    node = node.parentElement;
  }
  return false;
}

/**
 * 语义快照（供测试断言）：返回描述当前 skip 规则的**字面量结构**，防止未来
 * 悄悄改动 selector 或滚动检测阈值。
 */
export function skipRuleSnapshot() {
  return Object.freeze({
    inputSelector: INPUT_SELECTOR,
    scrollDetection: {
      overflowRegex: '/(auto|scroll)/',
      scrollHeightThreshold: 'scrollHeight > clientHeight + 1',
      scrollWidthThreshold: 'scrollWidth > clientWidth + 1',
    },
    boundary: 'stops at document.body / document.documentElement',
    source: 'static/js/touch-mouse.js:23-34',
    version: '2026-07-19',  // 变动时同步 touch-mouse.js 并 bump 版本
  });
}

export default {
  INPUT_SELECTOR,
  shouldSkip,
  skipRuleSnapshot,
};
