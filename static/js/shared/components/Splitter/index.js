// static/js/shared/components/Splitter/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 (候选 A) — 双面板可拖拽分隔条组件。
//
// 契约(硬约束):
//   - mount(container, {orientation:'horizontal'|'vertical', storageKey?, initial?, min?, max?, onResize?})
//     -> {setSize(px), getSize()->px, unmount()}
//   - orientation:'horizontal' = 上下分割(handle 水平);'vertical' = 左右分割(handle 竖直)
//   - storageKey 非空时 · 位置持久化到 localStorage(key=`sc-splitter:${storageKey}`)· 数值 px 存 string
//   - 拖动 pointer 事件(pointerdown / pointermove / pointerup)· 支持 touch / mouse / pen
//   - role="separator" · aria-orientation / aria-valuemin / aria-valuemax / aria-valuenow / tabindex="0"
//   - 键盘 ArrowLeft/ArrowRight/ArrowUp/ArrowDown 微调
//   - 零构建 / 零依赖 / native ES module

const STORAGE_PREFIX = 'sc-splitter:';

function escapeAttrLocal(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}

/**
 * @param {HTMLElement} container   Must contain at least 2 direct child panels
 * @param {{ orientation?:'horizontal'|'vertical', storageKey?:string, initial?:number,
 *           min?:number, max?:number, onResize?:(size:number)=>void, document?:Document,
 *           storage?:Storage }} opts
 */
export function mount(container, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    if (!doc || !container) throw new Error('SharedComponents.Splitter.mount: 需要 container + document');
    const orientation = options.orientation === 'vertical' ? 'vertical' : 'horizontal';
    const isVertical = orientation === 'vertical';
    const min = Number.isFinite(options.min) ? Number(options.min) : 40;
    const max = Number.isFinite(options.max) ? Number(options.max) : 4096;
    const onResize = typeof options.onResize === 'function' ? options.onResize : null;
    const storageKey = options.storageKey ? STORAGE_PREFIX + String(options.storageKey) : '';
    const storage = options.storage || (typeof localStorage !== 'undefined' ? localStorage : null);

    // Load persisted or use `initial`.
    let currentSize = Number(options.initial) || 200;
    if (storageKey && storage) {
        try {
            const raw = storage.getItem(storageKey);
            const persisted = raw != null ? Number(raw) : NaN;
            if (Number.isFinite(persisted) && persisted >= min && persisted <= max) {
                currentSize = persisted;
            }
        } catch (_) { /* noop */ }
    }

    const panels = Array.from(container.children).filter((n) => n.nodeType === 1);
    if (panels.length < 2) throw new Error('SharedComponents.Splitter.mount: container 至少两个 panel');
    const first = panels[0];

    // Create handle.
    const handle = doc.createElement('div');
    handle.className = `sc-splitter-handle sc-splitter-${orientation}`;
    handle.setAttribute('role', 'separator');
    handle.setAttribute('aria-orientation', orientation);
    handle.setAttribute('aria-valuemin', String(min));
    handle.setAttribute('aria-valuemax', String(max));
    handle.setAttribute('aria-valuenow', String(currentSize));
    handle.setAttribute('tabindex', '0');
    handle.setAttribute('data-splitter-storage', options.storageKey ? escapeAttrLocal(options.storageKey) : '');
    container.insertBefore(handle, panels[1]);

    function _apply(size) {
        const clamped = Math.max(min, Math.min(max, Number(size) || 0));
        currentSize = clamped;
        if (isVertical) {
            first.style.width = `${clamped}px`;
        } else {
            first.style.height = `${clamped}px`;
        }
        handle.setAttribute('aria-valuenow', String(clamped));
        if (storageKey && storage) {
            try { storage.setItem(storageKey, String(clamped)); } catch (_) { /* noop */ }
        }
        if (onResize) {
            try { onResize(clamped); } catch (_) { /* noop */ }
        }
    }
    _apply(currentSize);

    let dragging = false;
    let startPointer = 0;
    let startSize = currentSize;

    function onDown(e) {
        dragging = true;
        startPointer = isVertical ? e.clientX : e.clientY;
        startSize = currentSize;
        try { handle.setPointerCapture && handle.setPointerCapture(e.pointerId); } catch (_) { /* noop */ }
        e.preventDefault && e.preventDefault();
    }
    function onMove(e) {
        if (!dragging) return;
        const now = isVertical ? e.clientX : e.clientY;
        _apply(startSize + (now - startPointer));
    }
    function onUp(e) {
        if (!dragging) return;
        dragging = false;
        try { handle.releasePointerCapture && handle.releasePointerCapture(e.pointerId); } catch (_) { /* noop */ }
    }
    function onKey(e) {
        const step = e.shiftKey ? 20 : 5;
        if (isVertical) {
            if (e.key === 'ArrowLeft') { e.preventDefault && e.preventDefault(); _apply(currentSize - step); }
            else if (e.key === 'ArrowRight') { e.preventDefault && e.preventDefault(); _apply(currentSize + step); }
        } else {
            if (e.key === 'ArrowUp') { e.preventDefault && e.preventDefault(); _apply(currentSize - step); }
            else if (e.key === 'ArrowDown') { e.preventDefault && e.preventDefault(); _apply(currentSize + step); }
        }
    }

    handle.addEventListener('pointerdown', onDown);
    handle.addEventListener('pointermove', onMove);
    handle.addEventListener('pointerup', onUp);
    handle.addEventListener('pointercancel', onUp);
    handle.addEventListener('keydown', onKey);

    let unmounted = false;
    function unmount() {
        if (unmounted) return;
        unmounted = true;
        try { handle.removeEventListener('pointerdown', onDown); } catch (_) { /* noop */ }
        try { handle.removeEventListener('pointermove', onMove); } catch (_) { /* noop */ }
        try { handle.removeEventListener('pointerup', onUp); } catch (_) { /* noop */ }
        try { handle.removeEventListener('pointercancel', onUp); } catch (_) { /* noop */ }
        try { handle.removeEventListener('keydown', onKey); } catch (_) { /* noop */ }
        if (handle.parentNode) {
            try { handle.parentNode.removeChild(handle); } catch (_) { /* noop */ }
        }
    }

    return {
        setSize(size) { _apply(size); },
        getSize() { return currentSize; },
        unmount,
        handle,
    };
}

export const _internal = Object.freeze({ STORAGE_PREFIX, escapeAttr: escapeAttrLocal });

const Splitter = { mount, _internal };
export default Splitter;
