// static/js/shared/api-client/client.js
//
// Seam-period 前端统一 API 客户端。零构建零依赖，原生 ES module。
//
// 硬约束（[[前端兼容合同冻结清单]] §7.8、[[前端组件化治理实施计划与PR清单]] PR-2）：
//   1. 迁移前后 fetch URL / method / body / 关键 header **逐字节等价**。
//   2. 默认 `credentials: 'same-origin'`；同源接受策略保留（[[前端兼容合同冻结清单]] §1.4）。
//   3. 仅在 body 为普通对象（非 FormData / Blob / string / ArrayBuffer / URLSearchParams）
//      时自动加 `Content-Type: application/json` 并 `JSON.stringify` 序列化。multipart
//      上传由调用方直接传 FormData（[[前端兼容合同冻结清单]] §7.8：所有 form-data
//      上传点保留 multipart 语义）。
//   4. 错误统一抛出 `ApiClientError`；`X-Client-Id` 依然可选，legacy 模式后端不强制。
//   5. 中文 detail pass-through（[[前端兼容合同冻结清单]] §12.1）。
//   6. seam 期不引入 axios / ky，不做自动重试（PR-3/4 视需要再补 interceptor）。

import { ApiClientError, errorFromResponse } from './errors.js';

const JSON_CONTENT_TYPE = 'application/json';

/**
 * 判定 body 是否为"应作为 JSON 序列化"的普通对象。
 * FormData / Blob / ArrayBuffer / URLSearchParams / ReadableStream / string 直接透传。
 */
function shouldSerializeAsJson(body) {
  if (body === null || body === undefined) return false;
  if (typeof body === 'string') return false;
  if (typeof FormData !== 'undefined' && body instanceof FormData) return false;
  if (typeof Blob !== 'undefined' && body instanceof Blob) return false;
  if (typeof ArrayBuffer !== 'undefined'
      && (body instanceof ArrayBuffer || ArrayBuffer.isView(body))) return false;
  if (typeof URLSearchParams !== 'undefined' && body instanceof URLSearchParams) return false;
  if (typeof ReadableStream !== 'undefined' && body instanceof ReadableStream) return false;
  return typeof body === 'object';
}

/**
 * 将响应体解析为业务侧期望的数据。
 * 默认按 Content-Type 判定：JSON → 解析对象；其余 → 返回 Response 供调用方自处理。
 * 调用方可显式传 `parseAs: 'json' | 'text' | 'blob' | 'response' | 'none'` 覆盖。
 */
async function parseResponseBody(response, parseAs) {
  if (parseAs === 'response') return response;
  if (parseAs === 'none') return undefined;
  if (parseAs === 'text') return response.text();
  if (parseAs === 'blob') return response.blob();
  if (parseAs === 'json') return response.json();

  // auto：204 / 205 无 body；其他按 Content-Type
  if (response.status === 204 || response.status === 205) return undefined;
  const ct = response.headers.get('Content-Type') || '';
  if (ct.includes('application/json')) return response.json();
  // 未知类型：保底返回 text，避免调用方误消费
  return response.text();
}

/**
 * 单次请求核心。返回解析后的 body；HTTP >= 400 抛 ApiClientError。
 *
 * @param {string} method
 * @param {string} endpoint       相对路径（如 `/api/canvases`），也支持绝对 URL。
 * @param {object} [options]
 * @param {*}      [options.body]        普通对象自动 JSON 化；FormData / Blob 等直传。
 * @param {object} [options.headers]     额外 headers；与自动 Content-Type 合并（用户显式传入优先）。
 * @param {string} [options.query]       查询串（不含 `?`）；或用 endpoint 自带 query。
 * @param {URLSearchParams|object} [options.params] 查询参数对象；与 `query` 二选一。
 * @param {AbortSignal} [options.signal]
 * @param {RequestCredentials} [options.credentials] 默认 `'same-origin'`。
 * @param {'auto'|'json'|'text'|'blob'|'response'|'none'} [options.parseAs] 默认 `'auto'`。
 * @param {RequestCache} [options.cache]
 * @param {RequestMode}  [options.mode]
 * @param {RequestRedirect} [options.redirect]
 * @param {'cors'|'no-cors'|'same-origin'} [options.referrerPolicy]
 * @returns {Promise<*>}
 */
async function request(method, endpoint, options = {}) {
  const upperMethod = (method || 'GET').toUpperCase();
  const {
    body,
    headers: userHeaders,
    query,
    params,
    signal,
    credentials = 'same-origin',
    parseAs = 'auto',
    cache,
    mode,
    redirect,
    referrerPolicy,
  } = options;

  // 组装 URL：query / params 二选一（都不传则原样使用 endpoint）
  let url = endpoint;
  if (params && typeof params === 'object') {
    const usp = params instanceof URLSearchParams
      ? params
      : new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null));
    const qs = usp.toString();
    if (qs) url += (url.includes('?') ? '&' : '?') + qs;
  } else if (typeof query === 'string' && query) {
    url += (url.includes('?') ? '&' : '?') + query.replace(/^\?/, '');
  }

  // 组装 headers：用户显式 Content-Type 优先；否则仅在 JSON body 时自动加
  const headers = {};
  const hasUserContentType = userHeaders && Object.keys(userHeaders).some(
    (k) => k.toLowerCase() === 'content-type'
  );

  let finalBody;
  if (body === undefined || body === null) {
    finalBody = undefined;
  } else if (shouldSerializeAsJson(body)) {
    finalBody = JSON.stringify(body);
    if (!hasUserContentType) headers['Content-Type'] = JSON_CONTENT_TYPE;
  } else {
    finalBody = body; // FormData / Blob / string / URLSearchParams …
  }
  if (userHeaders) Object.assign(headers, userHeaders);

  const init = {
    method: upperMethod,
    credentials,
    headers,
  };
  if (finalBody !== undefined) init.body = finalBody;
  if (signal) init.signal = signal;
  if (cache) init.cache = cache;
  if (mode) init.mode = mode;
  if (redirect) init.redirect = redirect;
  if (referrerPolicy) init.referrerPolicy = referrerPolicy;

  let response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    // 网络错误 / abort：包装为 ApiClientError（isNetworkError=true）
    throw new ApiClientError(err && err.message ? err.message : '网络错误', {
      status: null,
      errorCode: null,
      detail: null,
      requestId: null,
      response: null,
      rawText: null,
      endpoint: url,
      method: upperMethod,
      isNetworkError: true,
      cause: err,
    });
  }

  if (!response.ok) {
    throw await errorFromResponse(response, { endpoint: url, method: upperMethod });
  }

  return parseResponseBody(response, parseAs);
}

/**
 * apiClient —— 方法级 shortcut。
 *
 * 用法：
 *     import { apiClient, LIST_CANVASES } from '/static/js/shared/api-client/index.js';
 *     const data = await apiClient.get(LIST_CANVASES);
 *     await apiClient.put(`/api/canvases/${id}`, { body: {title, ...} });
 */
export const apiClient = Object.freeze({
  request,
  get: (endpoint, options) => request('GET', endpoint, options),
  post: (endpoint, options) => request('POST', endpoint, options),
  put: (endpoint, options) => request('PUT', endpoint, options),
  delete: (endpoint, options) => request('DELETE', endpoint, options),
  patch: (endpoint, options) => request('PATCH', endpoint, options),
});
