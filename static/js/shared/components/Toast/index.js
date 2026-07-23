// static/js/shared/components/Toast/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (候选 A) — Toast(轻量提示)组件。
//
// 契约(硬约束):
//   - success/error/warning/info(msg, opts?) 4 个 API
//   - 自动 dismiss(默认 3000ms · 可 opts.timeout 覆盖 · 0 = 不自动关)
//   - 容器 `role="status"` + `aria-live="polite"`(warning/error 用 assertive)
//   - msg 走 escapeHtml,严禁 HTML 注入(P0)
//   - 零构建 / 零依赖 / native ES module
//
// P0 XSS 抗回归(T334):msg 参数任意用户输入必须 escape。

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}
const escapeAttr = escapeHtml;

const DEFAULT_TIMEOUT = 3000;
const CONTAINER_ID = 'sc-toast-container';

function _ensureContainer(doc) {
    let container = doc.getElementById(CONTAINER_ID);
    if (container) return container;
    container = doc.createElement('div');
    container.id = CONTAINER_ID;
    container.className = 'sc-toast-container';
    doc.body.appendChild(container);
    return container;
}

function _show(kind, msg, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    if (!doc) return null;
    const container = _ensureContainer(doc);
    const toast = doc.createElement('div');
    toast.className = `sc-toast sc-toast-${kind}`;
    // Assertive for error/warning; polite for info/success.
    const isUrgent = kind === 'error' || kind === 'warning';
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', isUrgent ? 'assertive' : 'polite');
    toast.setAttribute('data-kind', escapeAttr(kind));
    // ESCAPED msg only.
    toast.innerHTML = `<span class="sc-toast-msg">${escapeHtml(msg)}</span>`;
    container.appendChild(toast);

    const timeout = options.timeout == null ? DEFAULT_TIMEOUT : Number(options.timeout);
    let timerId = null;
    function dismiss() {
        if (timerId != null) {
            try { clearTimeout(timerId); } catch (_) { /* noop */ }
            timerId = null;
        }
        if (toast.parentNode) {
            try { toast.parentNode.removeChild(toast); } catch (_) { /* noop */ }
        }
    }
    if (timeout > 0) {
        timerId = setTimeout(dismiss, timeout);
    }
    return { root: toast, dismiss };
}

export function success(msg, opts) { return _show('success', msg, opts); }
export function error(msg, opts) { return _show('error', msg, opts); }
export function warning(msg, opts) { return _show('warning', msg, opts); }
export function info(msg, opts) { return _show('info', msg, opts); }

export const _internal = Object.freeze({ escapeHtml, escapeAttr, DEFAULT_TIMEOUT });

const Toast = { success, error, warning, info, _internal };
export default Toast;
