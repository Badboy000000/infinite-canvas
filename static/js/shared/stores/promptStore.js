// static/js/shared/stores/promptStore.js
//
// 前端 PR-5：Prompt store（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 语义：内部合并**五个 legacy localStorage key**的**读取**面（compat-contract §4.5 冻结要点：不合并 key 本身，
// 仅在 store 内合并读取），供 canvas.js / smart-canvas.js 单一订阅面消费。写操作仍走各自原 key（保活）。
//
// 五个 key（compat-contract §4.1–§4.4）：
//   1. `canvas_prompt_template_groups_v1`         —— canvas.js:420, :7126, :7136
//   2. `canvas_prompt_template_overrides`          —— canvas.js:421, :7140, :7150
//   3. `smart_canvas_prompt_presets_v1`            —— smart-canvas.js:114, :4148, :4155
//   4. `smart_canvas_prompt_template_groups_v1`    —— smart-canvas.js:115, :4169, :4179
//   5. `smart_canvas_prompt_template_overrides_v1` —— smart-canvas.js:116, :4183, :4193
//
// **key 名不变、不合并；不改 shape**（§4.5 硬约束）。

import { createStore } from './_createStore.js';

export const PROMPT_LEGACY_KEYS = Object.freeze({
  canvasTemplateGroups: 'canvas_prompt_template_groups_v1',
  canvasTemplateOverrides: 'canvas_prompt_template_overrides',
  smartPresets: 'smart_canvas_prompt_presets_v1',
  smartTemplateGroups: 'smart_canvas_prompt_template_groups_v1',
  smartTemplateOverrides: 'smart_canvas_prompt_template_overrides_v1',
});

function safeReadJson(key, fallback) {
  try {
    const raw = (typeof localStorage !== 'undefined') ? localStorage.getItem(key) : null;
    if (raw == null || raw === '') return fallback;
    const parsed = JSON.parse(raw);
    return parsed == null ? fallback : parsed;
  } catch (_) {
    return fallback;
  }
}

/**
 * 从五个 localStorage key **读取合并**：返回一个只读的合并视图。
 * 注意：不写 localStorage、不合并 key 本身；只是 store 内部提供一次性快照。
 */
export function readLegacyPromptSnapshot() {
  return {
    canvas: {
      templateGroups: safeReadJson(PROMPT_LEGACY_KEYS.canvasTemplateGroups, []),
      templateOverrides: safeReadJson(PROMPT_LEGACY_KEYS.canvasTemplateOverrides, {}),
    },
    smart: {
      presets: safeReadJson(PROMPT_LEGACY_KEYS.smartPresets, []),
      templateGroups: safeReadJson(PROMPT_LEGACY_KEYS.smartTemplateGroups, []),
      templateOverrides: safeReadJson(PROMPT_LEGACY_KEYS.smartTemplateOverrides, {}),
    },
  };
}

export const promptStore = createStore({
  name: 'prompt',
  initialState: readLegacyPromptSnapshot(),
  fetcher: async () => readLegacyPromptSnapshot(),
});

/**
 * 页面侧显式触发一次 legacy 快照重读（当页面已知刚刚写入了某个 key）。
 */
export function refreshPromptSnapshot(reason = 'legacy-reload') {
  promptStore.setState(readLegacyPromptSnapshot(), reason);
}
