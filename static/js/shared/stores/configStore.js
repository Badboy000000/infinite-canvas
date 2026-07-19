// static/js/shared/stores/configStore.js
//
// 前端 PR-5：Config store（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 语义：承接 `BroadcastChannel('studio-api')` 与 `broadcastStudioApiChange` 函数名 wrapper；
// 保存 `/api/config` 返回的公共配置（image_models / chat_models / video_models / comfy_instances / api_providers 等）。
//
// 兼容硬约束：
//   - `broadcastStudioApiChange` 函数名必须保留（compat-contract §6 冻结；
//     消费方 `api-settings.js:332` / `comfyui-settings.js:3` / smoke checklist §14）。
//   - `providers-changed` / `workflows-changed` / `comfy-instances-changed` 三个 type 字符串不改。
//
// 频道名 `studio-api` 与消息 type 由 shared/messaging（前端 PR-3）承接；本 store 只做数据面 + 兼容 wrapper。

import { createStore } from './_createStore.js';
import { apiClient } from '../api-client/client.js';

export const CONFIG_BROADCAST_TYPES = Object.freeze([
  'providers-changed',
  'workflows-changed',
  'comfy-instances-changed',
]);

async function fetchConfig() {
  try {
    const cfg = await apiClient.get('/api/config');
    return cfg && typeof cfg === 'object' ? cfg : {};
  } catch (_) {
    return {};
  }
}

export const configStore = createStore({
  name: 'config',
  initialState: {
    image_models: [],
    chat_models: [],
    video_models: [],
    ms_chat_models: [],
    api_providers: [],
    comfy_instances: [],
  },
  fetcher: async () => {
    const cfg = await fetchConfig();
    return {
      image_models: Array.isArray(cfg.image_models) ? cfg.image_models : [],
      chat_models: Array.isArray(cfg.chat_models) ? cfg.chat_models : [],
      video_models: Array.isArray(cfg.video_models) ? cfg.video_models : [],
      ms_chat_models: Array.isArray(cfg.ms_chat_models) ? cfg.ms_chat_models : [],
      api_providers: Array.isArray(cfg.api_providers) ? cfg.api_providers : [],
      comfy_instances: Array.isArray(cfg.comfy_instances) ? cfg.comfy_instances : [],
    };
  },
});

/**
 * 保留原函数名 wrapper（compat-contract §6 冻结）；内部委派 studio-api BroadcastChannel。
 * 消费方（api-settings.js / comfyui-settings.js）无需改，`window.broadcastStudioApiChange`
 * 由 bootstrap.js 挂载。
 */
export function broadcastStudioApiChange(type = 'providers-changed') {
  if (!CONFIG_BROADCAST_TYPES.includes(type)) {
    // 允许 pass-through 但打印警告：前端 PR-3 已允许通过 messaging bus 转发。
    if (globalThis.console) console.warn('[configStore] unknown broadcast type:', type);
  }
  const message = { type, updated_at: Date.now() };
  try {
    const bc = new BroadcastChannel('studio-api');
    bc.postMessage(message);
    bc.close();
  } catch (_) {}
  // 同时也 invalidate 本 store（订阅方按需 refetch）。
  configStore.invalidate(type);
  return message;
}
