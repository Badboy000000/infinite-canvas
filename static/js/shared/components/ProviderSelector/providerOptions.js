// static/js/shared/components/ProviderSelector/providerOptions.js
//
// Wave 3-K 前端 PR-9 (保守渲染层): ProviderSelector 3 变体 <option> 聚合层。
//
// **契约来源(硬约束)**:
//   - `static/js/canvas.js::chatProviderOptions`   (行 669-672)
//   - `static/js/canvas.js::providerOptions`       (行 681-686)
//   - `static/js/canvas.js::videoProviderOptions`  (行 708-711)
//   - `static/js/smart-canvas.js::chatProviderOptions` (行 2362-2365, 与 canvas.js 同 body)
//
// **提取规则**:三处 body 共享同一 `<option>` HTML 模板字面量:
//   `<option value="${escapeHtml(provider.id)}" ${provider.id === selected ? 'selected' : ''}>${escapeHtml(provider.name || provider.id)}</option>`
// 唯一差异只在:
//   1. providers 数据源函数(chatApiProviders / imageApiProviders / videoApiProviders)
//   2. resolveXxxProviderId 选定 fallback 语义
//   3. providerOptions 变体在 providers 为空时输出 disabled 占位 option (行 684)
//
// 本模块只剥离 **HTML 模板** + **empty state 文案 tokens**:
//   - `renderOption({id,name,selected})` -> 单个 <option> HTML string
//   - `renderOptionList(providers, selectedId)` -> 3 变体共享的 join('') 组装
//   - `renderEmptyOption(labelText)` -> `providerOptions` 变体在 providers 为空时用
//
// **不做**:
//   - ❌ 不动 chatApiProviders / imageApiProviders / videoApiProviders 数据源
//   - ❌ 不动 resolveChatProviderId / resolveImageProviderId / resolveVideoProviderId
//   - ❌ 不动 onchange 事件绑定
//   - ❌ 不引入 provider list 拉取 (fetch) 语义
//
// **等价性三轴(GM-13)**:
//   - `renderOption` + `renderOptionList` 与 canvas.js 三处 map(...).join('') 输出
//     对同一 provider 列表 + selectedId **runtime-output-byte-equal**
//     (T66/T67 通过 subprocess 独立执行 + 逐字节比对验证)
//   - 源码文本 NOT byte-equal (canvas.js 单行 map/join 模板 vs 本文件多行导出结构)
//   - 内嵌 escapeHtml 副本 -> **runtime-output-byte-equal** 于 canvas.js:14856
//     (T65b 通过 subprocess 独立跑四处定义体验证)
//
// **GM-14 死路检测**:
//   - 3 变体聚合中每一变体在 canvas.js/smart-canvas.js 都有至少 1 处**真实消费点**
//     (canvas.js:7992 chatProviderOptions / canvas.js:8274 providerOptions /
//      canvas.js:8595 videoProviderOptions), 无 dead-canonical 子集
//   - **不含** dormant seam:三变体全部当前活跃写入
//
// **GM-15 dormant seam**:
//   - ProviderSelector 组件层是 rendering consumed only; provider onchange 事件
//     handler / provider 列表状态管理仍在 canvas.js/smart-canvas.js
//   - state 层 dormant seam 待 PR-11+ 或 CB-P5-09 承接
//
// 零构建 / 零依赖 / 原生 ES module.

