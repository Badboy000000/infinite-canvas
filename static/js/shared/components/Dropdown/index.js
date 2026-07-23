// static/js/shared/components/Dropdown/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (候选 A) — Dropdown(下拉菜单)组件。
//
// 契约(硬约束):
//   - mount(trigger, {items:[{value,label,disabled?}], onSelect(value)}) -> {open,close,unmount}
//   - trigger click 切换 open/close
//   - role="menu" · role="menuitem" · aria-haspopup / aria-expanded 同步
//   - 键盘导航:ArrowDown / ArrowUp / Home / End / Enter / Escape
//   - items[].label 走 escapeHtml(P0)· value 走 escapeAttr
//   - 零构建 / 零依赖 / native ES module

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}
const escapeAttr = escapeHtml;

let _idSeq = 0;

/**
 * @param {HTMLElement} trigger
 * @param {{ items:Array<{value:string,label:string,disabled?:boolean}>,
 *           onSelect:(value:string)=>void,
 *           document?:Document }} opts
 * @returns {{open:()=>void, close:()=>void, unmount:()=>void, menu:HTMLElement}}
 */
export function mount(trigger, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    if (!doc || !trigger) throw new Error('SharedComponents.Dropdown.mount: 需要 trigger + document');
    const items = Array.isArray(options.items) ? options.items : [];

    _idSeq += 1;
    const menuId = `sc-dropdown-${_idSeq}-${Math.random().toString(36).slice(2, 8)}`;

    const menu = doc.createElement('div');
    menu.id = menuId;
    menu.className = 'sc-dropdown-menu';
    menu.setAttribute('role', 'menu');
    menu.hidden = true;

    items.forEach((it, index) => {
        const li = doc.createElement('button');
        li.type = 'button';
        li.className = 'sc-dropdown-item';
        li.setAttribute('role', 'menuitem');
        li.setAttribute('data-value', escapeAttr(it && it.value != null ? it.value : ''));
        li.setAttribute('data-index', String(index));
        if (it && it.disabled) {
            li.setAttribute('aria-disabled', 'true');
            li.disabled = true;
        }
        // Escaped label — P0 XSS guard.
        li.innerHTML = `<span class="sc-dropdown-label">${escapeHtml(it && it.label != null ? it.label : '')}</span>`;
        menu.appendChild(li);
    });

    doc.body.appendChild(menu);
    trigger.setAttribute('aria-haspopup', 'menu');
    trigger.setAttribute('aria-controls', menuId);
    trigger.setAttribute('aria-expanded', 'false');

    let opened = false;
    let focusIndex = -1;

    function _enabledItems() {
        return Array.from(menu.querySelectorAll('.sc-dropdown-item')).filter((el) => !el.disabled);
    }

    function _focusAt(idx) {
        const nodes = _enabledItems();
        if (!nodes.length) return;
        focusIndex = ((idx % nodes.length) + nodes.length) % nodes.length;
        try { nodes[focusIndex].focus(); } catch (_) { /* noop */ }
    }

    function open() {
        if (opened) return;
        opened = true;
        menu.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        focusIndex = 0;
        _focusAt(0);
    }

    function close() {
        if (!opened) return;
        opened = false;
        menu.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
    }

    function onTriggerClick() {
        if (opened) close(); else open();
    }

    function onItemClick(e) {
        const target = e.target.closest && e.target.closest('.sc-dropdown-item');
        if (!target || target.disabled) return;
        const value = target.getAttribute('data-value') || '';
        close();
        if (typeof options.onSelect === 'function') {
            try { options.onSelect(value); } catch (err) {
                if (typeof console !== 'undefined' && console.error) console.error('[Dropdown] onSelect', err);
            }
        }
    }

    function onKeyDown(e) {
        if (!opened) return;
        const nodes = _enabledItems();
        if (!nodes.length) return;
        if (e.key === 'Escape' || e.keyCode === 27) {
            e.preventDefault && e.preventDefault();
            close();
            try { trigger.focus(); } catch (_) { /* noop */ }
        } else if (e.key === 'ArrowDown' || e.keyCode === 40) {
            e.preventDefault && e.preventDefault();
            _focusAt(focusIndex + 1);
        } else if (e.key === 'ArrowUp' || e.keyCode === 38) {
            e.preventDefault && e.preventDefault();
            _focusAt(focusIndex - 1);
        } else if (e.key === 'Home' || e.keyCode === 36) {
            e.preventDefault && e.preventDefault();
            _focusAt(0);
        } else if (e.key === 'End' || e.keyCode === 35) {
            e.preventDefault && e.preventDefault();
            _focusAt(nodes.length - 1);
        } else if (e.key === 'Enter' || e.keyCode === 13) {
            const active = doc.activeElement;
            if (active && active.classList && active.classList.contains('sc-dropdown-item')) {
                e.preventDefault && e.preventDefault();
                active.click();
            }
        }
    }

    trigger.addEventListener('click', onTriggerClick);
    menu.addEventListener('click', onItemClick);
    doc.addEventListener('keydown', onKeyDown, true);

    let unmounted = false;
    function unmount() {
        if (unmounted) return;
        unmounted = true;
        try { trigger.removeEventListener('click', onTriggerClick); } catch (_) { /* noop */ }
        try { menu.removeEventListener('click', onItemClick); } catch (_) { /* noop */ }
        try { doc.removeEventListener('keydown', onKeyDown, true); } catch (_) { /* noop */ }
        trigger.removeAttribute('aria-controls');
        trigger.removeAttribute('aria-expanded');
        if (menu.parentNode) {
            try { menu.parentNode.removeChild(menu); } catch (_) { /* noop */ }
        }
    }

    return { open, close, unmount, menu };
}

export const _internal = Object.freeze({ escapeHtml, escapeAttr });

const Dropdown = { mount, _internal };
export default Dropdown;
