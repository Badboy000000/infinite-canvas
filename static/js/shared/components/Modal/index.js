// static/js/shared/components/Modal/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (共享组件套件 · 候选 A) — 通用 Modal 组件。
//
// 契约(硬约束):
//   - open(opts) -> { close, root } · 幂等打开(重复 open 关旧起新)
//   - close() -> void · 幂等关闭
//   - `role="dialog"` + `aria-modal="true"` + `aria-labelledby` 关联标题
//   - ESC 键关闭(自动清 keyboard listener)
//   - 焦点陷阱:tab / shift+tab 在 root 内循环;打开时 auto-focus 第一个可聚焦元素;
//     关闭时把焦点还给触发元素(opts.returnFocus)
//   - innerHTML 只走 `content` 已由调用方转义(或调用方明确 trusted) —— 本组件
//     不对 content 二次 escape,与 PromptTemplateDrawer / MediaEditor pattern 一致;
//     titleText / labelText 走 escapeHtml
//
// 硬约束:零构建 / 零依赖 / native ES module。
//
// P0 XSS 抗回归(T334):titleText / labelText 输入必须 escape。
// 消费方注入 content 时须自行保证 HTML 安全(与既有 dialog pattern 对齐)。

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}
const escapeAttr = escapeHtml;

const FOCUSABLE = [
    'a[href]', 'area[href]', 'button:not([disabled])', 'input:not([disabled])',
    'select:not([disabled])', 'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])', '[contenteditable="true"]',
].join(',');

let _activeInstance = null;

/**
 * Open a modal.
 *
 * @param {object} opts
 * @param {string} [opts.title]        Text-only title (escaped into <h2>)
 * @param {string} [opts.content]      Trusted HTML body (调用方职责)
 * @param {string} [opts.className]    额外 class 追加到 root
 * @param {(root:HTMLElement)=>void} [opts.onOpen]
 * @param {(reason:string)=>void}    [opts.onClose]
 * @param {HTMLElement} [opts.returnFocus] 关闭时把焦点还给此元素
 * @param {Document}   [opts.document]   注入(测试用);默认 globalThis.document
 * @returns {{close:(reason?:string)=>void, root:HTMLElement}}
 */
export function open(opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    if (!doc) throw new Error('SharedComponents.Modal.open: 需要 document(浏览器或注入)');

    // 幂等:若已有 active,先关(避免重叠)
    if (_activeInstance) {
        try { _activeInstance.close('reopen'); } catch (_) { /* noop */ }
    }

    const titleText = options.title == null ? '' : String(options.title);
    const contentHtml = options.content == null ? '' : String(options.content);
    const extraClass = options.className ? String(options.className) : '';
    const titleId = `sc-modal-title-${Math.random().toString(36).slice(2, 10)}`;

    const overlay = doc.createElement('div');
    overlay.className = `sc-modal-overlay ${extraClass}`.trim();
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    if (titleText) overlay.setAttribute('aria-labelledby', titleId);
    overlay.innerHTML = [
        '<div class="sc-modal-panel">',
        titleText ? `<h2 class="sc-modal-title" id="${escapeAttr(titleId)}">${escapeHtml(titleText)}</h2>` : '',
        `<div class="sc-modal-body">${contentHtml}</div>`,
        '</div>',
    ].join('');
    doc.body.appendChild(overlay);

    const prevActiveElement = doc.activeElement || null;

    // Focus first focusable inside
    const focusables = () => Array.from(overlay.querySelectorAll(FOCUSABLE));
    const initial = focusables()[0];
    if (initial && typeof initial.focus === 'function') {
        try { initial.focus(); } catch (_) { /* noop */ }
    }

    function onKeyDown(e) {
        if (!e) return;
        if (e.key === 'Escape' || e.keyCode === 27) {
            e.preventDefault && e.preventDefault();
            close('escape');
            return;
        }
        if (e.key === 'Tab' || e.keyCode === 9) {
            const nodes = focusables();
            if (nodes.length === 0) {
                e.preventDefault && e.preventDefault();
                return;
            }
            const first = nodes[0];
            const last = nodes[nodes.length - 1];
            const current = doc.activeElement;
            if (e.shiftKey && current === first) {
                e.preventDefault && e.preventDefault();
                try { last.focus(); } catch (_) { /* noop */ }
            } else if (!e.shiftKey && current === last) {
                e.preventDefault && e.preventDefault();
                try { first.focus(); } catch (_) { /* noop */ }
            }
        }
    }

    doc.addEventListener('keydown', onKeyDown, true);

    let closed = false;
    function close(reason) {
        if (closed) return;
        closed = true;
        try { doc.removeEventListener('keydown', onKeyDown, true); } catch (_) { /* noop */ }
        if (overlay.parentNode) {
            try { overlay.parentNode.removeChild(overlay); } catch (_) { /* noop */ }
        }
        if (_activeInstance === instance) _activeInstance = null;
        const rf = options.returnFocus || prevActiveElement;
        if (rf && typeof rf.focus === 'function') {
            try { rf.focus(); } catch (_) { /* noop */ }
        }
        if (typeof options.onClose === 'function') {
            try { options.onClose(reason || 'close'); } catch (_) { /* noop */ }
        }
    }

    const instance = { root: overlay, close };
    _activeInstance = instance;

    if (typeof options.onOpen === 'function') {
        try { options.onOpen(overlay); } catch (_) { /* noop */ }
    }
    return instance;
}

export function close(reason) {
    if (_activeInstance) _activeInstance.close(reason || 'close');
}

export function isOpen() { return !!_activeInstance; }

export const _internal = Object.freeze({ escapeHtml, escapeAttr });

const Modal = { open, close, isOpen, _internal };
export default Modal;
