// static/js/shared/components/AssetSidePanel/domTemplates.js
//
// Wave 3-K 前端 PR-9 (保守渲染层): AssetSidePanel HTML 片段字面量库。
//
// **契约来源(硬约束)**:剥自 `static/js/canvas.js::renderCanvasAssetLibrary`
// (行 6891-6961), 覆盖 4 类 HTML 片段:
//   1. 资产库 <option> (行 6897)
//   2. 资产分组 <option> (行 6902-6906)
//   3. 资产 item card (行 6917-6928, 含 workflow / local mode 支路 6922-6925)
//   4. 空态占位 (行 6928 尾部 `<div class="canvas-asset-empty">`)
//
// **保守渲染层硬约束**:
//   - ❌ 不动 fetch/upload/drag/rename/delete endpoint 契约
//   - ❌ 不动 canvasAssetLibrary / activeCanvasAssetLibraryId / activeCanvasAssetCategoryId
//        状态语义
//   - ❌ 不动 canvasAssetThumbHtml (仍在 canvas.js:6781)
//   - ❌ 不动 canvasPreviewImgHtml / canvasVideoPreviewHtml
//   - ✅ 只剥 HTML 模板字面量 + i18n label + CSS class 映射
//
// **等价性三轴(GM-13)**:
//   - 每个 template 与 canvas.js 原字符串**runtime-output-byte-equal**
//     (T60/T61 通过 Node subprocess 独立执行 + 逐字节比对验证)
//   - 源码文本 NOT byte-equal (原代码单行内嵌 vs 本文件多行 template)
//
// **GM-14 死路检测**:
//   - 5 个 template (renderLibraryOption / renderCategoryOption / renderAssetItemCard /
//     renderAssetActions / renderEmptyState) 全部有实际消费点
//   - 无 dead-canonical 子集
//
// **GM-15 dormant seam**:
//   - AssetSidePanel state 层(96 处 canvas.js 上下文)是 rendering consumed only
//   - state 层为 dormant seam, 待 PR-11+ / CB-P5-09 承接
//
// 零构建 / 零依赖 / 原生 ES module.

/**
 * escapeHtml 内嵌副本 —— **runtime-output-byte-equal** 于:
 *   - `static/js/canvas.js::escapeHtml`      (14856 行)
 *   - `static/js/smart-canvas.js::escapeHtml` (464 行)
 *   - `static/js/modules/node/registry/NodeRenderRegistry.js::escapeHtml`
 *   - `static/js/shared/components/NodeStatusView/index.js::escapeHtml`
 *   - `static/js/shared/components/ProviderSelector/providerOptions.js::escapeHtml`
 * 六处副本源码文本 NOT byte-equal, 但运行时输出逐字节相等 (T60/T63 subprocess 验证)。
 */
function escapeHtml(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g, (s) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[s]));
}

/**
 * escapeAttr 内嵌副本 —— alias to escapeHtml, byte-equivalent 于 canvas.js:14857。
 */
function escapeAttr(str) {
    return escapeHtml(str);
}

/**
 * 资产库单个 <option> HTML.
 *
 * 原 canvas.js:6897:
 *   libs.map(lib => `<option value="${escapeAttr(lib.id)}" ${lib.id === activeCanvasAssetLibraryId ? 'selected' : ''}>${escapeHtml(lib.name || '资产库')}</option>`).join('')
 *
 * **runtime-output-byte-equal** 于原 map 回调输出 (T60 断言).
 *
 * @param {{id:string,name?:string}} lib
 * @param {string} activeLibraryId
 */
export function renderLibraryOption(lib, activeLibraryId) {
    const id = lib && lib.id;
    const sel = id === activeLibraryId ? 'selected' : '';
    const label = (lib && lib.name) || '资产库';
    return `<option value="${escapeAttr(id)}" ${sel}>${escapeHtml(label)}</option>`;
}

/**
 * 资产分组单个 <option> HTML.
 *
 * 原 canvas.js:6902-6906:
 *   cats.map(cat => {
 *       const type = String(cat.type || 'image').toLowerCase();
 *       const prefix = type === 'workflow' ? '工作流 / ' : '';
 *       return `<option value="${escapeAttr(cat.id)}" ${cat.id === activeCanvasAssetCategoryId ? 'selected' : ''}>${escapeHtml(prefix + (cat.name || '默认分组'))}</option>`;
 *   }).join('')
 *
 * **runtime-output-byte-equal** 于原 map 回调输出 (T60 断言).
 *
 * @param {{id:string,name?:string,type?:string}} cat
 * @param {string} activeCategoryId
 */
export function renderCategoryOption(cat, activeCategoryId) {
    const id = cat && cat.id;
    const type = String((cat && cat.type) || 'image').toLowerCase();
    const prefix = type === 'workflow' ? '工作流 / ' : '';
    const sel = id === activeCategoryId ? 'selected' : '';
    const label = prefix + ((cat && cat.name) || '默认分组');
    return `<option value="${escapeAttr(id)}" ${sel}>${escapeHtml(label)}</option>`;
}

/**
 * 资产 item card 元数据行右侧的 actions 区块 (local 模式 vs 云端模式).
 *
 * 原 canvas.js:6922-6925 (二元支路):
 *   ${localMode
 *       ? `<span class="canvas-asset-local-tag">本地</span>`
 *       : `<button class="canvas-asset-action" ...>...</button>
 *          <button class="canvas-asset-action danger" ...>...</button>`}
 *
 * **runtime-output-byte-equal** 于原三元表达式输出 (T60 断言).
 *
 * @param {{id?:string}} item
 * @param {boolean} localMode
 */
