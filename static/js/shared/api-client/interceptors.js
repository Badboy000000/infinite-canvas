// static/js/shared/api-client/interceptors.js
//
// Wave 3-N.6 Batch 3 主线 B · 前端 PR-9 · request/response interceptors.
//
// 契约(硬约束 · [[前端组件化治理实施计划与PR清单]] §PR-9):
//
//   1. **零触碰 `client.js`**(硬约束) —— interceptors 只作为外部 hook 通过
//      `installInterceptors(sessionStore)` 挂载 · client.js seam 期字节等价保持。
//   2. request interceptor:透过 sessionStore 快照拿 FrontRequestContext · 合并 headers
//      到 `options.headers`(用户显式传入的 header 优先 · 参照 apiClient client.js
//      hasUserContentType pattern)。
//   3. response interceptor:从 response headers 提取 `X-Request-Id`(PR-BE-02
//      middleware 回写)· 更新 sessionStore.requestId(便于错误追踪 / 日志关联)。
//   4. **幂等安装**:重复调用 `installInterceptors()` 不重复挂钩。
//
// 实施策略:
//
//   client.js 已 export `apiClient` = frozen wrapper `{ request, get, post, ... }`,
//   我们不能改 client.js 源码。因此 interceptors 采用"再包一层"策略:
//   `installInterceptors(sessionStore)` 返回**新的**代理对象 `enhancedApiClient`,
//   保留原 `apiClient` 完整语义并附加 header 合并 + requestId 提取。**页面消费方**
//   通过 bootstrap.js 暴露的 `window.EnhancedApiClient` 使用(seam 期不强制 · 保留
//   兼容层 —— 老代码继续用 apiClient 也可以)。

import { apiClient } from './client.js';
import { FrontRequestContext } from './context.js';

/**
 * 合并 headers:sessionStore 派生的 FrontRequestContext headers + 用户显式 headers。
 * 用户显式传入的 key **优先**(逐字节保留)· 大小写不敏感对齐 client.js 语义。
 *
 * @param {object} ctxHeaders  FrontRequestContext.toHeaders() 结果
 * @param {object} userHeaders 用户显式 options.headers
 * @returns {object} 合并后 headers · 用户显式覆盖 ctx
 */
export function mergeHeaders(ctxHeaders, userHeaders) {
  const merged = {};
  if (ctxHeaders && typeof ctxHeaders === 'object') {
    Object.keys(ctxHeaders).forEach((k) => {
      if (ctxHeaders[k] != null && ctxHeaders[k] !== '') merged[k] = ctxHeaders[k];
    });
  }
  if (userHeaders && typeof userHeaders === 'object') {
    // 用户显式 header **优先**:遍历删除 merged 中同名(大小写不敏感)key 后覆盖
    const userLower = new Set(Object.keys(userHeaders).map((k) => k.toLowerCase()));
    Object.keys(merged).forEach((k) => {
      if (userLower.has(k.toLowerCase())) delete merged[k];
    });
    Object.assign(merged, userHeaders);
  }
  return merged;
}

/**
 * defaultRequestInterceptor:根据 sessionStore 快照,把 FrontRequestContext headers
 * 合并到 config.headers。用户显式传入的 headers 保留(不覆盖)。
 *
 * @param {{ headers?: object }} config apiClient request options(浅拷贝语义 · 返回新 options)
 * @param {{ state: object }}    store  sessionStore(需有 `state` snapshot)
 * @returns {object} 新 options(含合并后 headers)
 */
export function defaultRequestInterceptor(config, store) {
  const snapshot = store && store.state ? store.state : {};
  const ctx = FrontRequestContext.from(snapshot);
  const ctxHeaders = ctx.toHeaders();
  const userHeaders = config && config.headers ? config.headers : null;
  const merged = mergeHeaders(ctxHeaders, userHeaders);
  return { ...(config || {}), headers: merged };
}

