// static/js/shared/components/ProviderSelector/index.js
//
// Wave 3-K 前端 PR-9 (保守渲染层): ProviderSelector 单例组件入口。
//
// 参见 `providerOptions.js` 顶注的完整契约 / 三轴等价性 / 死路检测 / dormant seam
// 治理机制说明。
//
// 本 index.js 只做 **薄封装**:
//   - renderHtml(variant, providers, selectedId, opts) -> HTML string
//   - render(...)     -> 若有 document 则返回 HTMLSelectElement, 否则 HTML string
//     (当前 canvas.js 消费点全部使用 innerHTML 拼接 -> renderHtml 场景)
//   - 提供命名 export 便于 tree-shaking (虽然当前无构建, 但为将来一致)
//
// **不做**:
//   - 不动 chatApiProviders / imageApiProviders / videoApiProviders 数据源函数
//   - 不动 select 元素外壳 (由 canvas.js consumer 保持 `<select ...>` 属性)
//   - 不引入 onchange 事件绑定
//
// **零构建 / 零依赖 / 原生 ES module。**

import {
    renderOption,
    renderOptionList,
    renderEmptyOption,
    PROVIDER_SELECTOR_VARIANTS,
    _internal,
} from './providerOptions.js';

/**
 * 生成 <option> 序列 HTML string, 供 canvas.js 的 `<select>` innerHTML 拼接。
 *
 * @param {'chat'|'image'|'video'} variantKey  3 变体之一
 * @param {Array<{id,name}>} providers          providers 列表 (由调用方从
 *                                              chatApiProviders / imageApiProviders /
 *                                              videoApiProviders 传入)
 * @param {string} selectedId                   已 resolve 的 selectedId
 * @param {object} [opts]
 * @param {string} [opts.emptyLabel]            image 变体在 providers 为空时的占位文案
 *                                              (调用方传 tr('canvas.noApiProviders') || '暂无 API 平台')
 * @returns {string}                            option 序列 HTML string
 */
function renderHtml(variantKey, providers, selectedId, opts) {
    const variant = PROVIDER_SELECTOR_VARIANTS[variantKey];
    if (!variant) {
        // 未知 variant fallback:直接走原始 map+join, 与 chat/video 变体行为一致
        return renderOptionList(providers, selectedId);
    }
    // image 变体:providers 为空时输出 disabled 占位 option
    // (与 canvas.js:684 legacy 一致)
    if (variant.has_empty_placeholder && (!providers || providers.length === 0)) {
        const label = (opts && opts.emptyLabel) || '';
        return renderEmptyOption(label);
    }
    return renderOptionList(providers, selectedId);
}

/**
 * DOM 提升:若环境有 document, 把 option HTML string 提升为 DocumentFragment
 * (含多个 <option> 元素)。
 *
 * 当前 canvas.js 消费点全走 innerHTML 拼接 (`<select ...>${optionHtml}</select>`),
 * 因此此函数主要为将来消费点/单元测试留 API。
 *
 * @returns {DocumentFragment | string}
 */
function render(variantKey, providers, selectedId, opts) {
    const options = opts || {};
    const doc = options.document || (typeof document !== 'undefined' ? document : null);
    const html = renderHtml(variantKey, providers, selectedId, options);
    if (!doc) return html;
    const tpl = doc.createElement('template');
    tpl.innerHTML = `<select>${html}</select>`;
    const select = tpl.content && tpl.content.firstChild;
    if (!select) return html;
    // 返回 DocumentFragment (含多个 <option>) —— 调用方可直接 replaceChildren(...)
    const frag = doc.createDocumentFragment();
    while (select.firstChild) frag.appendChild(select.firstChild);
    return frag;
}

const ProviderSelector = {
    render,
    renderHtml,
    renderOption,
    renderOptionList,
    renderEmptyOption,
    PROVIDER_SELECTOR_VARIANTS,
    _internal,
};

export default ProviderSelector;
export {
    render,
    renderHtml,
    renderOption,
    renderOptionList,
    renderEmptyOption,
    PROVIDER_SELECTOR_VARIANTS,
};
