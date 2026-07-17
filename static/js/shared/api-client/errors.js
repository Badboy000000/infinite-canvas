// static/js/shared/api-client/errors.js
//
// Seam-period API 客户端错误类型与解析 helper。零构建零依赖，原生 ES module。
//
// 与后端错误契约对齐（[[技术开发规则与工程实施规范]] §API 与错误契约规则）：
//     {
//       "code": "stable_error_or_success_code",
//       "message": "用户可读信息",
//       "details": {},
//       "request_id": "..."
//     }
//
// seam 期后端旧接口仍返回历史 shape（FastAPI 默认 `{"detail": "..."}` / 422 结构化 errors[]）。
// `parseErrorBody` 兼容：
//   - 新契约 code/message/details/request_id
//   - 旧 FastAPI detail 字符串
//   - 旧 FastAPI 422 数组 detail
//   - 非 JSON 响应体（保留 rawText）
//
// 前端不重写中文 detail（[[前端兼容合同冻结清单]] §12.1）；`ApiClientError.message`
// 保留后端原文，`friendlyMessage()` 只在原文为空时兜底。

/**
 * ApiClientError —— seam 期统一异常。
 *
 * @property {number|null} status         HTTP status code；网络错误为 null。
 * @property {string|null} errorCode      后端错误码（新契约 `code` 字段）；旧接口为 null。
 * @property {*}           detail         后端原始 detail / details 字段；网络错误为 null。
 * @property {string|null} requestId      X-Request-Id header 或 body.request_id；缺省为 null。
 * @property {Response|null} response     原始 fetch Response；网络错误为 null。
 * @property {string|null} rawText        响应体原文（当无法 parse JSON 时保留）。
 * @property {string}       endpoint      请求 URL（相对或绝对，与调用方传入一致）。
 * @property {string}       method        HTTP method 大写。
 * @property {boolean}      isNetworkError 是否属于网络 / abort / 未响应类错误。
 */
export class ApiClientError extends Error {
  constructor(message, {
    status = null,
    errorCode = null,
    detail = null,
    requestId = null,
    response = null,
    rawText = null,
    endpoint = '',
    method = 'GET',
    isNetworkError = false,
    cause = null,
  } = {}) {
    super(message || '');
    this.name = 'ApiClientError';
    this.status = status;
    this.errorCode = errorCode;
    this.detail = detail;
    this.requestId = requestId;
    this.response = response;
    this.rawText = rawText;
    this.endpoint = endpoint;
    this.method = method;
    this.isNetworkError = isNetworkError;
    if (cause) this.cause = cause;
  }

  /**
   * 兜底文案：仅在 `err.message` 为空时使用（[[前端兼容合同冻结清单]] §12.1）。
   */
  friendlyMessage(fallback = '请求失败') {
    if (this.message && String(this.message).trim()) return this.message;
    return fallback;
  }
}

/**
 * 从 Response body（可能是 JSON 也可能是 text）中提取错误信息，构造 ApiClientError。
 *
 * @param {Response} response
 * @param {{endpoint:string, method:string}} ctx
 * @returns {Promise<ApiClientError>}
 */
export async function errorFromResponse(response, ctx) {
  const endpoint = ctx?.endpoint || '';
  const method = ctx?.method || 'GET';
  const status = response.status;
  const requestId = response.headers.get('X-Request-Id') || null;

  let bodyText = null;
  let bodyJson = null;
  try {
    bodyText = await response.text();
  } catch (_) {
    bodyText = null;
  }
  if (bodyText) {
    try {
      bodyJson = JSON.parse(bodyText);
    } catch (_) {
      bodyJson = null;
    }
  }

  let message = '';
  let errorCode = null;
  let detail = null;
  let bodyRequestId = null;

  if (bodyJson && typeof bodyJson === 'object') {
    // 新契约：{code, message, details, request_id}
    if (typeof bodyJson.code === 'string') errorCode = bodyJson.code;
    if (typeof bodyJson.message === 'string') message = bodyJson.message;
    if (bodyJson.details !== undefined) detail = bodyJson.details;
    if (typeof bodyJson.request_id === 'string') bodyRequestId = bodyJson.request_id;

    // 旧 FastAPI shape：`{"detail": "..."}` 或 `{"detail": [{...}, ...]}`
    if (bodyJson.detail !== undefined) {
      if (detail === null) detail = bodyJson.detail;
      if (!message) {
        if (typeof bodyJson.detail === 'string') {
          message = bodyJson.detail;
        } else if (Array.isArray(bodyJson.detail) && bodyJson.detail.length > 0) {
          const first = bodyJson.detail[0];
          if (first && typeof first.msg === 'string') message = first.msg;
        }
      }
    }
  } else if (bodyText) {
    message = bodyText;
  }

  return new ApiClientError(message, {
    status,
    errorCode,
    detail,
    requestId: requestId || bodyRequestId,
    response,
    rawText: bodyText,
    endpoint,
    method,
    isNetworkError: false,
  });
}

/**
 * 判定是否 Canvas 保存冲突（HTTP 409）。
 * 消费方按 [[前端兼容合同冻结清单]] §10 处理 `err.detail.canvas || err.detail?.canvas` 双 shape。
 */
export function isConflictError(err) {
  return err instanceof ApiClientError && err.status === 409;
}

/**
 * 常见 error code 常量（seam 期占位，随后端契约收敛逐步填充）。
 * 与后端 `app/api/errors.py`（PR-BE-12 承接）保持一致。
 */
export const ErrorCodes = Object.freeze({
  VALIDATION_ERROR: 'validation_error',
  UNAUTHORIZED: 'unauthorized',
  FORBIDDEN: 'forbidden',
  NOT_FOUND: 'not_found',
  CONFLICT: 'conflict',
  INTERNAL_ERROR: 'internal_error',
});
