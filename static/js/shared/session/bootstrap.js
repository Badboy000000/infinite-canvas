// static/js/shared/session/bootstrap.js
//
// Wave 3-N.6 Batch 3 主线 B · 前端 PR-9 · session bootstrap.
//
// 非模块脚本(`<script src>`),通过动态 ESM `import()` 装配以下模块并挂到:
//   window.SessionStore       = sessionStore(六件套模板 store · state + subscribe + refetch)
//   window.FrontRequestContext = FrontRequestContext class
//   window.Can                = <Can> 组件({ mount, unmount, autoMount })
//   window.EnhancedApiClient  = installInterceptors(sessionStore) 结果(可选消费)
//   window.SessionStoreReady  = Promise<{ sessionStore, FrontRequestContext, Can, enhancedApiClient }>
//
// 幂等:`window.__sessionBootstrapped` 防止重复 include。
//
// **自动 sessionStore.refresh()** 一次(fire-and-forget):
//   - 成功 → 填 FrontRequestContext 字段
//   - 404 / 网络失败 / 5xx → 全 true 降级(sessionStore 内部处理)
//
// 引入(5 处高风险 HTML):
//   <script src="/static/js/shared/session/bootstrap.js?v=..."></script>
//
// 使用示例(canvas.js / api-settings.js):
//   window.SessionStoreReady.then(({ sessionStore, Can }) => {
//     Can.autoMount(document.body, sessionStore);
//   });

(function installSessionBootstrap(global) {
  'use strict';

  if (typeof global === 'undefined') return;
  if (global.__sessionBootstrapped) return;
  global.__sessionBootstrapped = true;

  const SESSION_STORE_URL = '/static/js/shared/stores/sessionStore.js';
  const CONTEXT_URL = '/static/js/shared/api-client/context.js';
  const INTERCEPTORS_URL = '/static/js/shared/api-client/interceptors.js';
  const CAN_URL = '/static/js/shared/components/Can/index.js';

  const ready = Promise.all([
    import(SESSION_STORE_URL),
    import(CONTEXT_URL),
    import(INTERCEPTORS_URL),
    import(CAN_URL),
  ]).then(([storeMod, ctxMod, intMod, canMod]) => {
    const sessionStore = storeMod.sessionStore;
    const FrontRequestContext = ctxMod.FrontRequestContext || ctxMod.default;
    const Can = canMod.default || canMod;
    const enhancedApiClient = intMod.installInterceptors(sessionStore);

    global.SessionStore = sessionStore;
    global.FrontRequestContext = FrontRequestContext;
    global.Can = Can;
    global.EnhancedApiClient = enhancedApiClient;

    // fire-and-forget refresh —— 网络失败 / 404 / 5xx 均降级到全 true(sessionStore 处理)
    Promise.resolve(sessionStore.refetch('bootstrap')).catch((err) => {
      if (global.console && global.console.warn) {
        global.console.warn('[session bootstrap] initial refresh degraded:', err);
      }
    });

    return { sessionStore, FrontRequestContext, Can, enhancedApiClient };
  }).catch((err) => {
    if (global.console && global.console.error) {
      global.console.error('[session bootstrap] failed:', err);
    }
    throw err;
  });

  global.SessionStoreReady = ready;
})(typeof window !== 'undefined' ? window : this);