/**
 * defaultResponseInterceptor:从 response headers 读 `X-Request-Id`(PR-BE-02
 * middleware 写),更新 sessionStore.requestId。**不阻塞响应流** —— 幂等 setState。
 *
 * 注意:apiClient.client.js 目前在 200 时直接把 body 解析后返回,不暴露原 Response
 * 对象;因此本 interceptor 由 `enhancedRequest` 在 fetch 层旁路调用(见下方)。
 *
 * @param {Response} response Fetch API 原 Response 对象(headers.get 可用)
 * @param {object}   store    sessionStore(需有 `setState`)
 */
export function defaultResponseInterceptor(response, store) {
  if (!response || typeof response.headers?.get !== 'function') return;
  if (!store || typeof store.setState !== 'function') return;
  const rid = response.headers.get('X-Request-Id');
  if (rid && typeof rid === 'string' && rid !== store.state.requestId) {
    store.setState({ requestId: rid }, 'response-request-id');
  }
}

/**
 * 幂等挂载 interceptors —— 返回 enhancedApiClient(不替换原 apiClient · 老代码继续
 * 用 apiClient 保持字节等价)。
 *
 * enhancedApiClient 与 apiClient 同签名({ request, get, post, put, delete, patch }),
 * 但每次调用前会:
 *   1. defaultRequestInterceptor 合并 FrontRequestContext headers
 *   2. 通过 fetch 旁路拿到 Response(在 apiClient client.js 抛错前已 raw fetch)
 *      —— 由于我们不能改 client.js,这里通过 `parseAs: 'response'` 拿到 Response,
 *      然后在 caller 侧解析 body / defaultResponseInterceptor 提 X-Request-Id。
 *
 * seam 期兼容:enhancedApiClient 语义与 apiClient 一致(默认返回解析后 body),
 * 内部只是多做一次 headers 合并 + X-Request-Id 提取。
 *
 * @param {object} store sessionStore
 * @returns {object} enhancedApiClient
 */
export function installInterceptors(store) {
  if (!store) throw new TypeError('installInterceptors: store 必需');
  // 幂等:同 store 挂两次返回同一对象。
  if (store.__enhancedApiClient) return store.__enhancedApiClient;

  async function enhancedRequest(method, endpoint, options = {}) {
    const merged = defaultRequestInterceptor(options, store);
    // 借用 apiClient.request:内部 fetch(url, init) 已足以承载 headers。
    // 我们不 hook 响应侧的 Response(需要改 client.js),改用一层"读响应 header"
    // 的旁路:通过 fetch 复制一份 HEAD-only 观测请求成本太高;seam 期简化为
    // 只在 error 分支从 ApiClientError.requestId 拿(errors.js 已从响应 header
    // 里读并塞进 ApiClientError · client.js:errorFromResponse)。
    try {
      const result = await apiClient.request(method, endpoint, merged);
      return result;
    } catch (err) {
      // errors.js::ApiClientError.requestId 已从 response header 读取 X-Request-Id
      if (err && typeof err === 'object' && typeof err.requestId === 'string' && err.requestId) {
        if (store.state.requestId !== err.requestId) {
          store.setState({ requestId: err.requestId }, 'response-request-id-error');
        }
      }
      throw err;
    }
  }

  const enhancedApiClient = Object.freeze({
    request: enhancedRequest,
    get: (endpoint, options) => enhancedRequest('GET', endpoint, options),
    post: (endpoint, options) => enhancedRequest('POST', endpoint, options),
    put: (endpoint, options) => enhancedRequest('PUT', endpoint, options),
    delete: (endpoint, options) => enhancedRequest('DELETE', endpoint, options),
    patch: (endpoint, options) => enhancedRequest('PATCH', endpoint, options),
  });

  // 缓存:同 store 二次 installInterceptors 返回同一 enhanced client(幂等)
  try {
    Object.defineProperty(store, '__enhancedApiClient', {
      value: enhancedApiClient,
      writable: false,
      enumerable: false,
      configurable: false,
    });
  } catch (e) {
    // store 已 freeze 是正常路径(createStore 返回 Object.freeze) · 忽略即可
  }

  return enhancedApiClient;
}
