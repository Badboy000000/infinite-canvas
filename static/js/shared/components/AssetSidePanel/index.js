// static/js/shared/components/AssetSidePanel/index.js
//
// Wave 3-K 前端 PR-9 (保守渲染层): AssetSidePanel 单例组件入口。
//
// **契约(硬约束)**:
//   - `AssetSidePanel.renderHtml(templateKey, ...args)` -> HTML string
//   - `AssetSidePanel.render(templateKey, ...args, opts)` -> HTMLElement | string
//     (若有 document 则 htmlToElement, 否则直接返回 string)
//
// **保守渲染层硬约束**(参见 domTemplates.js 顶注):
//   - ❌ 不动 96 处 canvas.js state/fetch/upload/drag 代码
//   - ❌ 不动 activeCanvasAssetLibraryId / canvasAssetLibrary 状态语义
//   - ❌ 不动 canvasAssetThumbHtml / canvasAssetItemKind (由 consumer 传入)
//   - ✅ 只提供 HTML 模板生成 API, 状态与事件仍在 canvas.js
//
// **GM-15 dormant seam**:AssetSidePanel state 层是 rendering consumed only;
// state 层 dormant seam 待 PR-11+ / CB-P5-09 承接。
//
// 参照 NodeStatusView/index.js pattern (前端 PR-8), 零构建 / 零依赖 / 原生 ES module.

import {
    renderLibraryOption,
    renderCategoryOption,
    renderAssetActions,
    renderAssetItemCard,
    renderEmptyState,
    renderAssetGrid,
    ASSET_SIDE_PANEL_TEMPLATES,
    _internal,
} from './domTemplates.js';

/**
 * 5-6 template canonical 分派表, key -> function.
 *
 * canvas.js consumer 若走"通用 renderHtml(templateKey, ...args)"入口, 通过此
 * 分派;若消费点直接 import 具名函数 (`renderLibraryOption`), 亦可直接使用。
 *
 * 当前保守语义:consumer 通过具名 export 消费, 通用分派表为将来 UI 迁移预留。
 */
const TEMPLATE_DISPATCH = Object.freeze({
    library_option: renderLibraryOption,
    category_option: renderCategoryOption,
    asset_actions: renderAssetActions,
    asset_item_card: renderAssetItemCard,
    empty_state: renderEmptyState,
    asset_grid: renderAssetGrid,
});

/**
 * 通用 renderHtml 入口 —— 通过 templateKey 分派到对应 template.
 *
 * @param {string} templateKey  ASSET_SIDE_PANEL_TEMPLATES 中的 canonical key
 * @param  {...any} args        template 具体参数 (与 domTemplates.js 各函数签名一致)
 * @returns {string}
 */
function renderHtml(templateKey, ...args) {
    const fn = TEMPLATE_DISPATCH[templateKey];
    if (!fn) return '';
    return fn.apply(null, args);
}

/**
 * DOM 提升:若有 document, 把 HTML string 提升为 HTMLElement (若含单一根元素)
 * 或 DocumentFragment (若含多个兄弟节点, 如 asset grid 场景)。
 *
 * 当前 canvas.js 消费点全走 innerHTML 拼接 (`canvasAssetGrid.innerHTML = ...`),
 * 此函数主要为将来 pixel-perfect 迁移 + 单元测试留 API。
 *
 * @returns {HTMLElement | DocumentFragment | string}
 */
function render(templateKey, ...rest) {
    // 最后一个参数若为 `{document: ...}` opts 对象, 取出;否则视作 template 参数。
    let opts = null;
    let args = rest;
    if (rest.length > 0) {
        const tail = rest[rest.length - 1];
        if (tail && typeof tail === 'object' && !Array.isArray(tail) &&
            (Object.prototype.hasOwnProperty.call(tail, 'document') ||
             Object.prototype.hasOwnProperty.call(tail, '_asOpts'))) {
            opts = tail;
            args = rest.slice(0, -1);
        }
    }
    const html = renderHtml(templateKey, ...args);
    const doc = (opts && opts.document) || (typeof document !== 'undefined' ? document : null);
    if (!doc) return html;
    const tpl = doc.createElement('template');
    tpl.innerHTML = html;
    const content = tpl.content;
    if (!content) return html;
    if (content.childNodes && content.childNodes.length === 1) {
        return content.firstChild;
    }
    // 多子节点场景:返回整个 fragment
    return content;
}

const AssetSidePanel = {
    render,
    renderHtml,
    // 具名 template exports (推荐使用, 便于 tree-shaking + 类型自检)
    renderLibraryOption,
    renderCategoryOption,
    renderAssetActions,
    renderAssetItemCard,
    renderEmptyState,
    renderAssetGrid,
    ASSET_SIDE_PANEL_TEMPLATES,
    _internal,
};

export default AssetSidePanel;
export {
    render,
    renderHtml,
    renderLibraryOption,
    renderCategoryOption,
    renderAssetActions,
    renderAssetItemCard,
    renderEmptyState,
    renderAssetGrid,
    ASSET_SIDE_PANEL_TEMPLATES,
};