export function renderAssetActions(item, localMode) {
    if (localMode) {
        return `<span class="canvas-asset-local-tag">本地</span>`;
    }
    const id = (item && item.id) || '';
    return `<button class="canvas-asset-action" type="button" data-canvas-asset-rename="${escapeAttr(id)}" title="重命名" aria-label="重命名"><i data-lucide="pencil" class="w-4 h-4"></i></button>
                       <button class="canvas-asset-action danger" type="button" data-canvas-asset-delete="${escapeAttr(id)}" title="删除" aria-label="删除"><i data-lucide="trash-2" class="w-4 h-4"></i></button>`;
}

/**
 * 资产 item card HTML.
 *
 * 原 canvas.js:6917-6927:
 *   items.map(item => `
 *       <div class="canvas-asset-item" draggable="true" data-asset-id="${escapeAttr(item.id || '')}" data-url="${escapeAttr(item.url)}" data-name="${escapeAttr(item.name || 'asset')}" data-kind="${escapeAttr(canvasAssetItemKind(item))}">
 *           ${canvasAssetThumbHtml(item)}
 *           <div class="canvas-asset-meta">
 *               <span class="canvas-asset-name" title="${escapeAttr(item.name || '')}">${escapeHtml(item.name || 'asset')}</span>
 *               ${localMode ? `<span class="canvas-asset-local-tag">本地</span>` : `<button ...>...</button>...`}
 *           </div>
 *       </div>
 *   `)
 *
 * **runtime-output-byte-equal** 于原 map 回调输出 —— 前提是 thumbHtml 和 kind
 * 由调用方传入(避免本模块依赖 canvasAssetThumbHtml/canvasAssetItemKind 状态函数).
 *
 * **数据契约**(调用方必须遵守):
 *   - thumbHtml: 已由 canvas.js::canvasAssetThumbHtml(item) 生成
 *   - kind:      已由 canvas.js::canvasAssetItemKind(item) 计算得到
 *
 * @param {{id?:string,url?:string,name?:string}} item
 * @param {{thumbHtml:string, kind:string, localMode:boolean}} ctx
 */
export function renderAssetItemCard(item, ctx) {
    const id = (item && item.id) || '';
    const url = (item && item.url) || '';
    const name = (item && item.name) || 'asset';
    const nameForTitle = (item && item.name) || '';
    const kind = (ctx && ctx.kind) || '';
    const thumbHtml = (ctx && ctx.thumbHtml) || '';
    const localMode = !!(ctx && ctx.localMode);
    return `
        <div class="canvas-asset-item" draggable="true" data-asset-id="${escapeAttr(id)}" data-url="${escapeAttr(url)}" data-name="${escapeAttr(name)}" data-kind="${escapeAttr(kind)}">
            ${thumbHtml}
            <div class="canvas-asset-meta">
                <span class="canvas-asset-name" title="${escapeAttr(nameForTitle)}">${escapeHtml(name)}</span>
                ${renderAssetActions(item, localMode)}
            </div>
        </div>
    `;
}

/**
 * 空态占位.
 *
 * 原 canvas.js:6928 尾部:
 *   items.length ? items.map(...).join('') : `<div class="canvas-asset-empty">${escapeHtml(localMode ? '暂无本地素材，请在素材库管理中上传' : '当前分组还没有资产')}</div>`
 *
 * **runtime-output-byte-equal** 于原三元 fallback 输出 (T60 断言).
 *
 * @param {boolean} localMode
 */
export function renderEmptyState(localMode) {
    const text = localMode ? '暂无本地素材，请在素材库管理中上传' : '当前分组还没有资产';
    return `<div class="canvas-asset-empty">${escapeHtml(text)}</div>`;
}

/**
 * 资产 grid HTML (items 序列或空态) —— 直接对应 canvas.js:6917-6928 的
 * `canvasAssetGrid.innerHTML = ...` 值。
 *
 * **runtime-output-byte-equal** 于原表达式输出 (T60 断言).
 *
 * 数据契约:
 *   - itemsWithCtx: [{ item, ctx: {thumbHtml, kind, localMode} }, ...]
 *
 * @param {Array<{item:object, ctx:object}>} itemsWithCtx
 * @param {boolean} localMode
 */
export function renderAssetGrid(itemsWithCtx, localMode) {
    if (!Array.isArray(itemsWithCtx) || itemsWithCtx.length === 0) {
        return renderEmptyState(localMode);
    }
    return itemsWithCtx.map((entry) => renderAssetItemCard(entry.item, entry.ctx)).join('');
}

/**
 * 内部自省:测试可通过此 export 独立跑 escapeHtml/escapeAttr 定义体。
 */
export const _internal = Object.freeze({ escapeHtml, escapeAttr });

/**
 * 5-8 个 template canonical 支持集显式声明 (GM-14 死路检测支撑).
 *
 * 每个 canonical 都必须在 canvas.js consumer 侧有实际消费点。
 */
export const ASSET_SIDE_PANEL_TEMPLATES = Object.freeze({
    library_option: 'renderLibraryOption',
    category_option: 'renderCategoryOption',
    asset_actions: 'renderAssetActions',
    asset_item_card: 'renderAssetItemCard',
    empty_state: 'renderEmptyState',
    asset_grid: 'renderAssetGrid',
});
