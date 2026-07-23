// static/js/modules/asset/AssetSidePanel/index.js
//
// Wave 3-N.6 Batch 1 主线 B · 前端 PR-8 · **候选 A GM-14 第 5 次实证**。
//
// 语义分层(硬约束 · 与 Lead 拍板一致):
//   - 本文件承担 **state + lifecycle**(mount / unmount / refresh)
//   - `shared/components/AssetSidePanel/`(Wave 3-K PR-9 保守渲染层)承担
//     **纯模板函数**(renderHtml / renderLibraryOption / ... zero DOM state)
//   - 二者平级共存,不同路径(避免同名混淆):
//     * `modules/asset/AssetSidePanel/`  = 有状态组件
//     * `shared/components/AssetSidePanel/` = 纯模板层
//   - 消费:本文件 `mount()` 调用 shared/components 的 `renderHtml(...)` 生成
//     HTML,再直接注入 container,并挂 store subscribe + click 委托
//
// 契约(硬约束):
//   - mount(container, {onAssetPick, filterCategoryType?}) -> instance
//   - unmount() -> void · 幂等 · 清 store subscribe / event listener
//   - refresh() -> void · 手动触发重渲染
//   - assetLibraryStore 订阅:store 变化 → refresh
//   - click 委托:`.canvas-asset-item[data-asset-id]` -> onAssetPick(item)
//   - 零构建 / 零依赖 / native ES module
//
// GM-16 复核(codegraph):新增公开符号 `AssetSidePanel`(default export)+ mount +
//   unmount + refresh · 与 `shared/components/AssetSidePanel/` 同名不同路径 ·
//   Lead 候选 A 拍板允许(顶注交叉引用)
//
// zero-touch 承接:不改 `shared/components/AssetSidePanel/`(git diff baseline 空)

import { assetLibraryStore } from '../../../shared/stores/assetLibraryStore.js';
import {
    renderLibraryOption,
    renderCategoryOption,
    renderAssetGrid,
} from '../../../shared/components/AssetSidePanel/index.js';

function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[s]));
}
const escapeAttr = escapeHtml;

/**
 * Compute default thumb HTML for an asset item — 保守 fallback(没 canvas.js
 * 侧 `canvasAssetThumbHtml` 时的最小视图)。零 innerHTML 注入用户内容;url
 * 走 escapeAttr。
 */
function _defaultThumbHtml(item) {
    const url = (item && item.url) || '';
    return `<div class="canvas-asset-thumb"><img src="${escapeAttr(url)}" alt="" loading="lazy"></div>`;
}

