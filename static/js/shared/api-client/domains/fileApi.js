// static/js/shared/api-client/domains/fileApi.js
//
// Seam-period 前端文件 / 媒体访问收敛（[[前端组件化治理实施计划与PR清单]] PR-4）。
//
// 硬约束：
//   1. 迁移前后 fetch URL / method / body / 关键 header 逐字节等价（[[前端兼容合同冻结清单]] §7.8）。
//   2. `view` / `mediaPreview` / `downloadOutput` 是纯 URL 构造器（后端 GET 直接 `<img src>` 用）。
//      `fileApi.view(legacyUrl)` 消费 `legacyUrlResolver`，行为等价 canvasOriginalMediaUrl。
//   3. `upload` / `aiUpload` 走 apiClient.post，body 是 FormData（multipart 透传）。
//   4. 中文错误 detail pass-through；ApiClientError 由 apiClient 统一抛出。

import { apiClient } from '../client.js';
import {
  UPLOAD,
  AI_UPLOAD,
  API_VIEW,
  MEDIA_PREVIEW,
  DOWNLOAD_OUTPUT,
} from '../endpoints.js';
import {
  resolveLegacyUrl,
  unwrapMediaPreviewUrl,
  buildMediaPreviewUrl,
  buildDownloadOutputUrl,
} from '../../media/legacyUrlResolver.js';

/**
 * POST /api/upload —— multipart 通用上传（ComfyUI 输入队列使用）。
 * compat-contract §7.1 `canvas.js:10629`、§7.2 `smart-canvas.js:14954`。
 *
 * @param {FormData} form
 * @param {object} [options]
 * @param {AbortSignal} [options.signal]
 * @param {object} [options.headers]
 * @returns {Promise<any>}
 */
export function upload(form, options = {}) {
  return apiClient.post(UPLOAD, { body: form, ...options });
}

/**
 * POST /api/ai/upload —— AI 上传（返回本地资源 URL）。
 * compat-contract §7.1 `canvas.js:2005` 系列、§7.2 `smart-canvas.js:396` 系列。
 *
 * @param {FormData} form
 * @param {object} [options]
 * @returns {Promise<any>}
 */
export function aiUpload(form, options = {}) {
  return apiClient.post(AI_UPLOAD, { body: form, ...options });
}

/**
 * `fileApi.view(legacyUrl)` —— 统一解析 legacy URL。
 *
 * 语义等价 canvas.js `canvasOriginalMediaUrl`：
 *   - `/api/media-preview?url=<real>` → `<real>`
 *   - 其他 URL 原样返回
 *
 * @param {string} url
 * @returns {string}
 */
export function view(url) {
  return unwrapMediaPreviewUrl(url);
}

/** 直接返回 legacyUrlResolver 的完整描述（供 MediaEditor / 迁移代码判定分类）。 */
export function describe(url) {
  return resolveLegacyUrl(url);
}

/**
 * `fileApi.mediaPreview(url, size)` —— 生成宽度约束的预览 URL。
 * 语义等价 canvas.js `canvasMediaPreviewUrl`（[[前端兼容合同冻结清单]] §7.1）。
 */
export function mediaPreview(url, size = 512) {
  return buildMediaPreviewUrl(url, size);
}

/**
 * `fileApi.downloadOutput(url, name, {inline})` —— 生成 `/api/download-output` 下载 URL。
 */
export function downloadOutput(url, name = '', options = {}) {
  return buildDownloadOutputUrl(url, name, options);
}

/** 构造 `/api/view?...` 代理 URL（ComfyUI 输出转发）。 */
export function apiView(params) {
  return API_VIEW(params);
}

/** 便于消费方按 seam 期常规导入 endpoint 常量。 */
export const endpoints = Object.freeze({
  UPLOAD,
  AI_UPLOAD,
  MEDIA_PREVIEW,
  DOWNLOAD_OUTPUT,
});

/**
 * `fileApi` —— 统一命名空间导出（[[前端组件化治理实施计划与PR清单]] PR-4）。
 */
export const fileApi = Object.freeze({
  upload,
  aiUpload,
  view,
  describe,
  mediaPreview,
  downloadOutput,
  apiView,
  endpoints,
});
