// static/js/shared/stores/index.js
//
// 前端 PR-5：`shared/stores` 六件套模块索引（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 用法：
//   import {
//     providersStore, workflowsStore, configStore,
//     canvasMetaStore, assetLibraryStore, promptStore,
//     broadcastStudioApiChange,
//   } from '/static/js/shared/stores/index.js';
//
// 非模块页面通过 `bootstrap.js` → `window.stores` 消费。

export { createStore } from './_createStore.js';
export {
  providersStore,
  sanitizeProvider,
  findCredentialLeaks,
  credentialSafe,
  FORBIDDEN_CREDENTIAL_FIELDS,
} from './providersStore.js';
export { workflowsStore, WORKFLOW_KINDS } from './workflowsStore.js';
export { configStore, broadcastStudioApiChange, CONFIG_BROADCAST_TYPES } from './configStore.js';
export {
  canvasMetaStore,
  upsertCanvasMeta,
  upsertManyCanvasMeta,
  setActiveCanvas,
  CANVAS_META_FIELDS,
} from './canvasMetaStore.js';
export { assetLibraryStore, applyAssetLibrarySnapshot } from './assetLibraryStore.js';
export { promptStore, readLegacyPromptSnapshot, refreshPromptSnapshot, PROMPT_LEGACY_KEYS } from './promptStore.js';
