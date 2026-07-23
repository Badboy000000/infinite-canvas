// static/js/shared/components/Panel/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (候选 A) — 可折叠面板组件。
//
// 契约(硬约束):
//   - mount(container, {title, content, collapsed?, onToggle?}) -> {toggle, setCollapsed, unmount}
//   - title 走 escapeHtml(P0)· content 由调用方保证 trusted HTML
//   - aria-expanded 与折叠状态同步 · header button role="button" · aria-controls 关联 content id
//   - 零构建 / 零依赖 / native ES module

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}
const escapeAttr = escapeHtml;

let _idSeq = 0;

/**
 * @param {HTMLElement} container   Panel 挂载点
 * @param {{ title:string, content:string, collapsed?:boolean,
 *           onToggle?:(collapsed:boolean)=>void, document?:Document }} opts
 */
export function mount(container, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) throw new Error('SharedComponents.Panel.mount: 需要 container + document');
    const title = options.title == null ? '' : String(options.title);
    const contentHtml = options.content == null ? '' : String(options.content);
    let collapsed = !!options.collapsed;

    _idSeq += 1;
    const bodyId = `sc-panel-body-${_idSeq}-${Math.random().toString(36).slice(2, 8)}`;

    const root = doc.createElement('div');
    root.className = 'sc-panel';
    root.innerHTML = [
        `<button type="button" class="sc-panel-header" aria-expanded="${collapsed ? 'false' : 'true'}" aria-controls="${escapeAttr(bodyId)}">`,
        `<span class="sc-panel-title">${escapeHtml(title)}</span>`,
        `<span class="sc-panel-chevron" aria-hidden="true">${collapsed ? '▸' : '▾'}</span>`,
        `</button>`,
        `<div class="sc-panel-body" id="${escapeAttr(bodyId)}"${collapsed ? ' hidden' : ''}>${contentHtml}</div>`,
    ].join('');
    container.appendChild(root);

    const header = root.querySelector('.sc-panel-header');
    const body = root.querySelector('.sc-panel-body');
    const chevron = root.querySelector('.sc-panel-chevron');

    function _apply() {
        header.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        if (collapsed) {
            body.setAttribute('hidden', '');
        } else {
            body.removeAttribute('hidden');
        }
        if (chevron) chevron.textContent = collapsed ? '▸' : '▾';
    }

    function toggle() {
        collapsed = !collapsed;
        _apply();
        if (typeof options.onToggle === 'function') {
            try { options.onToggle(collapsed); } catch (_) { /* noop */ }
        }
    }

    function setCollapsed(v) {
        const next = !!v;
        if (next === collapsed) return;
        collapsed = next;
        _apply();
        if (typeof options.onToggle === 'function') {
            try { options.onToggle(collapsed); } catch (_) { /* noop */ }
        }
    }

    header.addEventListener('click', toggle);

    let unmounted = false;
    function unmount() {
        if (unmounted) return;
        unmounted = true;
        try { header.removeEventListener('click', toggle); } catch (_) { /* noop */ }
        if (root.parentNode) {
            try { root.parentNode.removeChild(root); } catch (_) { /* noop */ }
        }
    }

    return { toggle, setCollapsed, unmount, root, isCollapsed() { return collapsed; } };
}

export const _internal = Object.freeze({ escapeHtml, escapeAttr });

const Panel = { mount, _internal };
export default Panel;
