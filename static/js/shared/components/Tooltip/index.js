// static/js/shared/components/Tooltip/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (候选 A) — Tooltip 组件。
//
// 契约(硬约束):
//   - attach(target, {text, placement?}) -> detach() · 绑 hover / focus / focusout / mouseleave
//   - aria-describedby 关联 tooltip DOM id
//   - text 走 escapeHtml(P0)
//   - 零构建 / 零依赖 / native ES module

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}
const escapeAttr = escapeHtml;

let _idSeq = 0;

/**
 * @param {HTMLElement} target
 * @param {{text:string, placement?:string, document?:Document}} opts
 * @returns {{ detach:()=>void, id:string }}
 */
export function attach(target, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    if (!doc || !target) throw new Error('SharedComponents.Tooltip.attach: 需要 target + document');
    const text = options.text == null ? '' : String(options.text);
    const placement = options.placement || 'top';

    _idSeq += 1;
    const tipId = `sc-tooltip-${_idSeq}-${Math.random().toString(36).slice(2, 8)}`;
    const tip = doc.createElement('div');
    tip.id = tipId;
    tip.className = `sc-tooltip sc-tooltip-${escapeAttr(placement)}`;
    tip.setAttribute('role', 'tooltip');
    tip.setAttribute('data-placement', escapeAttr(placement));
    tip.hidden = true;
    tip.innerHTML = `<span class="sc-tooltip-text">${escapeHtml(text)}</span>`;
    doc.body.appendChild(tip);

    // 保留旧 aria-describedby(累加,不覆盖)
    const prevDescribed = target.getAttribute('aria-describedby') || '';
    const newDescribed = prevDescribed ? `${prevDescribed} ${tipId}` : tipId;
    target.setAttribute('aria-describedby', newDescribed);

    function show() { tip.hidden = false; }
    function hide() { tip.hidden = true; }

    target.addEventListener('mouseenter', show);
    target.addEventListener('mouseleave', hide);
    target.addEventListener('focus', show);
    target.addEventListener('blur', hide);

    let detached = false;
    function detach() {
        if (detached) return;
        detached = true;
        try { target.removeEventListener('mouseenter', show); } catch (_) { /* noop */ }
        try { target.removeEventListener('mouseleave', hide); } catch (_) { /* noop */ }
        try { target.removeEventListener('focus', show); } catch (_) { /* noop */ }
        try { target.removeEventListener('blur', hide); } catch (_) { /* noop */ }
        // Restore aria-describedby to previous value
        if (prevDescribed) {
            target.setAttribute('aria-describedby', prevDescribed);
        } else {
            target.removeAttribute('aria-describedby');
        }
        if (tip.parentNode) {
            try { tip.parentNode.removeChild(tip); } catch (_) { /* noop */ }
        }
    }
    return { detach, id: tipId };
}

export const _internal = Object.freeze({ escapeHtml, escapeAttr });

const Tooltip = { attach, _internal };
export default Tooltip;
