// static/js/shared/media/legacyUrlResolver.js
//
// Seam-period 前端 legacy URL 解析器（[[前端组件化治理实施计划与PR清单]] PR-4）。
//
// 目标：把散布在 canvas.js / smart-canvas.js 中的 `/assets/*` / `/output/*`
// / `/api/view` / `/api/media-preview` / `/api/download-output` 判定 / 解析
// 逻辑收敛到单一模块。fileApi.view(legacyUrl) 直接消费本 resolver。
//
// 硬约束：
//   1. 只做 URL 解析，禁改任何 URL 语义（[[前端兼容合同冻结清单]] §7.8、§13）。
//   2. 输入是"任意 URL 字符串"（可能是 data:/blob:/http(s):/相对路径/预览包裹）。
//   3. 输出是 `{ kind, originalUrl, resolvedUrl }` 描述；resolvedUrl 保证浏览器
//      可 `<img src>` 或 `<video src>` 直接消费。
//   4. 保持中文注释与既有约定一致，不新增第三方依赖。

/**
 * @typedef {Object} LegacyUrlDescriptor
 * @property {'data'|'blob'|'assets'|'output'|'api-view'|'media-preview'|'download-output'|'http'|'other'} kind
 *   URL 分类。`assets` / `output` 是本地静态挂载；`api-view` 是后端 ComfyUI 代理；
 *   `media-preview` / `download-output` 是后端媒体代理；`http` 是原始远端；
 *   `data` / `blob` 是浏览器内嵌资源；`other` 是无法归类。
 * @property {string} originalUrl    调用方传入的原始字符串（未经修改）。
 * @property {string} resolvedUrl    去掉预览包裹（`/api/media-preview?url=...`）后的原始资源 URL。
 *                                   `<img src>` 消费时若希望走预览走 `previewUrl(...)` 单独产出。
 * @property {string} [previewParam] 若 originalUrl 本身是 `/api/media-preview`，返回其 `url` 参数。
 */

/** 去掉 `/api/media-preview?url=<real>` 外层，返回真实资源 URL（若无包裹则原样返回）。 */
export function unwrapMediaPreviewUrl(url) {
  const raw = String(url || '');
  if (!raw) return '';
  try {
    const parsed = new URL(raw, (typeof window !== 'undefined' && window.location) ? window.location.origin : 'http://localhost/');
    if (parsed.pathname === '/api/media-preview') {
      const inner = parsed.searchParams.get('url') || '';
      return inner || raw;
    }
    if (parsed.pathname === '/api/download-output') {
      const inner = parsed.searchParams.get('url') || '';
      return inner || raw;
    }
  } catch (_) {}
  return raw;
}

/** 判定 URL 是否属于本地静态挂载或后端媒体代理。 */
export function isLocalMediaUrl(url) {
  const raw = String(url || '');
  if (!raw) return false;
  if (raw.startsWith('/assets/') || raw.startsWith('/output/')) return true;
  if (raw.startsWith('/api/view')) return true;
  if (raw.startsWith('/api/media-preview')) return true;
  if (raw.startsWith('/api/download-output')) return true;
  return false;
}

/** 解析 legacy URL；不改变任何语义，仅分类 + 剥离预览包裹。 */
export function resolveLegacyUrl(url) {
  const raw = String(url || '');
  if (!raw) {
    return { kind: 'other', originalUrl: '', resolvedUrl: '' };
  }
  if (raw.startsWith('data:')) return { kind: 'data', originalUrl: raw, resolvedUrl: raw };
  if (raw.startsWith('blob:')) return { kind: 'blob', originalUrl: raw, resolvedUrl: raw };
  if (raw.startsWith('/assets/')) return { kind: 'assets', originalUrl: raw, resolvedUrl: raw };
  if (raw.startsWith('/output/')) return { kind: 'output', originalUrl: raw, resolvedUrl: raw };
  if (raw.startsWith('/api/view')) return { kind: 'api-view', originalUrl: raw, resolvedUrl: raw };
  if (raw.startsWith('/api/media-preview')) {
    const inner = unwrapMediaPreviewUrl(raw);
    return { kind: 'media-preview', originalUrl: raw, resolvedUrl: inner, previewParam: inner };
  }
  if (raw.startsWith('/api/download-output')) {
    const inner = unwrapMediaPreviewUrl(raw);
    return { kind: 'download-output', originalUrl: raw, resolvedUrl: inner, previewParam: inner };
  }
  if (/^https?:\/\//i.test(raw)) return { kind: 'http', originalUrl: raw, resolvedUrl: raw };
  return { kind: 'other', originalUrl: raw, resolvedUrl: raw };
}

/**
 * 生成本地媒体的宽度预览 URL（`/api/media-preview?w=...&url=...`）。
 * 与 canvas.js `canvasMediaPreviewUrl` 语义等价（[[前端兼容合同冻结清单]] §7.1）。
 */
export function buildMediaPreviewUrl(url, size = 512) {
  const desc = resolveLegacyUrl(url);
  if (!desc.originalUrl) return '';
  if (desc.kind === 'data' || desc.kind === 'blob') return desc.originalUrl;
  const real = desc.resolvedUrl || desc.originalUrl;
  const width = Math.max(64, Math.min(2048, Math.round(Number(size) || 512)));
  return `/api/media-preview?w=${width}&url=${encodeURIComponent(real)}`;
}

/**
 * 生成 `/api/download-output?url=...&name=...` 下载 URL（inline=1 时走内联预览）。
 * 与 canvas.js `canvasProxiedMediaUrl` 语义等价（[[前端兼容合同冻结清单]] §7.1）。
 */
export function buildDownloadOutputUrl(url, name = '', { inline = false } = {}) {
  const desc = resolveLegacyUrl(url);
  if (!desc.originalUrl) return '';
  const real = desc.resolvedUrl || desc.originalUrl;
  const params = new URLSearchParams();
  if (inline) params.set('inline', '1');
  params.set('url', real);
  if (name) params.set('name', name);
  return `/api/download-output?${params.toString()}`;
}
