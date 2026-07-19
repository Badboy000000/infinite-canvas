// static/js/shared/stores/bootstrap.js
//
// 前端 PR-5：`shared/stores` 六件套 bootstrap（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 非模块脚本（`<script src>`），通过动态 ESM import 装配 `window.stores`：
//   window.stores = { providers, workflows, config, canvasMeta, assetLibrary, prompt }
// 以及 `window.broadcastStudioApiChange`（compat-contract §6 冻结的兼容 wrapper）。
//
// 用法（6 个 HTML 页面）：
//   <script src="/static/js/shared/stores/bootstrap.js"></script>
//   <script src="/static/js/canvas.js"></script>
//
// canvas.js / smart-canvas.js / asset-manager.js 内的顶层变量 wrapper（getter）
// 以 `window.stores.providers.state.providers` 为投影源；`window.stores` 未就绪时回退空数组 / 空对象。

(function installStoresBootstrap(global) {
  'use strict';

  if (global.__STORES_BOOTSTRAP__) return; // 幂等（同页多次 include 兜底）
  global.__STORES_BOOTSTRAP__ = true;

  const MODULE_URL = '/static/js/shared/stores/index.js';

  const ready = import(MODULE_URL).then(mod => {
    global.stores = Object.freeze({
      providers: mod.providersStore,
      workflows: mod.workflowsStore,
      config: mod.configStore,
      canvasMeta: mod.canvasMetaStore,
      assetLibrary: mod.assetLibraryStore,
      prompt: mod.promptStore,
    });
    // compat-contract §6：`broadcastStudioApiChange` 全局函数名保留 wrapper
    // （seam 期 api-settings.js / comfyui-settings.js 已各自定义同名函数，
    // 这里挂到 window 上作为跨页兜底 —— 覆盖不打破 api-settings.js 内部函数声明作用域）。
    if (typeof global.broadcastStudioApiChange !== 'function') {
      global.broadcastStudioApiChange = mod.broadcastStudioApiChange;
    }
    // 把命名工具暴露到 window.storesUtils（测试用；不作为公开 API）
    global.storesUtils = Object.freeze({
      sanitizeProvider: mod.sanitizeProvider,
      findCredentialLeaks: mod.findCredentialLeaks,
      credentialSafe: mod.credentialSafe,
      readLegacyPromptSnapshot: mod.readLegacyPromptSnapshot,
      upsertCanvasMeta: mod.upsertCanvasMeta,
      applyAssetLibrarySnapshot: mod.applyAssetLibrarySnapshot,
    });
    // 绑定 `refresh-workflows` bus 事件（前端 PR-3 shared/messaging）
    try {
      if (global.StudioMessaging && typeof global.StudioMessaging.connect === 'function') {
        const bus = global.StudioMessaging.connect({
          types: ['providers-changed', 'workflows-changed', 'comfy-instances-changed'],
          onMessage: msg => {
            if (!msg || typeof msg.type !== 'string') return;
            if (msg.type === 'providers-changed') mod.providersStore.invalidate('providers-changed');
            if (msg.type === 'workflows-changed') mod.workflowsStore.invalidate('workflows-changed');
            if (msg.type === 'comfy-instances-changed') mod.configStore.invalidate('comfy-instances-changed');
          },
        });
        global.__STORES_BUS__ = bus;
      }
    } catch (err) {
      if (global.console) global.console.warn('[stores bootstrap] messaging bus attach skipped:', err);
    }
    return global.stores;
  }).catch(err => {
    // seam 期严格容错：bootstrap 失败时不阻断页面渲染，仅打印警告；
    // 顶层变量 wrapper 内部会回退空数组 / 空对象（canvas.js 逻辑保持不变）。
    if (global.console) global.console.error('[stores bootstrap] failed:', err);
    throw err;
  });

  global.StoresReady = ready;
})(typeof window !== 'undefined' ? window : this);
