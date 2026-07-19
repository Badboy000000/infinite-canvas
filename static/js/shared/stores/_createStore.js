// static/js/shared/stores/_createStore.js
//
// 前端 PR-5：`shared/stores` 六件套通用发布订阅工厂（[[前端组件化治理实施计划与PR清单]] PR-5）。
//
// 硬约束：
//   1. 零依赖零构建：seam 期不引入 Pinia / nanostores / RxJS。
//   2. 100 行以内的纯发布订阅 helper。
//   3. `revision` 单调递增（每次 invalidate / setState 触发一次）。
//   4. `subscribe(handler)` 返回 unsubscribe 函数；`invalidate(reason)` 幂等；`refetch()` 幂等（同一 flight 复用 Promise）。
//   5. `state` 是 store 内部的**只读投影**（页面顶层变量 wrapper 化后指向该字段）。
//   6. 不持久化服务端权威数据到 localStorage；localStorage 仅承担 UI 偏好与 legacy 兼容。
//
// 用法：
//   const store = createStore({
//     name: 'providers',
//     initialState: { providers: [] },
//     fetcher: async () => apiClient.get(LIST_PROVIDERS).then(r => ({ providers: r.providers || [] })),
//   });
//   store.subscribe((state, revision, reason) => { ... });
//   await store.refetch();
//   store.invalidate('providers-changed');

/**
 * @template TState
 * @typedef {Object} Store
 * @property {TState}       state
 * @property {number}       revision
 * @property {(handler:(state:TState, revision:number, reason:string)=>void) => () => void} subscribe
 * @property {(reason?:string) => Promise<TState>} refetch
 * @property {(reason?:string) => void} invalidate
 * @property {(patch:Partial<TState>, reason?:string) => TState} setState
 * @property {string}       name
 */

/**
 * @template TState
 * @param {{ name?:string, initialState:TState, fetcher?:(current:TState)=>Promise<Partial<TState>|TState> }} config
 * @returns {Store<TState>}
 */
export function createStore(config = {}) {
  const name = String(config.name || 'anonymous');
  if (!config.initialState || typeof config.initialState !== 'object') {
    throw new TypeError(`[stores/${name}] initialState must be a non-null object`);
  }
  const state = { ...config.initialState };
  let revision = 0;
  let inflight = null;
  const handlers = new Set();
  const fetcher = typeof config.fetcher === 'function' ? config.fetcher : null;

  function notify(reason) {
    handlers.forEach(handler => {
      try { handler(state, revision, reason); }
      catch (err) { if (globalThis.console) console.error(`[stores/${name}] handler failed:`, err); }
    });
  }

  function setState(patch, reason = 'setState') {
    if (patch && typeof patch === 'object') {
      Object.keys(patch).forEach(key => { state[key] = patch[key]; });
    }
    revision += 1;
    notify(reason);
    return state;
  }

  function invalidate(reason = 'invalidate') {
    // invalidate 只 bump revision + 通知；不自动 refetch（由订阅方按需触发）
    revision += 1;
    notify(reason);
  }

  function refetch(reason = 'refetch') {
    if (!fetcher) return Promise.resolve(state);
    // 幂等：同一 flight 内多次 refetch() 共享同一 Promise
    if (inflight) return inflight;
    inflight = Promise.resolve()
      .then(() => fetcher(state))
      .then(patch => {
        if (patch && typeof patch === 'object' && patch !== state) {
          Object.keys(patch).forEach(key => { state[key] = patch[key]; });
        }
        revision += 1;
        notify(reason);
        return state;
      })
      .finally(() => { inflight = null; });
    return inflight;
  }

  function subscribe(handler) {
    if (typeof handler !== 'function') throw new TypeError(`[stores/${name}] subscribe(handler): handler must be a function`);
    handlers.add(handler);
    return function unsubscribe() { handlers.delete(handler); };
  }

  return Object.freeze({
    name,
    state,
    get revision() { return revision; },
    subscribe,
    refetch,
    invalidate,
    setState,
  });
}