/**
 * escapeHtml 内嵌副本 —— **runtime-output-byte-equal** 于:
 *   - `static/js/canvas.js::escapeHtml`      (14856 行)
 *   - `static/js/smart-canvas.js::escapeHtml` (464 行)
 *   - `static/js/modules/node/registry/NodeRenderRegistry.js::escapeHtml`
 *   - `static/js/shared/components/NodeStatusView/index.js::escapeHtml`
 *
 * 源码文本 NOT byte-equal (canvas.js/smart-canvas 单行式 vs 多行式), 但对
 * 同一输入返回**逐字节相等**的字符串。T65b 通过 Node subprocess 独立跑五处
 * 定义体逐字节对比得到 runtime-output-byte-equal 证据。
 *
 * seam 期硬约束:零依赖、不允许引入 escape 工具库,故内嵌副本。
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
 * 单个 <option> HTML string 生成。
 *
 * legacy 模板 (canvas.js:671 / 685 / 710 三处一致):
 *   `<option value="${escapeHtml(provider.id)}" ${provider.id === selected ? 'selected' : ''}>${escapeHtml(provider.name || provider.id)}</option>`
 *
 * **runtime-output-byte-equal** 于原三处 map 回调输出(见 T66 断言)。
 *
 * @param {object} provider  {id, name}
 * @param {string} selectedId
 * @returns {string} HTML string
 */
export function renderOption(provider, selectedId) {
    const id = provider && provider.id;
    const isSelected = id === selectedId ? 'selected' : '';
    const label = (provider && (provider.name || provider.id)) || '';
    return `<option value="${escapeHtml(id)}" ${isSelected}>${escapeHtml(label)}</option>`;
}

/**
 * providers list -> 拼接的 <option> HTML string。
 *
 * legacy 模式:providers.map(provider => `<option ...>`).join('')
 * **runtime-output-byte-equal** 于原三处 map+join 输出。
 *
 * @param {Array<{id,name}>} providers
 * @param {string} selectedId
 * @returns {string}
 */
export function renderOptionList(providers, selectedId) {
    if (!Array.isArray(providers)) return '';
    return providers.map((p) => renderOption(p, selectedId)).join('');
}

/**
 * providers 为空时的 disabled 占位 option (canvas.js:684 providerOptions 变体).
 *
 * legacy 模板 (byte-equivalent 硬约束):
 *   `<option value="" disabled selected>${tr('canvas.noApiProviders') || '暂无 API 平台'}</option>`
 *
 * **不 escape labelText** —— legacy canvas.js 也未 escape (tr() 返回值直接插入).
 * 保守渲染层硬约束:seam 层不新增 escape 语义 (调用方职责).
 *
 * @param {string} labelText 已由调用方 i18n 解析后的文案 (调用方须保证不含 HTML sink)
 * @returns {string}
 */
export function renderEmptyOption(labelText) {
    return `<option value="" disabled selected>${labelText == null ? '' : String(labelText)}</option>`;
}

/**
 * 3 变体聚合注册表 —— 显式声明每个变体的 canonical key + 消费点(GM-14 死路检测证据)。
 *
 * consumer_sites 值来自 grep canvas.js/smart-canvas.js 得到的实际调用点行号
 * (Wave 3-K 分派时 Lead 单点核实, 每变体至少 1 处真实消费点)。
 */
export const PROVIDER_SELECTOR_VARIANTS = Object.freeze({
    chat: Object.freeze({
        key: 'chat',
        legacyFn: 'chatProviderOptions',
        consumer_sites: Object.freeze([
            'canvas.js:7992 (LLM node)',
            'smart-canvas.js:6991 (prompt-node)',
        ]),
    }),
    image: Object.freeze({
        key: 'image',
        legacyFn: 'providerOptions',
        consumer_sites: Object.freeze([
            'canvas.js:8274 (generator node)',
        ]),
        has_empty_placeholder: true,
    }),
    video: Object.freeze({
        key: 'video',
        legacyFn: 'videoProviderOptions',
        consumer_sites: Object.freeze([
            'canvas.js:8595 (video node)',
        ]),
    }),
});

/**
 * 内部自省:测试可通过此 export 独立跑 escapeHtml 定义体。
 */
export const _internal = Object.freeze({ escapeHtml });

const defaultExport = {
    renderOption,
    renderOptionList,
    renderEmptyOption,
    PROVIDER_SELECTOR_VARIANTS,
    _internal,
};

export default defaultExport;
