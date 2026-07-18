// static/js/shared/api-client/index.js
//
// Seam-period 前端统一 API 客户端入口。零构建零依赖，原生 ES module。
//
// 用法：
//     import {
//       apiClient,
//       ApiClientError,
//       LIST_CANVASES,
//       CANVAS_BY_ID,
//     } from '/static/js/shared/api-client/index.js';
//
//     const data = await apiClient.get(LIST_CANVASES);
//     const canvas = await apiClient.get(CANVAS_BY_ID('abc'));
//
// 详见 `README.md` 与本目录三份实现：`client.js` / `endpoints.js` / `errors.js`。

export { apiClient } from './client.js';
export {
  ApiClientError,
  ErrorCodes,
  errorFromResponse,
  isConflictError,
} from './errors.js';
export * from './endpoints.js';
export { fileApi } from './domains/fileApi.js';
