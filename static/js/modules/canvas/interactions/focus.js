// static/js/modules/canvas/interactions/focus.js
//
// 前端 PR-6：焦点管理 seam（[[前端组件化治理实施计划与PR清单]] PR-6）。
//
// 定位：
//   - 判定当前焦点是否在**输入类元素**上；若是则热键 / 快捷键应屏蔽。
//   - 语义等价于 `touch-mouse.js` 的 shouldSkip 前半段（input/textarea/select
//     /contenteditable），但**独立命名**，避免与滚动容器判定耦合。

/** 输入类元素 selector（**冻结**） */
export const INPUT_SELECTOR = 'input, textarea, select, [contenteditable=""], [contenteditable="true"]';

/**
 * 判定目标是否为输入类元素（供热键屏蔽使用）。
 * @param {EventTarget|null} target
 */
export function isInputTarget(target) {
  if (!target || typeof target.closest !== 'function') return false;
  return !!target.closest(INPUT_SELECTOR);
}

/** 判定当前 activeElement 是否为输入类元素 */
export function isEditableFocused() {
  if (typeof document === 'undefined') return false;
  return isInputTarget(document.activeElement);
}

/**
 * 热键屏蔽判定：输入框内热键屏蔽（避免 canvas 快捷键在文本框里误触发）。
 * @param {KeyboardEvent} event
 */
export function shouldSuppressHotkey(event) {
  if (!event) return false;
  return isInputTarget(event.target) || isEditableFocused();
}

export default {
  INPUT_SELECTOR,
  isInputTarget,
  isEditableFocused,
  shouldSuppressHotkey,
};