function _itemKind(item) {
    const url = String((item && item.url) || '').toLowerCase();
    const kind = String((item && (item.kind || item.type)) || '').toLowerCase();
    if (kind.includes('video') || /\.(mp4|webm|mov|m4v)(\?|#|$)/.test(url)) return 'video';
    if (kind.includes('audio') || /\.(mp3|wav|flac|ogg|m4a)(\?|#|$)/.test(url)) return 'audio';
    return 'image';
}

/**
 * Build items-with-context array for renderAssetGrid template.
 *
 * @param {Array<object>} items
 * @param {{ thumbFn?:(item:object)=>string, kindFn?:(item:object)=>string, localMode?:boolean }} ctx
 */
function _buildItemsWithCtx(items, ctx) {
    const thumbFn = (ctx && typeof ctx.thumbFn === 'function') ? ctx.thumbFn : _defaultThumbHtml;
    const kindFn = (ctx && typeof ctx.kindFn === 'function') ? ctx.kindFn : _itemKind;
    const localMode = !!(ctx && ctx.localMode);
    return (items || []).map((item) => ({
        item,
        ctx: {
            thumbHtml: thumbFn(item),
            kind: kindFn(item),
            localMode,
        },
    }));
}

/**
 * mount an AssetSidePanel into a container. Idempotent — repeated mount into
 * the same container tears down the previous instance first.
 *
 * @param {HTMLElement} container
 * @param {object} opts
 * @param {(item:object)=>void} [opts.onAssetPick]
 * @param {(item:object)=>string} [opts.thumbFn]  由调用方注入(canvas.js 可传
 *                                                 canvasAssetThumbHtml)
 * @param {(item:object)=>string} [opts.kindFn]   由调用方注入
 * @param {boolean} [opts.localMode]
 * @param {'image'|'workflow'} [opts.categoryType='image']
 */
export function mount(container, opts) {
    const options = opts || {};
    if (!container || !container.appendChild) {
        throw new Error('AssetSidePanel.mount: 需要 container HTMLElement');
    }
    // 幂等:若 container 已有实例,先 unmount。
    if (container.__assetSidePanelInstance) {
        try { container.__assetSidePanelInstance.unmount(); } catch (_) { /* noop */ }
    }

    const state = {
        librarySelectId: `asp-lib-${Math.random().toString(36).slice(2, 8)}`,
        categorySelectId: `asp-cat-${Math.random().toString(36).slice(2, 8)}`,
        gridId: `asp-grid-${Math.random().toString(36).slice(2, 8)}`,
        activeLibraryId: '',
        activeCategoryId: '',
    };

    function _getLibraries() {
        const lib = assetLibraryStore.state && assetLibraryStore.state.library;
        return (lib && Array.isArray(lib.libraries)) ? lib.libraries : [];
    }
    function _activeLibrary() {
        const libs = _getLibraries();
        const wanted = state.activeLibraryId || assetLibraryStore.state.active_library_id || '';
        return libs.find((l) => l && l.id === wanted) || libs[0] || null;
    }
    function _categories() {
        const cats = (_activeLibrary()?.categories) || [];
        const wantType = options.categoryType || 'image';
        return cats.filter((c) => String((c && c.type) || 'image') === wantType);
    }
    function _activeCategory() {
        const cats = _categories();
        const wanted = state.activeCategoryId;
        return cats.find((c) => c && c.id === wanted) || cats[0] || null;
    }
    function _items() {
        const cat = _activeCategory();
        return (cat && Array.isArray(cat.items)) ? cat.items : [];
    }

    function _renderShell() {
        // 首帧结构 — 后续 refresh 只改 innerHTML 内部
        container.innerHTML = `
            <div class="asp-root" role="region" aria-label="资产库">
                <div class="asp-header">
                    <label>资产库
                        <select class="asp-library-select" id="${escapeAttr(state.librarySelectId)}"></select>
                    </label>
                    <label>分组
                        <select class="asp-category-select" id="${escapeAttr(state.categorySelectId)}"></select>
                    </label>
                </div>
                <div class="asp-grid" id="${escapeAttr(state.gridId)}"></div>
            </div>
        `;
    }

    function refresh() {
        if (!container.querySelector('.asp-root')) _renderShell();
        const libs = _getLibraries();
        const active = _activeLibrary();
        state.activeLibraryId = active ? active.id : '';
        const cats = _categories();
        const activeCat = _activeCategory();
        state.activeCategoryId = activeCat ? activeCat.id : '';

        const libSel = container.querySelector(`#${CSS.escape(state.librarySelectId)}`);
        const catSel = container.querySelector(`#${CSS.escape(state.categorySelectId)}`);
        const grid = container.querySelector(`#${CSS.escape(state.gridId)}`);

        // Consume shared/components/ pure templates.
        if (libSel) {
            libSel.innerHTML = libs.map((lib) => renderLibraryOption(lib, state.activeLibraryId)).join('');
        }
        if (catSel) {
            catSel.innerHTML = cats.map((cat) => renderCategoryOption(cat, state.activeCategoryId)).join('');
        }
        if (grid) {
            const itemsWithCtx = _buildItemsWithCtx(_items(), {
                thumbFn: options.thumbFn,
                kindFn: options.kindFn,
                localMode: !!options.localMode,
            });
            grid.innerHTML = renderAssetGrid(itemsWithCtx, !!options.localMode);
        }
    }

    function _onLibraryChange(e) {
        state.activeLibraryId = e && e.target && e.target.value ? String(e.target.value) : '';
        state.activeCategoryId = '';
        refresh();
    }
    function _onCategoryChange(e) {
        state.activeCategoryId = e && e.target && e.target.value ? String(e.target.value) : '';
        refresh();
    }
    function _onGridClick(e) {
        const card = e.target.closest && e.target.closest('.canvas-asset-item[data-asset-id]');
        if (!card) return;
        const assetId = card.getAttribute('data-asset-id') || '';
        const items = _items();
        const picked = items.find((it) => it && (it.id || '') === assetId) || null;
        if (typeof options.onAssetPick === 'function') {
            try { options.onAssetPick(picked || { id: assetId, url: card.getAttribute('data-url') || '' }); }
            catch (err) {
                if (typeof console !== 'undefined' && console.error) console.error('[AssetSidePanel] onAssetPick', err);
            }
        }
    }

    _renderShell();
    // Bind event delegation once — shell is stable.
    container.addEventListener('change', function (e) {
        const t = e && e.target;
        if (!t) return;
        if (t.id === state.librarySelectId) _onLibraryChange(e);
        else if (t.id === state.categorySelectId) _onCategoryChange(e);
    });
    container.addEventListener('click', _onGridClick);

    // Subscribe to the store — refresh on any revision bump.
    const unsubscribe = assetLibraryStore.subscribe(() => { refresh(); });
    refresh();

    let unmounted = false;
    function unmount() {
        if (unmounted) return;
        unmounted = true;
        try { unsubscribe && unsubscribe(); } catch (_) { /* noop */ }
        try { container.removeEventListener('click', _onGridClick); } catch (_) { /* noop */ }
        container.innerHTML = '';
        container.__assetSidePanelInstance = null;
    }

    const instance = { mount: null, unmount, refresh, root: container };
    container.__assetSidePanelInstance = instance;
    return instance;
}

/** 幂等关闭:优先关最近 mount 到 container 的实例。 */
export function unmount(container) {
    if (container && container.__assetSidePanelInstance) {
        try { container.__assetSidePanelInstance.unmount(); } catch (_) { /* noop */ }
    }
}

/** 无实例时不抛错;有则触发 refresh。 */
export function refresh(container) {
    if (container && container.__assetSidePanelInstance) {
        try { container.__assetSidePanelInstance.refresh(); } catch (_) { /* noop */ }
    }
}

const AssetSidePanel = { mount, unmount, refresh };
export default AssetSidePanel;
